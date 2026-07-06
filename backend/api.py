"""
EcoSeek API gateway — lightweight router to Emily (Hermes Agent).

Endpoints
---------
GET  /          Health check — always returns {"status": "ok"}.
POST /v1/query  Primary query endpoint. Routes to Emily / AgenticPlug /
                local model with configurable fallback chain.

Emily is the PRIMARY backend — Hermes Agent API server (OpenAI-compatible)
running with the ecoseek plugin + Emily scientific personality at
EMILY_API_URL/v1/chat/completions.

/v1/query — request (v2)
    text        string   required  The user query.
    mode        enum     optional  Routing preference:
                                   auto | hermes | agenticplug | local
                                   Default: auto
                                   "hermes" mode routes to Emily directly.
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

Streaming is NOT supported in alpha. If the caller sends ?stream=true the
endpoint returns 501 Not Implemented.

OpenTelemetry
-------------
When PHOENIX_ENABLED=true, every /v1/query request emits a trace tree:
  POST /v1/query   →  Auto-instrumented by FastAPIInstrumentor
    ecoseek.route   →  Routing decision + fallback chain
      ecoseek.call.{backend} → Upstream HTTP call (emily / agenticplug / local)

curl examples
-------------
# Health
curl http://localhost:3000/

# Simple auto-routed query (hits Emily by default)
curl -s -X POST http://localhost:3000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"text": "List top 5 mammal species in Yucatan."}'

# Force Emily mode
curl -s -X POST http://localhost:3000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"text": "Analyse host-parasite network.", "mode": "hermes"}'

# Force local fallback
curl -s -X POST http://localhost:3000/v1/query \
  -H 'Content-Type: application/json' \
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

app = FastAPI(title="EcoSeek API", version="2.0.0-alpha")

# ── OpenTelemetry auto-instrumentation (no-op when PHOENIX_ENABLED=false) ──
instrument_fastapi(app)

_tracer = get_tracer()


# ── Models ─────────────────────────────────────────────────────────────────


class Mode(str, Enum):
    auto = "auto"
    hermes = "hermes"  # "hermes" mode routes to Emily (Hermes Agent API server)
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


def _emily_headers() -> Dict[str, str]:
    """Auth headers for Emily (Hermes API server)."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if config.EMILY_API_KEY:
        headers["Authorization"] = f"Bearer {config.EMILY_API_KEY}"
    return headers


def _agenticplug_headers() -> Dict[str, str]:
    """Auth headers for AgenticPlug (uses same key as legacy)."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if config.EMILY_API_KEY:
        headers["Authorization"] = f"Bearer {config.EMILY_API_KEY}"
    return headers


def _local_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if config.LOCAL_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LOCAL_LLM_API_KEY}"
    return headers


async def _call_emily(req: QueryRequest) -> Dict[str, Any]:
    """
    POST to Emily (Hermes Agent API server) directly.

    Emily exposes an OpenAI-compatible /v1/chat/completions endpoint.
    This is the PRIMARY backend — Hermes Agent with ecoseek plugin,
    full tool access (eco_analyze, ku_hpc, web_search, etc.),
    and the Emily scientific personality.
    """
    url = f"{config.EMILY_API_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": "emily",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Emily, an expert ecological scientist and AI assistant "
                    "for EcoSeek. Respond in markdown with scientific rigour."
                ),
            },
            {"role": "user", "content": req.text},
        ],
        "stream": False,
    }
    if req.session_id:
        payload["session_id"] = req.session_id

    with _tracer.start_as_current_span("ecoseek.call.emily") as span:
        span.set_attribute("ecoseek.upstream", "emily")
        span.set_attribute("http.url", url)
        span.set_attribute("http.method", "POST")
        if req.session_id:
            span.set_attribute("ecoseek.session_id", req.session_id)
        try:
            async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
                r = await client.post(url, json=payload, headers=_emily_headers())
                span.set_attribute("http.status_code", r.status_code)
                r.raise_for_status()
                data = r.json()
                span.set_attribute("ecoseek.success", True)
                # Convert OpenAI chat completion to our response format
                content = ""
                if data.get("choices"):
                    content = data["choices"][0].get("message", {}).get("content", "")
                return {
                    "text": content,
                    "model": data.get("model", "emily"),
                    "raw": data,
                }
        except Exception as exc:  # noqa: BLE001
            span.set_attribute("ecoseek.success", False)
            span.set_attribute("error", True)
            span.record_exception(exc)
            raise


async def _call_agenticplug(req: QueryRequest) -> Dict[str, Any]:
    """POST to AgenticPlug chat completions (OpenAI-compatible fallback)."""
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
                r = await client.post(url, json=payload, headers=_agenticplug_headers())
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

    mode=hermes     → Emily (Hermes Agent API) direct; hard-fail if down.
                      This is the PRIMARY path — full agent with tools.
    mode=agenticplug → AgenticPlug only; fail if down.
    mode=local       → Local LLM only; fail if not configured or down.
    mode=auto        → Emily (if enabled) → AgenticPlug → local; each step
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
            result = await _try("emily", _call_emily(req))
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            if result is None:
                span.set_attribute("ecoseek.success", False)
                span.set_attribute("ecoseek.mode_used", "")
                return QueryResponse(
                    success=False,
                    mode_used=None,
                    result=None,
                    error="Emily (Hermes Agent) unavailable and no fallback allowed for mode=hermes.",
                    fallback_chain=chain,
                )
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "emily")
            return QueryResponse(
                success=True,
                mode_used="emily",
                result=result,
                error=None,
                fallback_chain=chain,
            )

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
            return QueryResponse(
                success=True,
                mode_used="agenticplug",
                result=result,
                error=None,
                fallback_chain=chain,
            )

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
            return QueryResponse(
                success=True,
                mode_used="local",
                result=result,
                error=None,
                fallback_chain=chain,
            )

        # mode=auto: try Emily first (if enabled), then AgenticPlug, then local.
        if config.EMILY_ENABLED and config.EMILY_API_URL:
            result = await _try("emily", _call_emily(req))
            if result is not None:
                span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
                span.set_attribute("ecoseek.success", True)
                span.set_attribute("ecoseek.mode_used", "emily")
                return QueryResponse(
                    success=True,
                    mode_used="emily",
                    result=result,
                    error=None,
                    fallback_chain=chain,
                )

        result = await _try("agenticplug", _call_agenticplug(req))
        if result is not None:
            span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
            span.set_attribute("ecoseek.success", True)
            span.set_attribute("ecoseek.mode_used", "agenticplug")
            return QueryResponse(
                success=True,
                mode_used="agenticplug",
                result=result,
                error=None,
                fallback_chain=chain,
            )

        if config.LOCAL_LLM_URL:
            result = await _try("local", _call_local(req))
            if result is not None:
                span.set_attribute("ecoseek.fallback_chain", ",".join(chain))
                span.set_attribute("ecoseek.success", True)
                span.set_attribute("ecoseek.mode_used", "local")
                return QueryResponse(
                    success=True,
                    mode_used="local",
                    result=result,
                    error=None,
                    fallback_chain=chain,
                )

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


class SearchRequest(BaseModel):
    """Search GBIF ecological literature via Meilisearch."""
    q: str = Field(..., description="Search query")
    limit: int = Field(default=10, ge=1, le=100, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    filter_has_abstract: bool = Field(default=False, description="Only papers with abstract >200 chars")
    min_year: int = Field(default=0, description="Minimum publication year")


class SearchResult(BaseModel):
    """A single literature search result."""
    id: str
    title: str
    abstract: str
    year: str
    keywords: str
    doi: str


class SearchResponse(BaseModel):
    """Meilisearch literature search response."""
    success: bool
    query: str
    total_hits: int
    processing_time_ms: int
    results: list[SearchResult]


@app.post("/v1/search", response_model=SearchResponse, summary="Search GBIF ecological literature")
async def search_papers(req: SearchRequest):  # returns SearchResponse | JSONResponse
    """
    Full-text search across 62,000 GBIF-cited ecological papers.

    Powered by Meilisearch — returns results in <100ms with typo-tolerant,
    relevance-ranked matching. Filters available for abstract presence and
    minimum publication year.
    """
    if not config.MEILI_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"detail": "Meilisearch is not enabled. Set MEILI_ENABLED=true."},
        )

    # Build Meilisearch query
    meili_query: dict[str, Any] = {
        "q": req.q,
        "limit": req.limit,
        "offset": req.offset,
        "attributesToRetrieve": ["id", "title", "abstract", "year", "keywords", "doi"],
    }

    filters: list[str] = []
    if req.filter_has_abstract:
        filters.append("has_abstract = true")
    if req.min_year > 0:
        filters.append(f"year >= {req.min_year}")
    if filters:
        meili_query["filter"] = " AND ".join(filters)

    try:
        async with httpx.AsyncClient(timeout=config.UPSTREAM_TIMEOUT_S) as client:
            resp = await client.post(
                f"{config.MEILI_URL}/indexes/{config.MEILI_INDEX}/search",
                json=meili_query,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.error("Meilisearch search failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Meilisearch unavailable: {exc}"},
        )

    results: list[SearchResult] = []
    for hit in data.get("hits", []):
        results.append(SearchResult(
            id=hit.get("id", ""),
            title=hit.get("title", ""),
            abstract=hit.get("abstract", ""),
            year=str(hit.get("year", "")),
            keywords=hit.get("keywords", ""),
            doi=hit.get("doi", ""),
        ))

    return SearchResponse(
        success=True,
        query=req.q,
        total_hits=data.get("estimatedTotalHits", 0),
        processing_time_ms=data.get("processingTimeMs", 0),
        results=results,
    )


@app.post("/v1/smart-search", summary="AI-powered semantic literature search")
async def smart_search_papers(req: SearchRequest):
    """
    Smart search with LLM-powered query expansion + semantic re-ranking.
    
    Uses the Q6000 Ollama cluster to:
    1. Expand the query with scientific terminology
    2. Search Meilisearch for top-50 papers
    3. Re-rank results based on semantic relevance to user intent
    
    Slower (~5-10s) but much more accurate than keyword search.
    """
    if not config.MEILI_ENABLED:
        return JSONResponse(status_code=503, content={"detail": "Meilisearch not enabled."})
    
    try:
        from smart_search import expand_query, rerank_papers, search_meili
        
        # 1. Expand query with LLM
        log.info("Smart search: expanding query '%s'", req.q[:80])
        expanded = expand_query(req.q)
        log.info("Smart search: expanded to '%s'", expanded[:100])
        
        # 2. Search Meilisearch
        meili_results = search_meili(expanded, limit=50)
        papers = meili_results.get("hits", [])
        log.info("Smart search: Meilisearch returned %d hits", len(papers))
        
        # 3. Re-rank with LLM
        if len(papers) > 10:
            papers = rerank_papers(req.q, papers)
            log.info("Smart search: re-ranked to %d papers", len(papers))
        
        # Format results
        results: list[SearchResult] = []
        for hit in papers[:req.limit]:
            results.append(SearchResult(
                id=hit.get("id", ""),
                title=hit.get("title", ""),
                abstract=hit.get("abstract", ""),
                year=str(hit.get("year", "")),
                keywords=hit.get("keywords", ""),
                doi=hit.get("doi", ""),
            ))
        
        return SearchResponse(
            success=True,
            query=req.q,
            total_hits=len(papers),
            processing_time_ms=meili_results.get("processingTimeMs", 0),
            results=results,
        )
    except Exception as exc:
        log.error("Smart search failed: %s", exc)
        return JSONResponse(status_code=502, content={"detail": f"Smart search error: {exc}"})


@app.post("/v1/metasearch", summary="Multi-agent dialectical literature search")
async def metasearch_papers(req: SearchRequest):
    """
    Alpha↔Beta dialectical search — multiple Hermes agents debate and refine.
    
    Alpha proposes query expansion + ranking.
    Beta critiques and suggests improvements.
    Alpha revises → consensus final ranking.
    
    Slower (~15-30s) but highest quality results with dialectical reasoning.
    """
    try:
        from metasearch import metasearch
        result = metasearch(req.q)
        return JSONResponse(content={
            "success": True,
            "query": req.q,
            "total_hits": len(result["results"]),
            "processing_time_ms": result["time_ms"],
            "results": result["results"][:req.limit],
            "method": "didal",
        })
    except Exception as exc:
        log.error("Metasearch failed: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/", summary="Health check")
async def health() -> Dict[str, str]:
    """Returns immediately with status=ok. Used by docker healthcheck."""
    return {"status": "ok"}


@app.post("/v1/query", response_model=QueryResponse, summary="Primary query endpoint")
async def query(
    req: QueryRequest,
    stream: Optional[bool] = Query(
        default=None, description="Streaming — not supported in alpha."
    ),
) -> QueryResponse:
    """
    Route a natural-language query to the appropriate backend.

    Emily (Hermes Agent) is the PRIMARY backend. It has full tool access
    (eco_analyze, ku_hpc, web_search, GitHub, etc.) and responds with
    scientific rigour.

    Streaming is **not** supported in alpha. Pass ``?stream=true`` to get a
    501 response rather than unexpected behaviour.
    """
    if stream:
        return JSONResponse(
            status_code=501,
            content={
                "detail": "Streaming is not supported in alpha. Omit ?stream=true."
            },
        )

    return await _route(req)
