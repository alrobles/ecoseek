"""EcoSeek API Gateway — lightweight proxy with failover chain.

Failover order: Hermes → AgenticPlug chat → local LLM.
Every upstream call is subject to UPSTREAM_TIMEOUT_S.

Security invariants:
  - HERMES_API_KEY, Authorization headers, and full prompts are NEVER logged.
  - Error responses to clients contain only a generic message + mode_used +
    fallback_chain. No stack traces, no upstream details.
  - Fail-closed: if all upstreams fail, return 503 with the chain tried.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────

UPSTREAM_TIMEOUT_S = int(os.getenv("UPSTREAM_TIMEOUT_S", "30"))

HERMES_URL = os.getenv("HERMES_URL", "").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")

AGENTICPLUG_URL = os.getenv("AGENTICPLUG_URL", "http://agenticplug:8080").rstrip("/")

LOCAL_LLM_URL = (
    os.getenv("LOCAL_LLM_URL")
    or os.getenv("OLLAMA_URL")
    or "http://ollama:11434"
).rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "tinyllama")

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

logger = logging.getLogger("ecoseek.gateway")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# ── Upstream health state ────────────────────────────────────────────────

_upstream_status: Dict[str, Dict[str, Any]] = {
    "hermes": {"healthy": False, "last_check": 0, "latency_ms": 0},
    "agenticplug": {"healthy": False, "last_check": 0, "latency_ms": 0},
    "local": {"healthy": False, "last_check": 0, "latency_ms": 0},
}

_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_S)
    return _http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_S)
    yield
    await _http_client.aclose()


app = FastAPI(title="EcoSeek Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _safe_exc(exc: BaseException) -> str:
    """Return exception class name only — never the message (may contain URLs/IPs)."""
    return type(exc).__name__


# ── Models ───────────────────────────────────────────────────────────────


class _Message(BaseModel):
    role: str
    content: str


class QueryRequest(BaseModel):
    """Accepts `text` (simple string) or `messages` (OpenAI-style array).

    If both are provided, `messages` wins and `text` is ignored.
    If neither is provided, validation fails.
    """
    text: Optional[str] = Field(None, description="Simple query string (sugar for a single user message).")
    messages: Optional[List[_Message]] = Field(None, description="OpenAI-compatible message array.")
    mode: Literal["auto", "hermes", "agenticplug", "local"] = "auto"
    context: Optional[Dict[str, Any]] = None
    stream: Optional[bool] = None

    @model_validator(mode="after")
    def _require_text_or_messages(self) -> "QueryRequest":
        if not self.messages and not self.text:
            raise ValueError("Provide 'text' or 'messages' (or both).")
        return self

    @property
    def query(self) -> str:
        """Canonical query string. Prefers messages[-1].content."""
        if self.messages:
            return self.messages[-1].content
        return self.text or ""

    @property
    def chat_messages(self) -> List[Dict[str, str]]:
        """OpenAI-compatible messages array."""
        if self.messages:
            return [m.model_dump() for m in self.messages]
        return [{"role": "user", "content": self.text or ""}]


class QueryResponse(BaseModel):
    answer: str
    mode_used: str
    fallback_chain: list


# ── Health endpoints ─────────────────────────────────────────────────────


@app.get("/")
async def root():
    return {"status": "ok", "service": "ecoseek-gateway"}


@app.get("/health/upstreams")
async def health_upstreams():
    """Non-sensitive upstream health summary."""
    results = {}
    client = _client()

    for name, url, path in [
        ("hermes", HERMES_URL, "/health"),
        ("agenticplug", AGENTICPLUG_URL, "/healthz"),
        ("local", LOCAL_LLM_URL, "/v1/models"),
    ]:
        if not url:
            results[name] = {"status": "not_configured"}
            continue
        t0 = time.monotonic()
        try:
            resp = await client.get(url + path)
            latency = round((time.monotonic() - t0) * 1000, 1)
            healthy = 200 <= resp.status_code < 300
            results[name] = {
                "status": "healthy" if healthy else "unhealthy",
                "latency_ms": latency,
            }
            _upstream_status[name] = {
                "healthy": healthy,
                "last_check": time.time(),
                "latency_ms": latency,
            }
        except Exception:
            latency = round((time.monotonic() - t0) * 1000, 1)
            results[name] = {"status": "unreachable", "latency_ms": latency}
            _upstream_status[name] = {
                "healthy": False,
                "last_check": time.time(),
                "latency_ms": latency,
            }

    return results


# ── Failover chain helpers ───────────────────────────────────────────────


async def _try_hermes(query: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    """Hermes via AgenticPlug /v1/orchestrate."""
    if not HERMES_URL and not AGENTICPLUG_URL:
        return None
    client = _client()
    target = AGENTICPLUG_URL + "/v1/orchestrate"
    headers: Dict[str, str] = {}
    if HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_API_KEY}"
    payload = {
        "task": query,
        "mode": "ecoSeek",
        "source": "ecoseek-gateway",
    }
    if context:
        payload["context"] = context
    try:
        resp = await client.post(target, json=payload, headers=headers)
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            task_id = data.get("task_id")
            status = data.get("status", "accepted")
            return f"[Hermes] Task {task_id} {status}. Poll: /hermes/tasks/{task_id}"
    except Exception as exc:
        logger.warning("hermes upstream error: %s", _safe_exc(exc))
    return None


async def _try_agenticplug_chat(query: str, messages: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """AgenticPlug /v1/chat/completions (Ollama passthrough)."""
    if not AGENTICPLUG_URL:
        return None
    client = _client()
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages or [{"role": "user", "content": query}],
    }
    try:
        resp = await client.post(
            AGENTICPLUG_URL + "/v1/chat/completions",
            json=payload,
        )
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning("agenticplug upstream error: %s", _safe_exc(exc))
    return None


async def _try_local_llm(query: str, messages: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Direct local OpenAI-compatible /v1/chat/completions."""
    if not LOCAL_LLM_URL:
        return None
    client = _client()
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages or [{"role": "user", "content": query}],
        "stream": False,
    }
    try:
        resp = await client.post(LOCAL_LLM_URL + "/v1/chat/completions", json=payload)
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return data.get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning("local llm upstream error: %s", _safe_exc(exc))
    return None


def _stream_requested(req: QueryRequest, request: Request) -> bool:
    if req.stream is True:
        return True
    return request.query_params.get("stream", "").lower() == "true"


# ── Query endpoint with failover ────────────────────────────────────────


@app.post("/v1/query", response_model=QueryResponse)
async def query(req: QueryRequest, request: Request):
    if _stream_requested(req, request):
        return JSONResponse(
            status_code=501,
            content={
                "error": "Streaming is not supported for alpha",
                "mode_used": "none",
                "fallback_chain": [],
            },
        )

    chain: List[str] = []
    answer = None
    mode_plan: List[Literal["hermes", "agenticplug", "local"]]
    if req.mode == "auto":
        mode_plan = ["hermes", "agenticplug", "local"]
    else:
        mode_plan = [req.mode]

    for mode in mode_plan:
        if mode == "hermes":
            chain.append("hermes")
            if not (HERMES_URL or HERMES_API_KEY):
                continue
            logger.info("Trying Hermes via AgenticPlug /v1/orchestrate")
            answer = await _try_hermes(req.query, req.context)
        elif mode == "agenticplug":
            chain.append("agenticplug")
            logger.info("Trying AgenticPlug /v1/chat/completions")
            answer = await _try_agenticplug_chat(req.query, req.chat_messages)
        else:
            chain.append("local")
            logger.info("Trying local /v1/chat/completions")
            answer = await _try_local_llm(req.query, req.chat_messages)

        if answer:
            return QueryResponse(answer=answer, mode_used=mode, fallback_chain=chain)

    # All upstreams failed — fail-closed with generic error
    logger.warning("All upstreams failed for query (length=%d)", len(req.query))
    return JSONResponse(
        status_code=503,
        content={
            "error": "All upstreams unavailable",
            "mode_used": "none",
            "fallback_chain": chain,
        },
    )
