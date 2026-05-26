import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api


class QueryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_missing_text_and_messages_returns_422(self):
        response = self.client.post("/v1/query", json={"mode": "auto"})
        self.assertEqual(response.status_code, 422)

    def test_stream_true_in_body_returns_501(self):
        response = self.client.post("/v1/query", json={"text": "hello", "stream": True})
        self.assertEqual(response.status_code, 501)

    def test_stream_true_in_query_param_returns_501(self):
        response = self.client.post("/v1/query?stream=true", json={"text": "hello"})
        self.assertEqual(response.status_code, 501)

    def test_messages_win_when_text_also_present(self):
        with patch.object(
            api, "_try_agenticplug_chat", new=AsyncMock(return_value="agentic response")
        ) as mocked:
            response = self.client.post(
                "/v1/query",
                json={
                    "mode": "agenticplug",
                    "text": "ignored text",
                    "messages": [{"role": "user", "content": "use this"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode_used"], "agenticplug")
        mocked.assert_awaited_once_with(
            "use this", [{"role": "user", "content": "use this"}]
        )

    def test_auto_falls_back_to_local(self):
        with (
            patch.object(api, "HERMES_URL", "http://hermes.example"),
            patch.object(api, "_try_hermes", new=AsyncMock(return_value=None)),
            patch.object(
                api, "_try_agenticplug_chat", new=AsyncMock(return_value=None)
            ),
            patch.object(
                api, "_try_local_llm", new=AsyncMock(return_value="local response")
            ),
        ):
            response = self.client.post(
                "/v1/query", json={"mode": "auto", "text": "hello"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "answer": "local response",
                "mode_used": "local",
                "fallback_chain": ["hermes", "agenticplug", "local"],
            },
        )

    def test_explicit_local_mode_skips_other_upstreams(self):
        with (
            patch.object(api, "_try_hermes", new=AsyncMock(return_value="wrong")),
            patch.object(
                api, "_try_agenticplug_chat", new=AsyncMock(return_value="wrong")
            ),
            patch.object(
                api, "_try_local_llm", new=AsyncMock(return_value="local response")
            ) as mocked_local,
        ):
            response = self.client.post(
                "/v1/query", json={"mode": "local", "text": "hello"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode_used"], "local")
        mocked_local.assert_awaited_once()


class LocalEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_llm_uses_openai_path(self):
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}}]}

        class FakeClient:
            async def post(self, url, json):
                captured["url"] = url
                captured["payload"] = json
                return FakeResponse()

        with (
            patch.object(api, "_client", return_value=FakeClient()),
            patch.object(api, "LOCAL_LLM_URL", "http://local-llm:11434"),
        ):
            answer = await api._try_local_llm(
                "hello", [{"role": "user", "content": "hello"}]
            )

        self.assertEqual(answer, "ok")
        self.assertEqual(captured["url"], "http://local-llm:11434/v1/chat/completions")
        self.assertEqual(captured["payload"]["stream"], False)
