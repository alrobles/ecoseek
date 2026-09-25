"""Phoenix span export for EcoSeek World — observability, fire-and-forget.

Posts OpenInference-style spans to a Phoenix server's REST endpoint
(`/v1/spans`). Zero hard dependencies (stdlib urllib); every failure path
degrades to a debug log — world operations NEVER fail because tracing did.

Env vars:
  PHOENIX_ENDPOINT    - Phoenix server (default: http://localhost:6006)
  PHOENIX_API_KEY     - optional bearer token
  ECOSEEK_WORLD_TRACE - "0" disables export entirely (default: on)

Span names follow `ecoseek.world.<op>`; attributes carry the recorded
provenance (artifact_id, event kind, agent, run_id) — never payloads that
could contain secrets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_ENDPOINT = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006").rstrip("/")
_API_KEY = os.environ.get("PHOENIX_API_KEY", "")


def _enabled() -> bool:
    return os.environ.get("ECOSEEK_WORLD_TRACE", "1") != "0"


def _post(span: dict) -> bool:
    try:
        body = json.dumps({"spans": [span]}).encode("utf-8")
        req = urllib.request.Request(
            f"{_ENDPOINT}/v1/spans",
            data=body,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}),
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception as exc:
        logger.debug("world trace export failed (non-blocking): %s", exc)
        return False


def _span_dict(name: str, start: float, end: float, status: str, attrs: dict) -> dict:
    return {
        "name": f"ecoseek.world.{name}",
        "context": {
            "trace_id": hashlib.sha256(
                f"{start}{name}{attrs.get('artifact_id', '')}".encode()
            ).hexdigest()[:32],
            "span_id": hashlib.sha256(f"{end}{name}{start}".encode()).hexdigest()[:16],
        },
        "start_time": start,
        "end_time": end,
        "attributes": {
            "openinference.span.kind": "CHAIN",
            **{f"ecoseek.world.{k}": v for k, v in attrs.items()},
        },
        "status": status,
    }


def emit(name: str, **attrs) -> bool:
    """Point-event span (world events are instantaneous)."""
    if not _enabled():
        return False
    now = time.time()
    return _post(_span_dict(name, now, now, "OK", attrs))


@contextmanager
def span(name: str, **attrs):
    """Timed span around an operation; status ERROR on exception (re-raised).
    Yields the attrs dict — callers may add result fields before exit; they
    are read when the span closes."""
    if not _enabled():
        yield attrs
        return
    start = time.time()
    try:
        yield attrs
    except Exception:
        _post(_span_dict(name, start, time.time(), "ERROR", attrs))
        raise
    else:
        _post(_span_dict(name, start, time.time(), "OK", attrs))
