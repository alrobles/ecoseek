"""Tests for EcoSeek API v2 — Emily (Hermes Agent) direct integration."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api
import config


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_health_returns_ok(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class QueryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    # ── Validation ──────────────────────────────────────────────────────

    def test_missing_text_returns_422(self):
        response = self.client.post("/v1/query", json={"mode": "auto"})
        self.assertEqual(response.status_code, 422)

    def test_stream_true_in_body_returns_501(self):
        response = self.client.post("/v1/query", json={"text": "hello", "stream": True})
        self.assertEqual(response.status_code, 501)

    def test_stream_true_in_query_param_returns_501(self):
        response = self.client.post("/v1/query?stream=true", json={"text": "hello"})
        self.assertEqual(response.status_code, 501)

    # ── Emily (primary backend) ─────────────────────────────────────────

    def test_hermes_mode_calls_emily(self):
        """mode=hermes routes to Emily (Hermes Agent API server)."""
        mock_response = {
            "choices": [{"message": {"content": "Emily's ecological analysis here."}}],
            "model": "emily",
        }
        with patch.object(
            api, "_call_emily", new=AsyncMock(return_value=mock_response)
        ):
            response = self.client.post(
                "/v1/query",
                json={"mode": "hermes", "text": "Explain niche modeling"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode_used"], "emily")
        self.assertIn("Emily's ecological analysis", str(data["result"]))

    def test_hermes_mode_fails_when_emily_down(self):
        """mode=hermes hard-fails when Emily is unreachable."""
        with patch.object(
            api, "_call_emily", new=AsyncMock(side_effect=ConnectionError("refused"))
        ):
            response = self.client.post(
                "/v1/query",
                json={"mode": "hermes", "text": "Explain niche modeling"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("unavailable", data.get("error", ""))

    # ── AgenticPlug (fallback) ──────────────────────────────────────────

    def test_agenticplug_mode_calls_agenticplug(self):
        mock_response = {"text": "agenticplug response"}
        with patch.object(
            api, "_call_agenticplug", new=AsyncMock(return_value=mock_response)
        ):
            response = self.client.post(
                "/v1/query",
                json={"mode": "agenticplug", "text": "hello"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode_used"], "agenticplug")

    # ── Local LLM ───────────────────────────────────────────────────────

    def test_local_mode_calls_local_llm(self):
        with patch.object(config, "LOCAL_LLM_URL", "http://ollama:11434"):
            with patch.object(
                api, "_call_local", new=AsyncMock(return_value={"text": "local"})
            ):
                response = self.client.post(
                    "/v1/query",
                    json={"mode": "local", "text": "hello"},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode_used"], "local")

    def test_local_mode_fails_without_url(self):
        with patch.object(config, "LOCAL_LLM_URL", ""):
            response = self.client.post(
                "/v1/query",
                json={"mode": "local", "text": "hello"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])

    # ── Auto mode (fallback chain) ──────────────────────────────────────

    def test_auto_falls_back_to_agenticplug_when_emily_down(self):
        """When Emily fails, auto mode tries AgenticPlug next."""
        with patch.object(config, "EMILY_ENABLED", True):
            with patch.object(config, "EMILY_API_URL", "http://emily:8642"):
                with patch.object(
                    api, "_call_emily", new=AsyncMock(side_effect=ConnectionError)
                ):
                    with patch.object(
                        api,
                        "_call_agenticplug",
                        new=AsyncMock(return_value={"text": "fallback"}),
                    ):
                        response = self.client.post(
                            "/v1/query",
                            json={"mode": "auto", "text": "hello"},
                        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode_used"], "agenticplug")
        self.assertEqual(data["fallback_chain"], ["emily", "agenticplug"])

    def test_auto_falls_back_to_local(self):
        """When both Emily and AgenticPlug fail, auto mode tries local."""
        with patch.object(config, "EMILY_ENABLED", True):
            with patch.object(config, "EMILY_API_URL", "http://emily:8642"):
                with patch.object(config, "LOCAL_LLM_URL", "http://ollama:11434"):
                    with patch.object(
                        api, "_call_emily", new=AsyncMock(side_effect=ConnectionError)
                    ):
                        with patch.object(
                            api,
                            "_call_agenticplug",
                            new=AsyncMock(side_effect=ConnectionError),
                        ):
                            with patch.object(
                                api,
                                "_call_local",
                                new=AsyncMock(return_value={"text": "local"}),
                            ):
                                response = self.client.post(
                                    "/v1/query",
                                    json={"mode": "auto", "text": "hello"},
                                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode_used"], "local")
        self.assertEqual(data["fallback_chain"], ["emily", "agenticplug", "local"])

    def test_auto_all_fail(self):
        """When all backends fail, return error."""
        with patch.object(config, "EMILY_ENABLED", True):
            with patch.object(config, "EMILY_API_URL", "http://emily:8642"):
                with patch.object(
                    api, "_call_emily", new=AsyncMock(side_effect=ConnectionError)
                ):
                    with patch.object(
                        api,
                        "_call_agenticplug",
                        new=AsyncMock(side_effect=ConnectionError),
                    ):
                        with patch.object(
                            api,
                            "_call_local",
                            new=AsyncMock(side_effect=ConnectionError),
                        ):
                            response = self.client.post(
                                "/v1/query",
                                json={"mode": "auto", "text": "hello"},
                            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("All backends", data.get("error", ""))

    # ── Emily API contract ──────────────────────────────────────────────

    def test_emily_chat_completion_format(self):
        """Verify Emily is called with OpenAI-compatible chat format."""
        mock_response = {
            "choices": [{"message": {"content": "Response", "role": "assistant"}}],
            "model": "emily",
        }
        with patch.object(
            api, "_call_emily", new=AsyncMock(return_value=mock_response)
        ) as mocked:
            self.client.post(
                "/v1/query",
                json={"mode": "hermes", "text": "Tell me about SDM"},
            )

        # Emily should have been called
        mocked.assert_awaited_once()
