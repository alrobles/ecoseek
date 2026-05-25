"""GBIF cluster query tool — bidirectional bridge through the reumanlab connector.

The agent calls ``query_gbif_cluster(...)``; the function POSTs the
``gbif.query`` capability to AgenticPlug, which routes it to the reumanlab
connector, which executes ``gbif_query.R`` on KU-HPC and ships the cleaned
Parquet result back base64-encoded. We decode it into a ``pandas.DataFrame``.

The laptop client never holds cluster credentials — all auth lives in
AgenticPlug (ADR-001, ADR-005). Risk class: ``read``. No approval required.

Contract: see https://github.com/alrobles/ecoseek/issues/71
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("ecoseek.tools.gbif_cluster")

# ── Constants from the capability contract (issue #71) ────────────────────
CAPABILITY_NAME: str = "gbif.query"
MAX_LIMIT: int = 100_000
SPECIES_NAME_MAX_LEN: int = 200
YEAR_MIN: int = 1700
YEAR_MAX: int = 2100
TAXON_KEY_MAX: int = 2_000_000_000

EXPECTED_COLUMNS: Tuple[str, ...] = (
    "decimalLatitude",
    "decimalLongitude",
    "species",
    "taxonKey",
    "year",
    "month",
    "basisOfRecord",
)


class GbifClusterError(RuntimeError):
    """Raised when the cluster bridge returns an error response.

    Carries the ``code`` field from the connector contract so callers can
    branch on specific failure modes (``invalid_spec``, ``row_cap_exceeded``,
    ``cluster_unreachable``, ``query_timeout``, ``result_too_large``).
    """

    def __init__(self, code: str, message: str, *, payload: Optional[Dict[str, Any]] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.payload = payload or {}


# ── Client-side validation (defense in depth — connector also validates) ──

def _validate_args(
    species_name: str,
    taxon_key: Optional[int],
    bbox: Optional[Tuple[float, float, float, float]],
    year_range: Optional[Tuple[int, int]],
    limit: int,
) -> Dict[str, Any]:
    """Validate inputs and return a JSON-safe dict for the capability payload.

    Raises ``GbifClusterError("invalid_spec", ...)`` on any violation so the
    bad call is rejected locally without burning a cluster round-trip.
    """
    if not isinstance(species_name, str) or len(species_name) > SPECIES_NAME_MAX_LEN:
        raise GbifClusterError(
            "invalid_spec",
            f"species_name must be a string of length <= {SPECIES_NAME_MAX_LEN}",
        )
    # shell-meta guard mirrors connector/reumanlab/sanitize.js
    if any(ch in species_name for ch in ";|&$`><\n\x00"):
        raise GbifClusterError("invalid_spec", "species_name contains forbidden characters")

    if taxon_key is not None:
        if not isinstance(taxon_key, int) or taxon_key < 1 or taxon_key > TAXON_KEY_MAX:
            raise GbifClusterError(
                "invalid_spec",
                f"taxon_key must be an integer in [1, {TAXON_KEY_MAX}]",
            )

    if bbox is not None:
        if len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
            raise GbifClusterError("invalid_spec", "bbox must be 4 numbers")
        min_lon, min_lat, max_lon, max_lat = bbox
        if not (-180 <= min_lon <= max_lon <= 180):
            raise GbifClusterError("invalid_spec", "bbox longitudes out of range or unordered")
        if not (-90 <= min_lat <= max_lat <= 90):
            raise GbifClusterError("invalid_spec", "bbox latitudes out of range or unordered")

    if year_range is not None:
        if len(year_range) != 2 or not all(isinstance(v, int) for v in year_range):
            raise GbifClusterError("invalid_spec", "year_range must be 2 integers")
        start, end = year_range
        if not (YEAR_MIN <= start <= end <= YEAR_MAX):
            raise GbifClusterError(
                "invalid_spec",
                f"year_range must be ordered and within [{YEAR_MIN}, {YEAR_MAX}]",
            )

    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise GbifClusterError(
            "invalid_spec",
            f"limit must be an integer in [1, {MAX_LIMIT}]",
        )

    args: Dict[str, Any] = {"limit": limit}
    if species_name:
        args["species_name"] = species_name
    if taxon_key is not None:
        args["taxon_key"] = taxon_key
    if bbox is not None:
        args["bbox"] = list(bbox)
    if year_range is not None:
        args["year_range"] = list(year_range)
    return args


# ── Parquet decode ────────────────────────────────────────────────────────

def _decode_parquet(b64_data: str) -> "Any":  # returns pd.DataFrame
    """Decode base64+Parquet bytes into a pandas DataFrame.

    Imported lazily so the backend can boot without pyarrow/pandas installed
    until the tool is actually called.
    """
    try:
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover — environment failure
        raise GbifClusterError(
            "missing_dep",
            "pyarrow is required to decode gbif.query responses; "
            "install ecoseek backend with the 'pyarrow' extra",
        ) from exc

    raw = base64.b64decode(b64_data, validate=True)
    table = pq.read_table(io.BytesIO(raw))
    return table.to_pandas()


# ── Public API ────────────────────────────────────────────────────────────

async def query_gbif_cluster(
    *,
    agenticplug_url: str,
    session_id: str,
    species_name: str = "",
    taxon_key: Optional[int] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    year_range: Optional[Tuple[int, int]] = None,
    limit: int = 50_000,
    timeout_s: float = 180.0,
    http_client: Optional[httpx.AsyncClient] = None,
) -> "Any":  # returns pd.DataFrame
    """Query the GBIF Parquet mirror on KU-HPC via AgenticPlug.

    Parameters
    ----------
    agenticplug_url
        Base URL of the AgenticPlug gateway (no trailing slash).
    session_id
        Opaque session ID minted by AgenticPlug (GitHub Device Flow upstream).
    species_name
        Optional scientific name (case-insensitive substring match server-side).
    taxon_key
        Optional GBIF ``taxonKey``.
    bbox
        Optional ``(min_lon, min_lat, max_lon, max_lat)`` bounding box.
    year_range
        Optional inclusive ``(start_year, end_year)``.
    limit
        Maximum rows returned (capped at ``MAX_LIMIT`` = 100k per call).
    timeout_s
        HTTP timeout for the whole round-trip (default 180s — cluster R + scp).
    http_client
        Optional ``httpx.AsyncClient`` to reuse a connection pool. Useful for
        tests (inject a transport mock) and for tools that batch many calls.

    Returns
    -------
    pandas.DataFrame
        Cleaned occurrence records with columns:
        ``decimalLatitude, decimalLongitude, species, taxonKey, year, month, basisOfRecord``.

    Raises
    ------
    GbifClusterError
        If input validation fails, the connector returns an error code, or
        the response cannot be decoded.
    """
    args = _validate_args(species_name, taxon_key, bbox, year_range, limit)
    payload = {"capability": CAPABILITY_NAME, "args": args}
    url = f"{agenticplug_url.rstrip('/')}/v1/capabilities"
    headers = {
        "Authorization": f"Bearer {session_id}",
        "Content-Type": "application/json",
    }

    logger.info(
        "gbif.query → species=%r taxon_key=%s bbox=%s year_range=%s limit=%d",
        species_name, taxon_key, bbox, year_range, limit,
    )

    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.post(url, json=payload, headers=headers)
    finally:
        if own_client:
            await client.aclose()

    if response.status_code in (401, 403):
        raise GbifClusterError("unauthorized", f"AgenticPlug rejected the session ({response.status_code})")
    if response.status_code >= 500:
        raise GbifClusterError(
            "cluster_unreachable",
            f"AgenticPlug returned {response.status_code}",
        )
    if response.status_code != 200:
        raise GbifClusterError(
            "bad_response",
            f"AgenticPlug returned {response.status_code}",
        )

    body = response.json()

    # Connector error envelope: {"error": true, "code": "...", "message": "..."}
    if isinstance(body, dict) and body.get("error"):
        raise GbifClusterError(
            str(body.get("code", "unknown_error")),
            str(body.get("message", "")),
            payload=body,
        )

    if body.get("status") != "ok":
        raise GbifClusterError(
            "bad_response",
            f"unexpected status={body.get('status')!r}",
            payload=body,
        )

    if body.get("encoding") != "parquet+base64":
        raise GbifClusterError(
            "bad_response",
            f"unsupported encoding={body.get('encoding')!r}",
            payload=body,
        )

    data_b64 = body.get("data")
    if not isinstance(data_b64, str) or not data_b64:
        raise GbifClusterError("bad_response", "missing data field")

    df = _decode_parquet(data_b64)

    schema: List[str] = list(body.get("schema") or [])
    if schema and tuple(schema) != EXPECTED_COLUMNS:
        logger.warning(
            "gbif.query schema mismatch: got %s expected %s",
            schema, EXPECTED_COLUMNS,
        )

    logger.info(
        "gbif.query ← rows=%d job_id=%s bytes=%d",
        body.get("row_count", len(df)),
        body.get("job_id", "?"),
        len(data_b64),
    )
    return df
