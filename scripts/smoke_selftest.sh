#!/usr/bin/env bash
# Self-test for scripts/smoke.sh.
#
# This does NOT spin up the full Docker stack. It stands up a tiny Python
# HTTP server that fakes AgenticPlug /healthz, /v1/connectors and Ollama
# /api/tags and /api/generate, then runs scripts/smoke.sh against those
# mock ports with SMOKE_PULL=0 (we pre-declare the model in /api/tags).
#
# Run from the repo root:
#   bash scripts/smoke_selftest.sh
#
# Useful when you want to validate the canonical smoke command without
# building containers — e.g. CI lint pass, or after editing smoke.sh.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PORT_GATEWAY="${SELFTEST_GATEWAY_PORT:-18080}"
PORT_OLLAMA="${SELFTEST_OLLAMA_PORT:-21434}"
PORT_API="${SELFTEST_API_PORT:-13000}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; [ -n "${MOCK_PID:-}" ] && kill "$MOCK_PID" 2>/dev/null || true' EXIT

cat > "$WORK/mock_server.py" <<'PYEOF'
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = int(os.environ["PORT_GATEWAY"])
OLLAMA  = int(os.environ["PORT_OLLAMA"])
API     = int(os.environ["PORT_API"])
MODEL   = os.environ.get("OLLAMA_MODEL", "tinyllama")

class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if self.path == "/v1/connectors":
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"connectors": []}).encode()); return
        self.send_response(404); self.end_headers()

class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path == "/api/tags":
            body = {"models": [{"name": f"{MODEL}:latest"}]}
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps(body).encode()); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path == "/api/generate":
            length = int(self.headers.get("Content-Length","0") or 0)
            _ = self.rfile.read(length)
            body = {"model": MODEL, "response": "pong", "done": True}
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps(body).encode()); return
        self.send_response(404); self.end_headers()

class Api(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path in ("/health", "/"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(404); self.end_headers()

import threading
servers = [
    ThreadingHTTPServer(("127.0.0.1", GATEWAY), Gateway),
    ThreadingHTTPServer(("127.0.0.1", OLLAMA), Ollama),
    ThreadingHTTPServer(("127.0.0.1", API), Api),
]
for s in servers:
    threading.Thread(target=s.serve_forever, daemon=True).start()
print("ready", flush=True)
import time
while True:
    time.sleep(3600)
PYEOF

# Write a temporary .env-like file at a sibling path so smoke.sh sources it.
BACKUP=""
if [ -f .env ]; then
  BACKUP=".env.selftest_backup.$$"
  cp .env "$BACKUP"
fi
cat > .env <<EOF
ECOSEEK_API_PORT=${PORT_API}
AGENTICPLUG_PORT=${PORT_GATEWAY}
OLLAMA_PORT=${PORT_OLLAMA}
OLLAMA_MODEL=tinyllama
EOF
chmod 600 .env

restore() {
  rm -f .env
  if [ -n "$BACKUP" ]; then mv "$BACKUP" .env; fi
}
trap 'restore; rm -rf "$WORK"; [ -n "${MOCK_PID:-}" ] && kill "$MOCK_PID" 2>/dev/null || true' EXIT

PORT_GATEWAY="$PORT_GATEWAY" PORT_OLLAMA="$PORT_OLLAMA" PORT_API="$PORT_API" \
  OLLAMA_MODEL=tinyllama \
  python3 "$WORK/mock_server.py" > "$WORK/server.log" 2>&1 &
MOCK_PID=$!

# Wait for "ready"
for i in $(seq 1 30); do
  if grep -q ready "$WORK/server.log" 2>/dev/null; then break; fi
  sleep 0.2
done

# Stub docker compose so smoke.sh's healthcheck for `docker compose version`
# passes. Smoke.sh will not actually exec `docker compose` because
# SMOKE_PULL=0 makes it skip the pull step (the model is in /api/tags).
STUB_DIR="$WORK/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/docker" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
  echo "Docker Compose version vMOCK"
  exit 0
fi
echo "docker stub: unexpected args: $*" >&2
exit 0
STUB
chmod +x "$STUB_DIR/docker"

if SMOKE_PULL=0 \
   PATH="$STUB_DIR:$PATH" \
   bash scripts/smoke.sh; then
  echo "[selftest] PASS"
  exit 0
else
  rc=$?
  echo "[selftest] FAIL (smoke.sh exited $rc)" >&2
  echo "[selftest] mock server log:" >&2
  cat "$WORK/server.log" >&2 || true
  exit "$rc"
fi
