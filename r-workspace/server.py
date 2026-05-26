"""R Workspace HTTP Bridge — lightweight API for executing R code.

Emily sends R code via POST /execute, and this server runs it inside
the rocker/geospatial container with full access to geospatial R packages.

Endpoints:
  POST /execute   — run R code, return stdout/stderr/files
  GET  /health    — container health check
  GET  /packages  — list installed R packages
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[r-workspace] %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE = Path(os.environ.get("R_WORKSPACE_DIR", "/workspace"))
PORT = int(os.environ.get("R_WORKSPACE_PORT", "8787"))
TIMEOUT = int(os.environ.get("R_EXEC_TIMEOUT", "300"))

WORKSPACE.mkdir(parents=True, exist_ok=True)


class RWorkspaceHandler(BaseHTTPRequestHandler):
    """Handle R code execution requests."""

    def log_message(self, format, *args):
        logger.info(format, *args)

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "workspace": str(WORKSPACE)})
        elif self.path == "/packages":
            self._handle_packages()
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/execute":
            self._handle_execute()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_packages(self) -> None:
        """List installed R packages."""
        try:
            result = subprocess.run(
                ["Rscript", "-e", "cat(paste(installed.packages()[,'Package'], collapse='\\n'))"],
                capture_output=True, text=True, timeout=30,
            )
            packages = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            self._send_json(200, {"packages": packages, "count": len(packages)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _handle_execute(self) -> None:
        """Execute R code and return results."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty_body"})
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        code = payload.get("code", "")
        if not code.strip():
            self._send_json(400, {"error": "empty_code"})
            return

        timeout = min(payload.get("timeout", TIMEOUT), TIMEOUT)
        job_id = payload.get("job_id", str(uuid.uuid4())[:12])

        # Create job directory for outputs
        job_dir = WORKSPACE / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Write R script
        script_path = job_dir / "script.R"
        script_path.write_text(code, encoding="utf-8")

        # Wrap code to set working directory and capture outputs
        wrapper = f"""
setwd("{job_dir}")
tryCatch({{
  source("{script_path}", local = TRUE, echo = TRUE)
}}, error = function(e) {{
  cat("\\n[R ERROR]:", conditionMessage(e), "\\n", file = stderr())
}})
"""
        wrapper_path = job_dir / "wrapper.R"
        wrapper_path.write_text(wrapper, encoding="utf-8")

        start = time.time()
        try:
            result = subprocess.run(
                ["Rscript", "--vanilla", str(wrapper_path)],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(job_dir),
                env={**os.environ, "R_LIBS_USER": str(WORKSPACE / "R_libs")},
            )
            elapsed = round(time.time() - start, 2)

            # Collect output files (plots, CSVs, etc.)
            output_files = []
            for f in job_dir.iterdir():
                if f.name not in ("script.R", "wrapper.R") and f.is_file():
                    output_files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "path": str(f),
                    })

            self._send_json(200, {
                "success": result.returncode == 0,
                "job_id": job_id,
                "stdout": result.stdout[-10000:] if len(result.stdout) > 10000 else result.stdout,
                "stderr": result.stderr[-5000:] if len(result.stderr) > 5000 else result.stderr,
                "exit_code": result.returncode,
                "elapsed_seconds": elapsed,
                "output_files": output_files,
                "working_dir": str(job_dir),
            })

        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start, 2)
            self._send_json(408, {
                "success": False,
                "job_id": job_id,
                "error": f"R execution timed out after {timeout}s",
                "elapsed_seconds": elapsed,
            })
        except Exception as exc:
            self._send_json(500, {
                "success": False,
                "job_id": job_id,
                "error": str(exc)[:500],
            })


def main() -> None:
    logger.info("Starting R Workspace bridge on port %d", PORT)
    logger.info("Workspace directory: %s", WORKSPACE)
    server = HTTPServer(("0.0.0.0", PORT), RWorkspaceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
