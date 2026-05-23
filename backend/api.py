"""
EcoSeek API gateway.

Endpoints
---------
GET  /          Health check — always returns {"status": "ok"}.
POST /v1/query  Primary query endpoint. Routes to Hermes / AgenticPlug /
                local model with a configurable fallback chain.

/v1/query — request (v1)
    text        string   required  The user query.
    mode        enum     optional  Routing preference:
                                   auto | hermes | agenticplug | local
                                   Default: auto
    session_id  string   optional  Opaque session identifier forwarded to
                                   upstream services.
    metadata    object   optional  Arbitrary key-value pairs forwarded as
                                   request context.

/v1/query — response
    success         bool           True when at least one upstream responded.
    mode_used       string         Which backend ultimately answered.
    result          object         Upstream response body.
    error           string|null    Error message when success=false.
    fallback_chain  list[string]   Backends tried in order.

Streaming is NOT supported in alpha.  If the caller sends ?stream=true the
endpoint returns 501 Not Implemented.

OpenTelemetry
-------------
When PHOENIX_ENABLED=true, every /v1/query request emits a trace tree:
  POST /v1/query   →  Auto-instrumented by FastAPIInstrumentor
    ecoseek.route   →  Routing decision + fallback chain
      ecoseek.call.{backend} → Upstream HTTP call (hermes / agenticplug / local)

Spans carry attributes: ecoseek.mode, ecoseek.upstream, ecoseek.success,
ecoseek.fallback_chain, ecoseek.session_id, http.url, http.status_code, error.

curl examples
-------------
# Health
curl http://localhost:3000/

# Simple auto-routed query
curl -s -X POST http://localhost:3000/v1/query \\
  -H 'Content-Type: application/json' \\
  -d '{"text": "List top 5 mammal species in Yucatan."}'

# Force Hermes mode
curl -s -X POST http://localhost:3000/v1/query \\
  -H 'Content-Type: application/json' \\
  -d '{"text": "Analyse host-parasite network.", "mode": "hermes"}'

# Force local fallback
curl -s -X POST http://localhost:3000/v1/query \\
  -H 'Content-Type: application/json' \\
  -d '{"text": "Hello?", "mode": "local"}'
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
from phoenix_tracer import get_tracer, instrument_fastapi

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("ecoseek.api")

app = FastAPI(title="EcoSeek API", version="1.0.0-alpha")

# ── OpenTelemetry auto-instrumentation (no-op when PHOENIX_ENABLED=false) ──
instrument_fastapi(app)

_tracer = get_tracer()


# ── Models ─────────────────────────────────────────────────────────────────

class Mode(str, Enum):
    auto = "auto"
    hermes = "hermes"
    agenticplug = "agenticplug"
    local = "local"


class QueryRequest(BaseModel):
    text: str = Field(..., description="The user query text.")
    mode: Mode = Field(Mode.auto, description="Routing preference.")
    session_id: Optional[str] = Field(None, description="Opaque session identifier.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary context.")


class QueryResponse(BaseModel):
    success: bool
    mode_used: Optional[str]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    fallback_chain: List[str]


# ── Upstream helpers ────────────────────────────────────────────────────────

def _hermes_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if config.HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {config.HERMES_API_KEY}"
    return headers


def _local_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if config.LOCAL_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LOCAL_LLM_API_KEY}"
    return headers


async def _call_hermes(req: QueryRequest) -> Dict[str, Any]:
    """POST to Hermes orchestrate endpoint via AgenticPlug."""
    url = f"{config.AGENTICPLUG_URL}/v1/orchestrate"
    payload: Dict[str, Any] = {"text": req.text}
    if req.session_id:
        payload["session_id"] = req.session_id
    if req.metadata:
        payload["metadata"] = req.metadata

    with _tracer.start_as_current_span("ecoseek.call.hermes") as span:
        span.set_attribute("ecoseek.upstream", "hermes")
        span.set_attribute("http.url", url)
        span.set_attribute("http.method", "POST")
        if req.session_id:
            span.set_attribute("ecoseek.session_id", req.session_id)
        try:
            async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
                r = await client.post(url, json=payload, headers=_hermes_headers())
                span.set_attribute("http.status_code", r.status_code)
                r.raise_for_status()
                span.set_attribute("ecoseek.success", True)
                return r.json()
        except Exception as exc:  # noqa: BLE001
            span.set_attribute("ecoseek.success", False)
            span.set_attribute("error", True)
            span.record_exception(exc)
            raise


async def _call_agenticplug(req: QueryRequest) -> Dict[str, Any]:
    """POST to AgenticPlug chat completions (OpenAI-compatible)."""
    url = f"{config.AGENTICPLUG_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": req.text}],
        "stream": False,
    }
    if req.session_id:
        payload["session_id"] = req.session_id

    with _tracer.start_as_current_span("ecoseek.call.agenticplug") as span:
        span.set_attribute("ecoseek.upstream", "agenticplug")
        span.set_attribute("http.url", url)
        span.set_attribute("http.method", "POST")
        if req.session_id:
            span.set_attribute("ecoseek.session_id", req.session_id)
        try:
            async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
                r = await client.post(url, json=payload)
                span.set_attribute("http.status_code", r.status_code)
                r.raise_for_status()
                span.set_attribute("ecoseek.success", True)
                return r.json()
        except Exception as exc:  # noqa: BLE001
            span.set_attribute("ecoseek.success", False)
            span.set_attribute("error", True)
            span.record_exception(exc)
            raise


async def _call_local(req: QueryRequest) -> Dict[str, Any]:
    """POST to the local OpenAI-compatible LLM endpoint (e.g. Ollama)."""
    if not config.LOCAL_LLM_URL:
        raise RuntimeError("LOCAL_LLM_URL is not configured")
    url = f"{config.LOCAL_LLM_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": req.text}],
        "stream": False,
    }

    with _tracer.start_as_current_span("ecoseek.call.local") as span:
        span.set_attribute("ecoseek.upstream", "local")
        span.set_attribute("http.url", url)
        span.set_attribute("http.method", "POST")
        if req.session_id:
            span.set_attribute("ecoseek.session_id", req.session_id)
        try:
            async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
                r = await client.post(url, json=payload, headers=_local_headers())
                span.set_attribute("http.status_code", r.status_code)
                r.raise_for_status()
                span.set_attribute("ecoseek.success", True)
                return r.json()
        except Exception as exc:  # noqa: BLE001
            span.set_attribute("ecoseek.success", False)
            span.set_attribute("error", True)
            span.record_exception(exc)
            raise


# ── Routing logic ───────────────────────────────────────────────────────────

async def _route(req: QueryRequest) -> QueryResponse:
    """
    Routing / fallback chain:

    mode=hermes     → Hermes (via AgenticPlug /v1/orchestrate); hard-fail if down.
    mode=agenticplug → AgenticPlug only; fail if down.
    mode=local       → Local LLM only; fail if not configured or down.
    mode=auto        → Hermes (if enabled) → AgenticPlug → local; each step
                       is tried only when the previous one fails.
    """
    with _tracer.start_as_current_span("ecoseek.route") as span:
        span.set_attribute("ecoseek.mode", req.mode.value)
        if req.session_id:
            span.set_attribute("ecoseek.session_id", req.session_id)

        chain: List[str] = []

        async def _try(name: str, coro) -> Optional[Dict[str, Any]]:
            chain.append(name)
            try:
                result = await coro
                log.info("upstream %s succeeded", name)
                return result
            except Exception as exc:  # noqa: BLE001
                log.warning("upstream %s failed: %s", name, exc)
                return None

        if req.mode == Mode.hermes:
            result = await _try("hermes", _call_hermes(req))
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            if result is None:
                span.set_attribute("ecoseek.success", False)
                span.set_attribute("ecoseek.mode_used", "")
                return QueryResponse(
                    success=False,
                    mode_used=None,
                    result=None,
                    error="Hermes backend unavailable and no fallback allowed for mode=hermes.",
                    fallback_chain=chain,
                )
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "hermes")
            return QueryResponse(success=True, mode_used="hermes", result=result, error=None, fallback_chain=chain)

        if req.mode == Mode.agenticplug:
            result = await _try("agenticplug", _call_agenticplug(req))
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            if result is None:
                span.set_attribute("ecoseek.success", False)
                span.set_attribute("ecoseek.mode_used", "")
                return QueryResponse(
                    success=False,
                    mode_used=None,
                    result=None,
                    error="AgenticPlug backend unavailable.",
                    fallback_chain=chain,
                )
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "agenticplug")
            return QueryResponse(success=True, mode_used="agenticplug", result=result, error=None, fallback_chain=chain)

        if req.mode == Mode.local:
            result = await _try("local", _call_local(req))
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            if result is None:
                span.set_attribute("ecoseek.success", False)
                span.set_attribute("ecoseek.mode_used", "")
                return QueryResponse(
                    success=False,
                    mode_used=None,
                    result=None,
                    error="Local LLM unavailable or LOCAL_LLM_URL not configured.",
                    fallback_chain=chain,
                )
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "local")
            return QueryResponse(success=True, mode_used="local", result=result, error=None, fallback_chain=chain)

        # mode=auto: try Hermes first (if enabled), then AgenticPlug, then local.
        if config.HERMES_ENABLED and config.HERMES_URL:
            result = await _try("hermes", _call_hermes(req))
            if result is not None:
                span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
                span.set_attribute("ecoseek.success", True)
                span.set_attribute("ecoseek.mode_used", "hermes")
                return QueryResponse(success=True, mode_used="hermes", result=result, error=None, fallback_chain=chain)

        result = await _try("agenticplug", _call_agenticplug(req))
        if result is not None:
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "agenticplug")
            return QueryResponse(success=True, mode_used="agenticplug", result=result, error=None, fallback_chain=chain)

        if config.LOCAL_LLM_URL:
            result = await _try("local", _call_local(req))
            if result is not None:
                span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
                span.set_attribute("ecoseek.success", True)
                span.set_attribute("ecoseek.mode_used", "local")
                return QueryResponse(success=True, mode_used="local", result=result, error=None, fallback_chain=chain)

        span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
        span.set_attribute("ecoseek.success", False)
        span.set_attribute("ecoseek.mode_used", "")
        return QueryResponse(
            success=False,
            mode_used=None,
            result=None,
            error="All backends in the fallback chain failed.",
            fallback_chain=chain,
        )


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", summary="Health check")
async def health() -> Dict[str, str]:
    """Returns immediately with status=ok. Used by docker healthcheck."""
    return {"status": "ok"}


@app.post("/v1/query", response_model=QueryResponse, summary="Primary query endpoint")
async def query(
    req: QueryRequest,
    stream: Optional[bool] = Query(default=None, description="Streaming — not supported in alpha."),
) -> QueryResponse:
    """
    Route a natural-language query to the appropriate backend.

    Streaming is **not** supported in alpha.  Pass ``?stream=true`` to get a
    501 response rather than unexpected behaviour.
    """
    if stream:
        return JSONResponse(
            status_code=501,
            content={"detail": "Streaming is not supported in alpha. Omit ?stream=true."},
        )

    return await _route(req)
