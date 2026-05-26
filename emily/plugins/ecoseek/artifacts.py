"""GitHub artifacts pivot — upload large files from Hermes to a GitHub repo.

When Hermes generates large outputs on the cluster (rasters, CSVs, plots),
they can't be returned inline through the Cloudflare tunnel (100s timeout,
~5MB practical limit). Instead, we upload them to a dedicated GitHub repo
(``ecoseek-artifacts``) and return a raw.githubusercontent.com URL.

Architecture:
    Hermes (cluster) → git push → ecoseek-artifacts → raw URL → Emily/frontend

This module provides:
  1. ``upload_artifact()`` — push a file to the artifacts repo via Hermes
  2. ``get_artifact_url()`` — construct the raw download URL
  3. ``list_artifacts()`` — list files in the repo for a session

The artifacts repo is ``alrobles/ecoseek-artifacts`` (auto-created if needed).
Files are organized by date and session: ``YYYY-MM-DD/{session_id}/{filename}``

For files <5MB, use inline base64 in the JSON response instead.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_ARTIFACTS_REPO = os.environ.get("ECOSEEK_ARTIFACTS_REPO", "alrobles/ecoseek-artifacts")
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_HERMES_REMOTE_URL = os.environ.get("HERMES_REMOTE_URL", "https://hermes.ecoseek.org").rstrip("/")
_HERMES_API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")

_INLINE_SIZE_LIMIT = 5 * 1024 * 1024  # 5MB — files smaller than this go inline


def get_artifact_url(path: str) -> str:
    """Construct the raw download URL for a file in the artifacts repo."""
    return f"https://raw.githubusercontent.com/{_ARTIFACTS_REPO}/main/{path}"


def upload_artifact_via_hermes(
    local_path: str,
    artifact_name: str,
    session_id: str = "",
) -> dict:
    """Upload a file from the cluster to the artifacts repo via Hermes.

    Hermes runs on the cluster and has git access. We ask it to:
    1. Read the file from the cluster filesystem
    2. Push it to the ecoseek-artifacts repo

    Parameters
    ----------
    local_path : str
        Path to the file on the cluster (e.g., /home/a474r867/work/sdm/output.tif)
    artifact_name : str
        Name for the artifact file in the repo.
    session_id : str
        Session identifier for organizing artifacts.

    Returns
    -------
    dict
        {success, url, path, size_bytes}
    """
    if not _HERMES_API_KEY:
        return {"success": False, "error": "HERMES_ECOSEEK_API_KEY not configured"}

    from datetime import datetime
    date_prefix = datetime.utcnow().strftime("%Y-%m-%d")
    sid = session_id or f"session-{int(time.time())}"
    repo_path = f"{date_prefix}/{sid}/{artifact_name}"

    try:
        from .http_client import http_post_json
        resp = http_post_json(
            f"{_HERMES_REMOTE_URL}/v1/chat/completions",
            body={
                "model": "hermes-agent",
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Upload the file at '{local_path}' to the GitHub repo "
                        f"'{_ARTIFACTS_REPO}' at path '{repo_path}'. "
                        f"Use: cd /tmp && git clone https://github.com/{_ARTIFACTS_REPO}.git artifacts-repo && "
                        f"mkdir -p artifacts-repo/{date_prefix}/{sid} && "
                        f"cp '{local_path}' artifacts-repo/{repo_path} && "
                        f"cd artifacts-repo && git add . && "
                        f"git commit -m 'artifact: {artifact_name}' && git push && "
                        f"echo 'UPLOAD_SUCCESS:{repo_path}'"
                    ),
                }],
            },
            headers={"Authorization": f"Bearer {_HERMES_API_KEY}"},
            timeout=60,
        )

        content = ""
        choices = resp.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        if "UPLOAD_SUCCESS" in content:
            url = get_artifact_url(repo_path)
            logger.info("Artifact uploaded: %s → %s", local_path, url)
            return {
                "success": True,
                "url": url,
                "path": repo_path,
                "repo": _ARTIFACTS_REPO,
            }
        else:
            return {
                "success": False,
                "error": f"Upload may have failed. Hermes response: {content[:300]}",
            }

    except Exception as exc:
        logger.warning("Artifact upload failed: %s", exc)
        return {"success": False, "error": str(exc)[:200]}


def upload_artifact_direct(
    content_bytes: bytes,
    artifact_name: str,
    session_id: str = "",
    commit_message: str = "",
) -> dict:
    """Upload bytes directly to the artifacts repo via GitHub API.

    Uses the GitHub Contents API (PUT /repos/:owner/:repo/contents/:path)
    to upload files up to 100MB directly, without needing Hermes.

    Requires GITHUB_TOKEN environment variable.
    """
    if not _GITHUB_TOKEN:
        return {"success": False, "error": "GITHUB_TOKEN not configured for direct upload"}

    import urllib.request
    import urllib.error
    from datetime import datetime

    date_prefix = datetime.utcnow().strftime("%Y-%m-%d")
    sid = session_id or f"session-{int(time.time())}"
    repo_path = f"{date_prefix}/{sid}/{artifact_name}"

    b64_content = base64.b64encode(content_bytes).decode("ascii")
    msg = commit_message or f"artifact: {artifact_name}"

    api_url = f"https://api.github.com/repos/{_ARTIFACTS_REPO}/contents/{repo_path}"
    payload = json.dumps({
        "message": msg,
        "content": b64_content,
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {_GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            download_url = data.get("content", {}).get("download_url", get_artifact_url(repo_path))
            logger.info("Artifact uploaded directly: %s", download_url)
            return {
                "success": True,
                "url": download_url,
                "path": repo_path,
                "size_bytes": len(content_bytes),
                "repo": _ARTIFACTS_REPO,
            }
    except urllib.error.HTTPError as exc:
        err = ""
        try:
            err = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        logger.warning("Direct artifact upload failed (HTTP %d): %s", exc.code, err)
        return {"success": False, "error": f"HTTP {exc.code}: {err[:200]}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}


def should_use_artifact(size_bytes: int) -> bool:
    """Determine if a file should be uploaded as an artifact vs inline."""
    return size_bytes > _INLINE_SIZE_LIMIT
