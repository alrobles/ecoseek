#!/usr/bin/env bash
# Docker-free selftest for scripts/remote-smoke.sh.
#
# Stands up a tiny Python HTTP server that fakes the AgenticPlug broker
# (/healthz, /v1/tasks) and a local "edge" endpoint (/healthz). The mock
# /v1/tasks endpoint validates that:
#   - the script sends a Bearer Authorization header (token-safe path),
#   - it does NOT include the token in the URL or in argv (we inspect a
#     marker file written by the mock to see how the request arrived),
#   - the script handles the documented "AgenticPlug #83 not ready
#     yet" responses (404, 501, and 200 + capability_not_ready) without
#     a hard failure when SMOKE_REMOTE_STRICT is 0,
#   - the script does treat those as a hard failure when
#     SMOKE_REMOTE_STRICT=1.
#
# Run from the repo root:
#   bash scripts/remote_smoke_selftest.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PORT_GATEWAY="${SELFTEST_REMOTE_GATEWAY_PORT:-18091}"
PORT_EDGE="${SELFTEST_REMOTE_EDGE_PORT:-18092}"
SELFTEST_SESSION="selftest-remote-0123456789abcdef0123456789abcdef"

WORK="$(mktemp -d)"
MOCK_PID=""
cleanup() {
  if [ -n "$MOCK_PID" ]; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# ── Mock server ──────────────────────────────────────────────────────────
# MODE controls the broker's response to /v1/tasks:
#   not_ready_404   — always returns 404
#   not_ready_501   — always returns 501
#   not_ready_body  — returns 200 with {"error":{"code":"capability_not_ready"}}
#   ready           — returns 200 with a minimal success envelope
#   mixed           — first capability is ready, others are not_ready_body
#   connector_error — returns 200 with {"error":{"code":"ssh_failed"}}
#   bad_session     — returns 401 if Bearer missing or empty
cat > "$WORK/mock.py" <<'PYEOF'
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = int(os.environ["PORT_GATEWAY"])
EDGE    = int(os.environ["PORT_EDGE"])
MODE    = os.environ.get("MODE", "not_ready_body")
MARKER  = os.environ.get("MARKER", "/tmp/remote_smoke_marker")

CALL_COUNT = {"v1_tasks": 0}

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
        self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path != "/v1/tasks":
            self.send_response(404); self.end_headers(); return

        # Record what we observed — used by the selftest to verify
        # token-safe request construction.
        auth = self.headers.get("Authorization", "")
        has_bearer = auth.startswith("Bearer ") and len(auth) > len("Bearer ")
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except Exception:
            body = None
        CALL_COUNT["v1_tasks"] += 1
        with open(MARKER, "a") as f:
            f.write(json.dumps({
                "has_bearer": has_bearer,
                "url_path": self.path,
                "body": body,
                "auth_in_url": "?" in self.path or "&" in self.path,
            }) + "\n")

        if MODE == "bad_session" and not has_bearer:
            _json(self, 401, {"error": {"code": "no_session"}})
            return
        if not has_bearer:
            # Even in other modes, require a bearer — the script is
            # supposed to send one.
            _json(self, 401, {"error": {"code": "no_session"}})
            return

        cap = ""
        if isinstance(body, dict):
            cap = body.get("capability", "") or ""

        if MODE == "not_ready_404":
            self.send_response(404); self.end_headers(); return
        if MODE == "not_ready_501":
            self.send_response(501); self.end_headers(); return
        if MODE == "not_ready_body":
            _json(self, 200, {"error": {"code": "capability_not_ready",
                                        "message": "waiting for #83"}})
            return
        if MODE == "ready":
            _json(self, 200, {"connector": "reumanlab", "capability": cap,
                              "result": {"ok": True}})
            return
        if MODE == "mixed":
            if cap == "remote.health":
                _json(self, 200, {"connector": "reumanlab", "capability": cap,
                                  "result": {"ok": True}})
            else:
                _json(self, 200, {"error": {"code": "capability_not_ready"}})
            return
        if MODE == "connector_error":
            _json(self, 200, {"error": {"code": "ssh_failed",
                                        "message": "ssh to hpc failed"}})
            return
        # Default: behave like not_ready_body
        _json(self, 200, {"error": {"code": "capability_not_ready"}})

class Edge(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(404); self.end_headers()

import threading
servers = [
    ThreadingHTTPServer(("127.0.0.1", GATEWAY), Gateway),
    ThreadingHTTPServer(("127.0.0.1", EDGE), Edge),
]
for s in servers:
    threading.Thread(target=s.serve_forever, daemon=True).start()
print("ready", flush=True)
import time
while True:
    time.sleep(3600)
PYEOF

start_mock() {
  local mode="$1"
  if [ -n "$MOCK_PID" ]; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
    MOCK_PID=""
  fi
  : > "$WORK/marker"
  MODE="$mode" MARKER="$WORK/marker" \
    PORT_GATEWAY="$PORT_GATEWAY" PORT_EDGE="$PORT_EDGE" \
    python3 "$WORK/mock.py" > "$WORK/server.log" 2>&1 &
  MOCK_PID=$!
  for _ in $(seq 1 30); do
    if grep -q ready "$WORK/server.log" 2>/dev/null; then return 0; fi
    sleep 0.2
  done
  echo "[selftest] mock did not start" >&2
  cat "$WORK/server.log" >&2 || true
  return 1
}

# Backup .env to avoid clobbering caller state.
BACKUP=""
if [ -f .env ]; then
  BACKUP=".env.remote_selftest_backup.$$"
  cp .env "$BACKUP"
fi
restore() {
  rm -f .env
  if [ -n "$BACKUP" ]; then mv "$BACKUP" .env; fi
}
# Re-install cleanup so we also restore .env on exit.
trap 'restore; cleanup' EXIT

# A minimal .env so remote-smoke.sh has something to source. We do NOT
# put the session here — we pass it via env to exercise the env-only
# path (CI runners commonly do this).
cat > .env <<EOF
AGENTICPLUG_PORT=${PORT_GATEWAY}
EOF
chmod 600 .env

EDGE_URL="http://127.0.0.1:${PORT_EDGE}/healthz"
BROKER_URL="http://127.0.0.1:${PORT_GATEWAY}"

run_case() {
  local name="$1" expected_rc="$2" mode="$3"
  shift 3
  start_mock "$mode" || return 1
  local logfile="$WORK/${name}.log"
  set +e
  AGENTICPLUG_URL="$BROKER_URL" \
  AGENTICPLUG_SESSION="$SELFTEST_SESSION" \
  ECOSEEK_REMOTE_HEALTH_URL="$EDGE_URL" \
  ECOSEEK_REMOTE_CONNECTOR="reumanlab" \
  "$@" \
    bash scripts/remote-smoke.sh > "$logfile" 2>&1
  local rc=$?
  set -e
  if [ "$rc" != "$expected_rc" ]; then
    echo "[selftest] FAIL — ${name}: expected exit ${expected_rc}, got ${rc}" >&2
    echo "[selftest] script output:" >&2
    cat "$logfile" >&2 || true
    return 1
  fi
  echo "[selftest] ${name}: OK (exit ${rc})"
  return 0
}

verify_token_safety() {
  # No marker line may have auth_in_url=true, and every recorded call
  # must have has_bearer=true (the script must always send the header).
  python3 - "$WORK/marker" <<'PY'
import json, sys
path = sys.argv[1]
ok = True
n = 0
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            d = json.loads(line)
            if d.get("auth_in_url"):
                print(f"FAIL: token appeared in URL: {d['url_path']}", file=sys.stderr)
                ok = False
            if not d.get("has_bearer"):
                print("FAIL: request missing Bearer header", file=sys.stderr)
                ok = False
except FileNotFoundError:
    print("FAIL: no marker file", file=sys.stderr)
    sys.exit(1)
if n == 0:
    print("FAIL: marker file is empty (no v1/tasks call observed)", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if ok else 1)
PY
}

verify_no_secret_leak() {
  local log="$1"
  if grep -F "$SELFTEST_SESSION" "$log" >/dev/null 2>&1; then
    echo "[selftest] FAIL — session token leaked into script output: $log" >&2
    return 1
  fi
}

echo "[selftest] case 1: missing session → expected exit 4"
start_mock "not_ready_body"
set +e
AGENTICPLUG_URL="$BROKER_URL" \
ECOSEEK_REMOTE_HEALTH_URL="$EDGE_URL" \
AGENTICPLUG_SESSION="" \
  bash scripts/remote-smoke.sh > "$WORK/case1.log" 2>&1
rc1=$?
set -e
if [ "$rc1" -ne 4 ]; then
  echo "[selftest] FAIL — case 1 expected exit 4, got $rc1" >&2
  cat "$WORK/case1.log" >&2; exit 1
fi
echo "[selftest] case 1: OK (exit 4)"

echo "[selftest] case 2: #83 not ready (404) → expected exit 0"
run_case "case2_404" 0 "not_ready_404"
verify_token_safety
verify_no_secret_leak "$WORK/case2_404.log"

echo "[selftest] case 3: #83 not ready (501) → expected exit 0"
run_case "case3_501" 0 "not_ready_501"

echo "[selftest] case 4: #83 not ready (200 capability_not_ready) → expected exit 0"
run_case "case4_body" 0 "not_ready_body"
# Confirm the success message mentions 'waiting for AgenticPlug #83'.
if ! grep -F "waiting for AgenticPlug #83" "$WORK/case4_body.log" >/dev/null; then
  echo "[selftest] FAIL — case 4 missing '#83' guidance in output" >&2
  cat "$WORK/case4_body.log" >&2; exit 1
fi

echo "[selftest] case 5: strict mode + #83 not ready → expected exit 5"
run_case "case5_strict" 5 "not_ready_body" env SMOKE_REMOTE_STRICT=1

echo "[selftest] case 6: ready → expected exit 0 with PASS"
run_case "case6_ready" 0 "ready"
if ! grep -F "Phase 3 remote smoke: PASS" "$WORK/case6_ready.log" >/dev/null; then
  echo "[selftest] FAIL — case 6 missing PASS in output" >&2
  cat "$WORK/case6_ready.log" >&2; exit 1
fi

echo "[selftest] case 7: mixed (some ready, some not) → expected exit 0 with PARTIAL"
run_case "case7_mixed" 0 "mixed"
if ! grep -F "PARTIAL" "$WORK/case7_mixed.log" >/dev/null; then
  echo "[selftest] FAIL — case 7 missing PARTIAL in output" >&2
  cat "$WORK/case7_mixed.log" >&2; exit 1
fi

echo "[selftest] case 8: connector_error (real failure) → expected exit 6"
run_case "case8_connector_error" 6 "connector_error"

echo ""
echo "[selftest] PASS — all cases behaved as documented."
