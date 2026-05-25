"""Tests for the gbif.query bridge tool.

All tests are hermetic: AgenticPlug is mocked with httpx.MockTransport. A
small Parquet fixture is built in-memory from a pandas DataFrame so we do not
need any network or cluster.
"""

from __future__ import annotations

import base64
import io
import unittest

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tools.gbif_cluster import (
    EXPECTED_COLUMNS,
    GbifClusterError,
    query_gbif_cluster,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _fixture_parquet_b64(rows: int = 3) -> str:
    """Build a tiny in-memory Parquet payload that matches the contract schema."""
    df = pd.DataFrame({
        "decimalLatitude":  [54.1, 55.2, 56.3][:rows],
        "decimalLongitude": [-3.1, -2.2, -1.3][:rows],
        "species":          ["Caligus elongatus"] * rows,
        "taxonKey":         [2227682] * rows,
        "year":             [2018, 2019, 2020][:rows],
        "month":            [5, 6, 7][:rows],
        "basisOfRecord":    ["HUMAN_OBSERVATION"] * rows,
    })
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="zstd")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ok_envelope(rows: int = 3) -> dict:
    return {
        "status": "ok",
        "job_id": "abc123",
        "row_count": rows,
        "schema": list(EXPECTED_COLUMNS),
        "encoding": "parquet+base64",
        "data": _fixture_parquet_b64(rows),
    }


def _client_with_handler(handler) -> httpx.AsyncClient:
    """Return an httpx.AsyncClient whose transport invokes ``handler``."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=10.0)


# ── Happy path ─────────────────────────────────────────────────────────────


class HappyPath(unittest.IsolatedAsyncioTestCase):
    async def test_returns_dataframe_with_expected_schema(self):
        received: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            received["url"] = str(request.url)
            received["headers"] = dict(request.headers)
            received["body"] = request.read().decode()
            return httpx.Response(200, json=_ok_envelope(rows=3))

        async with _client_with_handler(handler) as client:
            df = await query_gbif_cluster(
                agenticplug_url="http://broker",
                session_id="sess-xyz",
                species_name="Caligus elongatus",
                limit=100,
                http_client=client,
            )

        self.assertEqual(len(df), 3)
        self.assertEqual(list(df.columns), list(EXPECTED_COLUMNS))
        self.assertEqual(received["url"], "http://broker/v1/capabilities")
        self.assertIn("Bearer sess-xyz", received["headers"]["authorization"])
        import json as _json
        body_obj = _json.loads(received["body"])
        self.assertEqual(body_obj["capability"], "gbif.query")
        self.assertEqual(body_obj["args"]["species_name"], "Caligus elongatus")

    async def test_passes_all_optional_filters(self):
        seen_args: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            seen_args.update(json.loads(request.read())["args"])
            return httpx.Response(200, json=_ok_envelope(rows=1))

        async with _client_with_handler(handler) as client:
            await query_gbif_cluster(
                agenticplug_url="http://broker",
                session_id="s",
                species_name="x",
                taxon_key=12345,
                bbox=(-10.0, 40.0, 20.0, 60.0),
                year_range=(2010, 2023),
                limit=42,
                http_client=client,
            )

        self.assertEqual(seen_args["taxon_key"], 12345)
        self.assertEqual(seen_args["bbox"], [-10.0, 40.0, 20.0, 60.0])
        self.assertEqual(seen_args["year_range"], [2010, 2023])
        self.assertEqual(seen_args["limit"], 42)


# ── Validation (client-side, no HTTP call) ────────────────────────────────


class ClientSideValidation(unittest.IsolatedAsyncioTestCase):
    async def _fails_with(self, **kwargs) -> str:
        called = False

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            nonlocal called
            called = True
            return httpx.Response(200, json=_ok_envelope())

        async with _client_with_handler(handler) as client:
            with self.assertRaises(GbifClusterError) as ctx:
                await query_gbif_cluster(
                    agenticplug_url="http://broker",
                    session_id="s",
                    http_client=client,
                    **kwargs,
                )
        self.assertFalse(called, "validation must short-circuit before HTTP")
        return ctx.exception.code

    async def test_species_name_with_shell_meta_rejected(self):
        self.assertEqual(await self._fails_with(species_name="evil; rm -rf /"), "invalid_spec")

    async def test_species_name_too_long_rejected(self):
        self.assertEqual(await self._fails_with(species_name="x" * 1000), "invalid_spec")

    async def test_taxon_key_out_of_range_rejected(self):
        self.assertEqual(await self._fails_with(taxon_key=-1), "invalid_spec")

    async def test_bbox_unordered_rejected(self):
        self.assertEqual(
            await self._fails_with(bbox=(20.0, 40.0, -10.0, 60.0)),
            "invalid_spec",
        )

    async def test_year_range_unordered_rejected(self):
        self.assertEqual(await self._fails_with(year_range=(2023, 2010)), "invalid_spec")

    async def test_year_range_out_of_bounds_rejected(self):
        self.assertEqual(await self._fails_with(year_range=(1500, 1600)), "invalid_spec")

    async def test_limit_too_big_rejected(self):
        self.assertEqual(await self._fails_with(limit=200_000), "invalid_spec")

    async def test_limit_zero_rejected(self):
        self.assertEqual(await self._fails_with(limit=0), "invalid_spec")


# ── Connector error envelopes ─────────────────────────────────────────────


class ConnectorErrorEnvelopes(unittest.IsolatedAsyncioTestCase):
    async def _connector_returns(self, body: dict, status: int = 200) -> GbifClusterError:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=body)

        async with _client_with_handler(handler) as client:
            with self.assertRaises(GbifClusterError) as ctx:
                await query_gbif_cluster(
                    agenticplug_url="http://broker",
                    session_id="s",
                    http_client=client,
                )
        return ctx.exception

    async def test_row_cap_exceeded(self):
        exc = await self._connector_returns(
            {"error": True, "code": "row_cap_exceeded", "row_count": 200_001}
        )
        self.assertEqual(exc.code, "row_cap_exceeded")
        self.assertEqual(exc.payload["row_count"], 200_001)

    async def test_invalid_spec_from_connector(self):
        exc = await self._connector_returns(
            {"error": True, "code": "invalid_spec", "message": "bad bbox"}
        )
        self.assertEqual(exc.code, "invalid_spec")

    async def test_cluster_unreachable_on_5xx(self):
        exc = await self._connector_returns({"error": "broker is sad"}, status=503)
        self.assertEqual(exc.code, "cluster_unreachable")

    async def test_unauthorized_on_401(self):
        exc = await self._connector_returns({"error": "nope"}, status=401)
        self.assertEqual(exc.code, "unauthorized")

    async def test_unsupported_encoding_rejected(self):
        envelope = _ok_envelope()
        envelope["encoding"] = "json"
        exc = await self._connector_returns(envelope)
        self.assertEqual(exc.code, "bad_response")

    async def test_missing_data_field_rejected(self):
        envelope = _ok_envelope()
        envelope["data"] = ""
        exc = await self._connector_returns(envelope)
        self.assertEqual(exc.code, "bad_response")


# ── Defaults & edges ──────────────────────────────────────────────────────


class Defaults(unittest.IsolatedAsyncioTestCase):
    async def test_empty_species_name_omits_filter_in_payload(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json
            seen.update(json.loads(request.read())["args"])
            return httpx.Response(200, json=_ok_envelope(rows=1))

        async with _client_with_handler(handler) as client:
            await query_gbif_cluster(
                agenticplug_url="http://broker",
                session_id="s",
                http_client=client,
            )

        self.assertNotIn("species_name", seen)
        self.assertNotIn("taxon_key", seen)
        self.assertEqual(seen["limit"], 50_000)


if __name__ == "__main__":
    unittest.main()
