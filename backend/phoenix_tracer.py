"""
Phoenix OpenTelemetry tracer for the EcoSeek API gateway.

Sends spans to Arize Phoenix via OTLP/HTTP when PHOENIX_ENABLED=true.
Phoenix must be running (docker compose --profile observability up phoenix).

Environment variables
---------------------
PHOENIX_ENABLED       Set to "true" to activate tracing. Default: false.
PHOENIX_ENDPOINT      OTLP collector endpoint. Default: http://phoenix:6006/v1/traces
PHOENIX_PROJECT_NAME  Project name in the Phoenix UI. Default: ecoseek
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("ecoseek.phoenix")

PHOENIX_ENABLED: bool = os.getenv("PHOENIX_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
PHOENIX_ENDPOINT: str = os.getenv(
    "PHOENIX_ENDPOINT",
    "http://phoenix:6006/v1/traces",
)
PHOENIX_PROJECT_NAME: str = os.getenv("PHOENIX_PROJECT_NAME", "ecoseek")

_tracer = None


def _init_tracer():
    """Lazily initialise the OTel SDK with an OTLP/HTTP exporter."""
    global _tracer
    if _tracer is not None:
        return _tracer

    if not PHOENIX_ENABLED:
        _tracer = _NoOpTracer()
        return _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({SERVICE_NAME: PHOENIX_PROJECT_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=PHOENIX_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("ecoseek.gateway")
        log.info(
            "Phoenix tracing enabled → %s (project=%s)",
            PHOENIX_ENDPOINT,
            PHOENIX_PROJECT_NAME,
        )
    except ImportError:
        log.warning(
            "PHOENIX_ENABLED=true but OpenTelemetry packages not installed. "
            "Run: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp-proto-http",
        )
        _tracer = _NoOpTracer()
    except Exception:  # noqa: BLE001
        log.exception("Failed to initialise Phoenix tracer — tracing disabled.")
        _tracer = _NoOpTracer()

    return _tracer


class _NoOpSpan:
    """Drop-in stand-in for an OTel span that does nothing."""

    def set_attribute(self, key: str, value: str | bool | int | float) -> None:
        pass

    def set_attributes(self, attrs: dict) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def set_status(self, status, description: str = "") -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @property
    def is_recording(self) -> bool:
        return False


class _NoOpTracer:
    """Drop-in stand-in for an OTel tracer that creates no-op spans."""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs):
        return _NoOpSpan()


def get_tracer():
    """Return the OTel tracer, lazily initialised. No-op when disabled."""
    global _tracer
    if _tracer is None:
        _tracer = _init_tracer()
    return _tracer


def instrument_fastapi(app):
    """Auto-instrument FastAPI with OpenTelemetry if PHOENIX_ENABLED=true.

    Call once during startup, before the first request.
    """
    if not PHOENIX_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        log.info("FastAPI auto-instrumentation active.")
    except ImportError:
        log.warning(
            "PHOENIX_ENABLED=true but opentelemetry-instrumentation-fastapi "
            "is not installed. FastAPI spans will NOT be auto-created. "
            "Run: pip install opentelemetry-instrumentation-fastapi.",
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to instrument FastAPI — continuing without.")
