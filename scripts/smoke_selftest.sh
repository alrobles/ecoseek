#!/usr/bin/env bash
# Self-test for scripts/smoke.sh.
#
# This does NOT spin up the full Docker stack. It stands up a tiny Python
# HTTP server that fakes AgenticPlug /healthz, /v1/connectors,
# /v1/chat/completions (the new broker-mediated route from AgenticPlug
# PR #80), and Ollama /api/tags, then runs scripts/smoke.sh against
# those mock ports with SMOKE_PULL=0 (we pre-declare the model in
# /api/tags). The mock /v1/chat/completions enforces a Bearer
# Authorization header so the selftest exercises the new auth path,
# not a fake unauthenticated bypass.
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
# Fixed selftest session id — the mock gateway accepts any non-empty
# Bearer, but we use a real-looking opaque value so a future change that
# starts validating the token format will surface immediately.
SELFTEST_SESSION="selftest-session-0123456789abcdef0123456789abcdef"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; [ -n "${MOCK_PID:-}" ] && kill "$MOCK_PID" 2>/dev/null || true' EXIT

cat > "$WORK/mock_server.py" <<'PYEOF'
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = int(os.environ["PORT_GATEWAY"])
OLLAMA  = int(os.environ["PORT_OLLAMA"])
API     = int(os.environ["PORT_API"])
MODEL   = os.environ.get("OLLAMA_MODEL", "tinyllama")

def _json(self, code, body):
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.end_headers()
    self.wfile.write(json.dumps(body).encode())

class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if self.path == "/v1/connectors":
            _json(self, 200, {"connectors": []}); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path == "/v1/chat/completions":
            # Enforce the same auth surface the real broker uses: a
            # Bearer token is required. We intentionally do NOT verify
            # the token contents — the broker's session validation lives
            # in its own test suite; here we are proving smoke.sh sends
            # the header at all and parses the OpenAI-shape response.
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or len(auth) <= len("Bearer "):
                _json(self, 401, {"error": "no_session"}); return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except Exception:
                _json(self, 400, {"error": {"code": "invalid_json", "message": "bad json"}}); return
            # Minimal shape check so we notice if smoke.sh stops sending
            # the OpenAI envelope.
            if not isinstance(body, dict) or "model" not in body or "messages" not in body:
                _json(self, 400, {"error": {"code": "invalid_request_body", "message": "bad shape"}}); return
            if body.get("stream") is True:
                _json(self, 400, {"error": {"code": "streaming_not_supported", "message": "no stream"}}); return
            # Emit a minimal valid OpenAI-shape response.
            _json(self, 200, {
                "id": "chatcmpl-selftest",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
            return
        self.send_response(404); self.end_headers()

class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path == "/api/tags":
            _json(self, 200, {"models": [{"name": f"{MODEL}:latest"}]}); return
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
AGENTICPLUG_SESSION=${SELFTEST_SESSION}
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

# ── Sub-test 1: missing AGENTICPLUG_SESSION must fail Step 3 cleanly ─────
echo "[selftest] case 1: missing AGENTICPLUG_SESSION → expected fail (exit 4)"
cp .env "$WORK/env.backup"
sed -i.bak 's/^AGENTICPLUG_SESSION=.*/AGENTICPLUG_SESSION=/' .env
set +e
SMOKE_PULL=0 PATH="$STUB_DIR:$PATH" bash scripts/smoke.sh > "$WORK/case1.log" 2>&1
rc1=$?
set -e
cp "$WORK/env.backup" .env
if [ "$rc1" -ne 4 ]; then
  echo "[selftest] FAIL — case 1 expected exit 4, got $rc1" >&2
  cat "$WORK/case1.log" >&2
  exit 1
fi
echo "[selftest] case 1: OK (exit 4 as expected)"

# ── Sub-test 2: happy path with a session → PASS ─────────────────────────
echo "[selftest] case 2: with AGENTICPLUG_SESSION → expected PASS"
if SMOKE_PULL=0 \
   PATH="$STUB_DIR:$PATH" \
   bash scripts/smoke.sh; then
  echo "[selftest] case 2: OK (PASS)"
  echo "[selftest] PASS"
  exit 0
else
  rc=$?
  echo "[selftest] FAIL (smoke.sh exited $rc)" >&2
  echo "[selftest] mock server log:" >&2
  cat "$WORK/server.log" >&2 || true
  exit "$rc"
fi
