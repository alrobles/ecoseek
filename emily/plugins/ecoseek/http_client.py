"""HTTP client for Emily — Cloudflare-safe requests.

Python's urllib inside Docker containers can be blocked by Cloudflare's
Bot Fight Mode (error 1010) due to TLS fingerprinting.  This module
provides a thin wrapper that tries urllib first and automatically falls
back to ``curl`` subprocess (which has a browser-like TLS fingerprint
that Cloudflare allows).

Usage::

    from .http_client import http_post_json, http_get_json

    data = http_post_json(url, payload, headers, timeout=30)
    data = http_get_json(url, headers, timeout=15)
"""

from __future__ import annotations

import json
import logging
import random
import subprocess
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # exponential backoff: 1s, 2s, 4s + jitter

# HTTP status codes that should NOT be retried
_NO_RETRY_CODES = {401, 403, 404, 422}


def http_post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: int = 30,
    retries: int = _MAX_RETRIES,
) -> dict:
    """POST JSON and return parsed response. Falls back to curl on 403.

    Retries on transient failures (empty responses, timeouts, 5xx errors).
    """
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    body = json.dumps(payload).encode("utf-8")

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return _post_once(url, body, hdrs, payload, timeout)
        except _NoRetryError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                delay = min(
                    _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5), 8
                )
                logger.info(
                    "http_post_json attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt,
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]


class _NoRetryError(Exception):
    """Raised for errors that should not be retried (auth, not found)."""


def _post_once(
    url: str,
    body: bytes,
    hdrs: dict,
    payload: dict,
    timeout: int,
) -> dict:
    """Single POST attempt: urllib first, curl fallback on Cloudflare 403."""
    # --- Attempt 1: urllib ---
    try:
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                raise ValueError("Empty response body from server")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        if exc.code in (401, 422):
            logger.error("HTTP %d from %s: %s", exc.code, url[:80], err_body[:200])
            raise _NoRetryError(
                f"Authentication failed (HTTP {exc.code}). Check HERMES_ECOSEEK_API_KEY. "
                f"Server: {err_body[:100]}"
            ) from exc
        if exc.code == 403:
            if (
                "1010" in err_body
                or "cloudflare" in err_body.lower()
                or not err_body.strip()
            ):
                logger.info("urllib blocked by Cloudflare (1010), falling back to curl")
                return _curl_post(url, payload, hdrs, timeout)
            # Non-Cloudflare 403 is an auth error — don't retry
            raise _NoRetryError(f"Forbidden (HTTP 403). {err_body[:100]}") from exc
        if exc.code == 404:
            raise _NoRetryError(f"Not found (HTTP 404): {url}") from exc
        raise
    except json.JSONDecodeError:
        logger.info("urllib got non-JSON response, falling back to curl")
        return _curl_post(url, payload, hdrs, timeout)


def http_get_json(
    url: str,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict | list | None:
    """GET JSON and return parsed response. Falls back to curl on 403."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    # --- Attempt 1: urllib ---
    try:
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if (
                "1010" in err_body
                or "cloudflare" in err_body.lower()
                or not err_body.strip()
            ):
                logger.info("urllib blocked by Cloudflare (1010), falling back to curl")
                return _curl_get(url, hdrs, timeout)
        raise
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("http_get_json failed for %s: %s", url[:120], exc)
        return None

    return None


def _curl_post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    """POST via curl subprocess — bypasses Cloudflare TLS fingerprinting.

    Uses -w to capture HTTP status code and validates response before parsing.
    """
    cmd = [
        "curl",
        "-s",
        "--max-time",
        str(timeout),
        "-w",
        "\n%{http_code}",
    ]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-d", json.dumps(payload), url])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(
            f"curl POST failed (rc={result.returncode}): {result.stderr[:200]}"
        )

    stdout = result.stdout.rstrip()
    lines = stdout.rsplit("\n", 1)
    body = lines[0] if len(lines) == 2 else stdout
    status = int(lines[1]) if len(lines) == 2 and lines[1].isdigit() else 0

    if status == 401:
        raise RuntimeError(
            f"Authentication failed (HTTP 401). Check HERMES_ECOSEEK_API_KEY. "
            f"Server: {body[:100]}"
        )
    if status >= 500:
        raise RuntimeError(f"curl POST got HTTP {status}: {body[:200]}")
    if not body.strip():
        raise ValueError(f"curl POST got empty body (HTTP {status})")

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"curl POST got non-JSON response (HTTP {status}): {body[:200]}"
        ) from exc


def _curl_get(url: str, headers: dict, timeout: int) -> dict | list | None:
    """GET via curl subprocess — bypasses Cloudflare TLS fingerprinting."""
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        logger.warning(
            "curl GET failed (rc=%d): %s", result.returncode, result.stderr[:200]
        )
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
