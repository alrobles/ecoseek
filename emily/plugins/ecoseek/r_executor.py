"""R code executor — agentic bridge to rocker/geospatial workspace.

Emily generates R code via DiDAL or direct response, sends it to the
R workspace container for execution, and reads back the results
(stdout, stderr, plots, CSVs, etc.).

The R workspace runs rocker/geospatial with sf, terra, dismo, vegan,
ape, rgbif, and other ecology packages pre-installed.
"""
from __future__ import annotations

import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

_R_WORKSPACE_URL = os.environ.get(
    "R_WORKSPACE_URL", "http://r-workspace:8787"
).rstrip("/")

_R_EXEC_TIMEOUT = int(os.environ.get("R_EXEC_TIMEOUT", "300"))


def _is_r_workspace_available() -> bool:
    """Check if the R workspace container is reachable."""
    try:
        from .http_client import http_get_json
        result = http_get_json(f"{_R_WORKSPACE_URL}/health", timeout=5)
        return result.get("status") == "ok"
    except Exception:
        return False


def execute_r_code(
    code: str,
    timeout: int | None = None,
    job_id: str | None = None,
    task_id: str | None = None,
) -> str:
    """Execute R code in the geospatial workspace and return results.

    The R workspace has rocker/geospatial pre-installed with:
    sf, terra, raster, dismo, vegan, ape, picante, rgbif, taxize,
    ENMeval, spocc, CoordinateCleaner, biomod2, and more.

    Args:
        code: R code to execute.
        timeout: Max execution time in seconds (default: 300).
        job_id: Optional job identifier for tracking.

    Returns:
        JSON string with stdout, stderr, output files, and exit code.
    """
    from .http_client import http_post_json

    if not code.strip():
        return json.dumps({"success": False, "error": "empty_code"})

    effective_timeout = min(timeout or _R_EXEC_TIMEOUT, _R_EXEC_TIMEOUT)
    effective_job_id = job_id or str(uuid.uuid4())[:12]

    try:
        result = http_post_json(
            f"{_R_WORKSPACE_URL}/execute",
            payload={
                "code": code,
                "timeout": effective_timeout,
                "job_id": effective_job_id,
            },
            timeout=effective_timeout + 30,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error("R execution failed: %s", exc)
        return json.dumps({
            "success": False,
            "error": str(exc)[:500],
            "job_id": effective_job_id,
            "r_workspace_url": _R_WORKSPACE_URL,
        }, ensure_ascii=False)


def list_r_packages(task_id: str | None = None) -> str:
    """List installed R packages in the geospatial workspace."""
    from .http_client import http_get_json

    try:
        result = http_get_json(f"{_R_WORKSPACE_URL}/packages", timeout=30)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)[:300]})


def r_workspace_status(task_id: str | None = None) -> str:
    """Check R workspace container status and available packages."""
    available = _is_r_workspace_available()
    return json.dumps({
        "available": available,
        "url": _R_WORKSPACE_URL,
        "description": (
            "R geospatial workspace with rocker/geospatial. "
            "Packages: sf, terra, raster, dismo, vegan, ape, rgbif, "
            "taxize, ENMeval, spocc, CoordinateCleaner, biomod2, etc."
        ) if available else "R workspace container is not running.",
    })
