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
import subprocess
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def http_post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: int = 30,
) -> dict:
    """POST JSON and return parsed response. Falls back to curl on 403."""
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    body = json.dumps(payload).encode("utf-8")

    # --- Attempt 1: urllib ---
    try:
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            if "1010" in err_body or "cloudflare" in err_body.lower() or not err_body.strip():
                logger.info("urllib blocked by Cloudflare (1010), falling back to curl")
                return _curl_post(url, payload, hdrs, timeout)
        raise

    return {}


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
                err_body = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            if "1010" in err_body or "cloudflare" in err_body.lower() or not err_body.strip():
                logger.info("urllib blocked by Cloudflare (1010), falling back to curl")
                return _curl_get(url, hdrs, timeout)
        raise
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("http_get_json failed for %s: %s", url[:120], exc)
        return None

    return None


def _curl_post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    """POST via curl subprocess — bypasses Cloudflare TLS fingerprinting."""
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-d", json.dumps(payload), url])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    if result.returncode != 0:
        raise RuntimeError(f"curl POST failed (rc={result.returncode}): {result.stderr[:200]}")
    return json.loads(result.stdout)


def _curl_get(url: str, headers: dict, timeout: int) -> dict | list | None:
    """GET via curl subprocess — bypasses Cloudflare TLS fingerprinting."""
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    if result.returncode != 0:
        logger.warning("curl GET failed (rc=%d): %s", result.returncode, result.stderr[:200])
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
