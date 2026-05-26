"""
EcoSeek backend gateway — environment-driven configuration.

All settings are read from environment variables (no config.ini).

Environment variables
---------------------
AGENTICPLUG_URL         URL of the AgenticPlug gateway (docker-internal).
                        Default: http://agenticplug:8080

HERMES_ENABLED          Set to "true" to enable routing to Hermes.
                        Default: false

HERMES_URL              External URL of the Hermes orchestration service.
                        Required when HERMES_ENABLED=true.

HERMES_API_KEY          Bearer token for Hermes API authentication.
                        Optional; sent as Authorization header when present.

UPSTREAM_TIMEOUT_S      Seconds before upstream requests time out.
                        Default: 30

LOCAL_LLM_URL           OpenAI-compatible endpoint for local-model fallback
                        (e.g. Ollama or OpenWebUI). Optional.

LOCAL_LLM_API_KEY       Bearer token for LOCAL_LLM_URL. Optional.

BACKEND_PORT            Port the uvicorn server listens on inside the
                        container. Derived from ECOSEEK_API_PORT in
                        docker-compose; default 3000.

PHOENIX_ENABLED         Set to "true" to send traces to Arize Phoenix.
                        Default: false.

PHOENIX_ENDPOINT        OTLP collector endpoint. Default: http://phoenix:6006/v1/traces

PHOENIX_PROJECT_NAME    Project name in Phoenix UI. Default: ecoseek
"""

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env if present (dev only; prod uses docker env)

# ── AgenticPlug (internal docker network) ─────────────────────────────────
AGENTICPLUG_URL: str = os.getenv("AGENTICPLUG_URL", "http://agenticplug:8080").rstrip(
    "/"
)

# Hermes orchestration service (optional; disabled by default).
HERMES_ENABLED: bool = os.getenv("HERMES_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
HERMES_URL: str = os.getenv("HERMES_URL", "").rstrip("/")
HERMES_API_KEY: str = os.getenv("HERMES_API_KEY", "")

# ── Timeouts ──────────────────────────────────────────────────────────────
UPSTREAM_TIMEOUT_S: int = int(os.getenv("UPSTREAM_TIMEOUT_S", "30"))

# ── Local LLM fallback (e.g. Ollama, OpenWebUI) ───────────────────────────
LOCAL_LLM_URL: str = os.getenv("LOCAL_LLM_URL", "").rstrip("/")
LOCAL_LLM_API_KEY: str = os.getenv("LOCAL_LLM_API_KEY", "")

# ── Server ────────────────────────────────────────────────────────────────
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "3000"))

# ── Phoenix observability (tracing disabled by default) ───────────────────
PHOENIX_ENABLED: bool = os.getenv("PHOENIX_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
PHOENIX_ENDPOINT: str = os.getenv("PHOENIX_ENDPOINT", "http://phoenix:6006/v1/traces")
PHOENIX_PROJECT_NAME: str = os.getenv("PHOENIX_PROJECT_NAME", "ecoseek")
