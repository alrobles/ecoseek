"""Phoenix / OpenTelemetry tracing for DiDAL Protocol.

Instruments every DiDAL stage as a span inside a root trace. All tracing
is a **no-op** when ``PHOENIX_COLLECTOR_ENDPOINT`` is not set — zero
overhead in environments without Phoenix.

Trace tree per protocol execution::

    didal_protocol (root)
    ├── classification
    ├── frontend.frame_task
    ├── backend.retrieve           (didal_literature only)
    │   ├── retrieve.openalex
    │   ├── retrieve.semantic_scholar
    │   ├── retrieve.gbif
    │   └── retrieve.entrez
    ├── backend.synthesize_draft
    ├── frontend.critique          (per round)
    ├── backend.revise             (per round)
    └── finalize_report

Span attributes follow the DiDAL protocol spec plus OpenInference
semantic conventions where applicable.

Environment variables:
    PHOENIX_COLLECTOR_ENDPOINT  — e.g. http://localhost:6006/v1/traces
    PHOENIX_PROJECT_NAME        — project name in Phoenix UI (default: ecoseek-didal)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "")
_PROJECT = os.environ.get("PHOENIX_PROJECT_NAME", "ecoseek-didal")
_ENABLED = bool(_ENDPOINT)

# Lazy-initialized tracer
_tracer = None
_trace_provider = None


def _get_tracer():
    """Lazy-initialize the OpenTelemetry tracer with Phoenix exporter."""
    global _tracer, _trace_provider
    if _tracer is not None:
        return _tracer
    if not _ENABLED:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": "ecoseek-emily",
                "service.version": "1.0.0",
                "phoenix.project.name": _PROJECT,
            }
        )

        exporter = OTLPSpanExporter(endpoint=_ENDPOINT)
        processor = BatchSpanProcessor(exporter)

        provider = TracerProvider(resource=resource)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        _trace_provider = provider
        _tracer = trace.get_tracer("ecoseek.didal", "1.0.0")
        logger.info("Phoenix tracing enabled → %s (project: %s)", _ENDPOINT, _PROJECT)
        return _tracer

    except ImportError:
        logger.debug(
            "OpenTelemetry packages not installed — tracing disabled. "
            "Install with: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )
        return None
    except Exception as exc:
        logger.warning("Failed to initialize Phoenix tracer: %s", exc)
        return None


def is_tracing_enabled() -> bool:
    """Return True if tracing is configured and packages are available."""
    return _get_tracer() is not None


def shutdown():
    """Flush pending spans and shut down the tracer provider."""
    global _trace_provider
    if _trace_provider is not None:
        try:
            _trace_provider.shutdown()
        except Exception:
            pass
        _trace_provider = None


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


def _prompt_hash(text: str) -> str:
    """Short hash of the prompt for trace correlation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _set_span_attrs(span, attrs: dict[str, Any]):
    """Set attributes on a span, skipping None values."""
    for key, val in attrs.items():
        if val is None:
            continue
        if isinstance(val, (list, dict)):
            import json

            span.set_attribute(key, json.dumps(val, ensure_ascii=False, default=str))
        elif isinstance(val, float):
            span.set_attribute(key, round(val, 4))
        else:
            span.set_attribute(key, val)


@contextmanager
def trace_protocol(
    protocol_id: str,
    prompt: str,
    mode: str,
    classification: dict | None = None,
) -> Generator[dict, None, None]:
    """Root span for the entire DiDAL protocol execution.

    Yields a context dict that child spans can read/write to share state.
    Usage::

        with trace_protocol("abc123", prompt, "didal") as ctx:
            ctx["classification"] = {...}
            with trace_stage("classification", ctx):
                ...
    """
    tracer = _get_tracer()
    ctx: dict[str, Any] = {
        "protocol_id": protocol_id,
        "prompt": prompt,
        "prompt_hash": _prompt_hash(prompt),
        "mode": mode,
        "start_time": time.time(),
        "root_span": None,
        "trace_id": None,
    }

    if tracer is None:
        yield ctx
        return

    from opentelemetry import trace as otel_trace

    with tracer.start_as_current_span(
        "didal_protocol",
        kind=otel_trace.SpanKind.SERVER,
    ) as root_span:
        ctx["root_span"] = root_span
        span_context = root_span.get_span_context()
        ctx["trace_id"] = (
            format(span_context.trace_id, "032x") if span_context else None
        )

        _set_span_attrs(
            root_span,
            {
                "didal.protocol_id": protocol_id,
                "didal.mode": mode,
                "didal.prompt_hash": ctx["prompt_hash"],
                "input.value": prompt[:500],
                "phoenix.project.name": _PROJECT,
            },
        )
        if classification:
            _set_span_attrs(
                root_span,
                {
                    "didal.complexity_score": classification.get("complexity_score"),
                    "didal.reasons": classification.get("reasons"),
                    "didal.expected_depth": classification.get("expected_depth"),
                },
            )

        try:
            yield ctx
        except Exception as exc:
            root_span.set_status(otel_trace.StatusCode.ERROR, str(exc))
            root_span.record_exception(exc)
            raise
        finally:
            elapsed = round(time.time() - ctx["start_time"], 1)
            _set_span_attrs(
                root_span,
                {
                    "didal.elapsed_seconds": elapsed,
                    "didal.critique_rounds": ctx.get("critique_rounds", 0),
                    "didal.total_sources": ctx.get("total_sources", 0),
                },
            )


@contextmanager
def trace_stage(
    stage_name: str,
    ctx: dict,
    agent_role: str = "system",
    round_index: int = 0,
    **extra_attrs,
) -> Generator[dict, None, None]:
    """Child span for a single DiDAL stage.

    Parameters
    ----------
    stage_name : str
        One of: classification, frontend.frame_task, backend.retrieve,
        backend.synthesize_draft, frontend.critique, backend.revise,
        finalize_report, direct_answer.
    ctx : dict
        Protocol context from trace_protocol.
    agent_role : str
        "frontend_naive", "backend_expert", "judge", or "system".
    round_index : int
        Critique-revise round number (0 for non-looping stages).
    extra_attrs : dict
        Additional span attributes.

    Yields a stage_ctx dict for recording stage-specific results.
    """
    stage_ctx: dict[str, Any] = {
        "stage_name": stage_name,
        "start_time": time.time(),
        "latency_ms": 0,
    }

    tracer = _get_tracer()
    if tracer is None:
        try:
            yield stage_ctx
        finally:
            stage_ctx["latency_ms"] = round(
                (time.time() - stage_ctx["start_time"]) * 1000
            )
        return

    from opentelemetry import trace as otel_trace

    with tracer.start_as_current_span(stage_name) as span:
        _set_span_attrs(
            span,
            {
                "didal.stage": stage_name,
                "didal.agent_role": agent_role,
                "didal.protocol_id": ctx.get("protocol_id"),
                "didal.prompt_hash": ctx.get("prompt_hash"),
                "didal.round_index": round_index,
            },
        )
        _set_span_attrs(span, extra_attrs)

        try:
            yield stage_ctx
        except Exception as exc:
            span.set_status(otel_trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            latency = round((time.time() - stage_ctx["start_time"]) * 1000)
            stage_ctx["latency_ms"] = latency
            _set_span_attrs(span, {"didal.latency_ms": latency})

            # Record stage-specific results
            for key in (
                "tokens_used",
                "retrieved_sources",
                "evidence_used",
                "confidence",
                "quality",
                "requires_revision",
                "provider",
                "error",
            ):
                if key in stage_ctx:
                    _set_span_attrs(span, {f"didal.{key}": stage_ctx[key]})


@contextmanager
def trace_retrieval_source(
    provider: str,
    ctx: dict,
    query: str,
) -> Generator[dict, None, None]:
    """Child span for a single retrieval source call (under backend.retrieve).

    Usage::

        with trace_retrieval_source("openalex", ctx, query) as src_ctx:
            results = search_openalex(query)
            src_ctx["results_count"] = len(results)
    """
    src_ctx: dict[str, Any] = {
        "provider": provider,
        "start_time": time.time(),
    }

    tracer = _get_tracer()
    if tracer is None:
        yield src_ctx
        return

    from opentelemetry import trace as otel_trace

    with tracer.start_as_current_span(f"retrieve.{provider}") as span:
        _set_span_attrs(
            span,
            {
                "didal.stage": "retrieve",
                "didal.retrieval.provider": provider,
                "didal.retrieval.query": query[:200],
                "didal.protocol_id": ctx.get("protocol_id"),
            },
        )
        try:
            yield src_ctx
        except Exception as exc:
            span.set_status(otel_trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            src_ctx["error"] = str(exc)[:200]
            raise
        finally:
            latency = round((time.time() - src_ctx["start_time"]) * 1000)
            _set_span_attrs(
                span,
                {
                    "didal.latency_ms": latency,
                    "didal.retrieval.results_count": src_ctx.get("results_count", 0),
                    "didal.retrieval.error": src_ctx.get("error"),
                },
            )


def record_llm_call(
    ctx: dict,
    model: str,
    usage: dict,
    stage: str,
):
    """Record LLM call metadata on the current span (if tracing is active)."""
    tracer = _get_tracer()
    if tracer is None:
        return

    from opentelemetry import trace as otel_trace

    span = otel_trace.get_current_span()
    if span and span.is_recording():
        _set_span_attrs(
            span,
            {
                "llm.model_name": model,
                "llm.token_count.prompt": usage.get("prompt_tokens", 0),
                "llm.token_count.completion": usage.get("completion_tokens", 0),
                "llm.token_count.total": usage.get("total_tokens", 0),
            },
        )
