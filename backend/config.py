"""
EcoSeek backend gateway — environment-driven configuration.

All settings are read from environment variables (no config.ini).

Environment variables
---------------------
EMILY_API_URL           URL of Emily (Hermes Agent API server).
                        Default: http://localhost:8642
                        Emily is the primary backend — Hermes Agent running
                        with the ecoseek plugin + Emily scientific personality.
                        Exposes an OpenAI-compatible endpoint at /v1/chat/completions.

EMILY_API_KEY           Bearer token for Emily API authentication.
                        Must match API_SERVER_KEY in the Emily container.

EMILY_ENABLED           Set to "true" to enable routing to Emily.
                        Default: true (Emily is the primary backend).

AGENTICPLUG_URL         URL of the AgenticPlug gateway (optional fallback).
                        Default: http://agenticplug:8080

# ── Legacy / deprecated (kept for backward compat) ─────────────────────
HERMES_ENABLED          Deprecated. Use EMILY_ENABLED.
HERMES_URL              Deprecated. Use EMILY_API_URL.
HERMES_API_KEY          Deprecated. Use EMILY_API_KEY.

UPSTREAM_TIMEOUT_S      Seconds before upstream requests time out.
                        Default: 60 (longer for Emily's tool-calling loops).

MEILI_URL               URL of Meilisearch instance for literature search.
                        Default: http://localhost:7700
                        Provides instant full-text search across 62K GBIF papers.

MEILI_ENABLED           Set to \"true\" to enable /v1/search endpoint.
                        Default: true

MEILI_INDEX             Meilisearch index name for GBIF literature.
                        Default: gbif_literature

LOCAL_LLM_URL           OpenAI-compatible endpoint for local-model fallback
                        (e.g. Ollama or OpenWebUI). Optional.

LOCAL_LLM_API_KEY       Bearer token for LOCAL_LLM_URL. Optional.

BACKEND_PORT            Port the uvicorn server listens on inside the
                        container. Derived from ECOSEEK_API_PORT in
                        docker-compose; default 3000.

PHOENIX_ENABLED         Set to "true" to send traces to Arize Phoenix.
                        Default: false.

PHOENIX_ENDPOINT        OTLP collector endpoint.
                        Default: http://phoenix:6006/v1/traces

PHOENIX_PROJECT_NAME    Project name in Phoenix UI. Default: ecoseek
"""

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env if present (dev only; prod uses docker env)


# ── Emily (Hermes Agent API server) — PRIMARY backend ────────────────────
def _resolve_emily_url() -> str:
    """Resolve Emily URL: EMILY_API_URL > HERMES_URL (legacy) > localhost:8642."""
    url = os.getenv("EMILY_API_URL", "") or os.getenv("HERMES_URL", "")
    return url.rstrip("/") if url else "http://localhost:8642"


def _resolve_emily_key() -> str:
    """Resolve Emily API key: EMILY_API_KEY > HERMES_API_KEY (legacy) > empty."""
    return os.getenv("EMILY_API_KEY", "") or os.getenv("HERMES_API_KEY", "")


def _resolve_emily_enabled() -> bool:
    """Emily enabled by default. HERMES_ENABLED is legacy fallback."""
    env = os.getenv("EMILY_ENABLED", os.getenv("HERMES_ENABLED", "true"))
    return env.lower() in ("1", "true", "yes")


EMILY_API_URL: str = _resolve_emily_url()
EMILY_API_KEY: str = _resolve_emily_key()
EMILY_ENABLED: bool = _resolve_emily_enabled()

# Legacy aliases for backward compat
HERMES_ENABLED = EMILY_ENABLED
HERMES_URL = EMILY_API_URL
HERMES_API_KEY = EMILY_API_KEY

# ── AgenticPlug (optional fallback) ──────────────────────────────────────
AGENTICPLUG_URL: str = os.getenv("AGENTICPLUG_URL", "http://agenticplug:8080").rstrip(
    "/"
)

# ── Timeouts ──────────────────────────────────────────────────────────────
UPSTREAM_TIMEOUT_S: int = int(os.getenv("UPSTREAM_TIMEOUT_S", "60"))

# ── Local LLM fallback (e.g. Ollama) ─────────────────────────────────────
LOCAL_LLM_URL: str = os.getenv("LOCAL_LLM_URL", "").rstrip("/")
LOCAL_LLM_API_KEY: str = os.getenv("LOCAL_LLM_API_KEY", "")

# ── Meilisearch (literature search) ────────────────────────────────────────
MEILI_URL: str = os.getenv("MEILI_URL", "http://localhost:7700").rstrip("/")
MEILI_ENABLED: bool = os.getenv("MEILI_ENABLED", "true").lower() not in ("false", "0", "no")
MEILI_INDEX: str = os.getenv("MEILI_INDEX", "gbif_literature")

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
