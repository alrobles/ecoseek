#!/usr/bin/env bash
# EcoSeek canonical smoke command (no-broker stack).
#
# Proves the real product workflow for the alpha:
#   1. Emily (Hermes gateway, :8642) is alive — /health returns JSON
#      {"status": "ok"}.
#   2. EcoSeek API (:3000) is alive — / returns 200 JSON {"status": "ok"}.
#   3. EcoAgent tool server (:8000) is alive — /v1/tools returns 200.
#   4. A real chat round-trip through the EcoSeek API (/v1/query) returns a
#      non-empty assistant reply (Emily primary → local Ollama fallback).
#
# Honesty notes (do not skip):
#   - This is the LOCAL DIY path. It does not exercise the reumanlab
#     connector, GitHub OAuth, or any KU-HPC routing — those require
#     private credentials and a different deployment, by design.
#   - Step 4 is tolerant: on failure it reports the cause honestly with
#     diagnostic hints (no LLM backend, model not pulled, Emily unhealthy)
#     instead of pretending the route was exercised.
#   - This script never reads or prints DEEPSEEK_API_KEY, EMILY_API_KEY,
#     EMILY_HERMES_KEY, or any environment variable whose name contains
#     KEY/TOKEN/SECRET/PASSWORD/SESSION.
#   - All probes use 127.0.0.1; nothing is exposed off-host.
#
# Usage:
#   bash scripts/smoke.sh                        # defaults (OLLAMA_MODEL=tinyllama)
#   EMILY_PORT=8642 bash scripts/smoke.sh        # override Emily gateway port
#   ECOSEEK_API_PORT=3000 bash scripts/smoke.sh  # override EcoSeek API port
#   ECOAGENT_PORT=8000 bash scripts/smoke.sh     # override EcoAgent port
#   SMOKE_PROMPT="..." bash scripts/smoke.sh     # override the prompt
#   OLLAMA_MODEL=ecocoder bash scripts/smoke.sh  # model used in diagnostics
#
# Exit codes:
#   0  all checks passed
#   1  prerequisite missing (docker, curl, .env)
#   2  Emily gateway /health probe failed
#   3  EcoSeek API / probe failed
#   4  EcoAgent /v1/tools probe failed
#   5  chat round-trip failed (no LLM backend / model missing / Emily unhealthy)

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

step()  { printf "${GREEN}[smoke]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[smoke]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[smoke]${NC} %s\n" "$*" >&2; }
help()  { printf "${YELLOW}[smoke]${NC}   %s\n" "$*"; }

# Print grounded diagnostics for a failed chat round-trip. Never prints
# secrets — only HTTP status codes of the live probes.
_chat_diagnostics() {
  fail ""
  fail "  Possible causes (in order of likelihood):"
  help "1. No LLM backend configured for Emily."
  help "   Set DEEPSEEK_API_KEY=<key> in .env (DeepSeek cloud), or set"
  help "   OLLAMA_BASE_URL=http://ollama:11434 in .env (local Ollama),"
  help "   then re-create Emily: docker compose up -d emily"
  help "2. Local model not pulled into Ollama:"
  help "   docker compose exec ollama ollama pull ${OLLAMA_MODEL}"
  help "3. Emily unhealthy or still starting:"
  help "   docker compose ps ; docker compose logs emily"
  help "4. Emily gateway denying chat (403):"
  help "   ensure GATEWAY_ALLOW_ALL_USERS=true in .env, then:"
  help "   docker compose up -d emily"
  EMILY_NOW="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    "http://127.0.0.1:${EMILY_PORT}/health" 2>/dev/null || true)"
  OLLAMA_NOW="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    "http://127.0.0.1:${OLLAMA_PORT}/api/tags" 2>/dev/null || true)"
  help "Current status: Emily /health=${EMILY_NOW:-000}  Ollama /api/tags=${OLLAMA_NOW:-000}"
  fail "  See docs/smoke-test.md → Troubleshooting for more."
}

# ── 0. Prerequisites ──────────────────────────────────────────────────────
for bin in curl docker; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    fail "Missing prerequisite: $bin"
    fail "  See docs/smoke-test.md → Troubleshooting → 'Missing Docker'."
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  fail "docker compose v2 plugin not found."
  fail "  See docs/smoke-test.md → Troubleshooting → 'Missing Docker'."
  exit 1
fi

if [ ! -f .env ]; then
  fail ".env not found. Run: bash setup.sh"
  exit 1
fi

# Source .env without leaking secret-named values to stdout. set -a marks
# every assigned variable as exported for the duration of the source.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

export EMILY_PORT="${EMILY_PORT:-8642}"
export ECOSEEK_API_PORT="${ECOSEEK_API_PORT:-3000}"
export ECOAGENT_PORT="${ECOAGENT_PORT:-8000}"
export OLLAMA_PORT="${OLLAMA_PORT:-11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-tinyllama}"
export SMOKE_PROMPT="${SMOKE_PROMPT:-Reply with exactly the single word: pong.}"
export SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-120}"

step "Repo:            $REPO_ROOT"
step "Emily gateway:   127.0.0.1:$EMILY_PORT   (override: EMILY_PORT=...)"
step "EcoSeek API:     127.0.0.1:$ECOSEEK_API_PORT  (override: ECOSEEK_API_PORT=...)"
step "EcoAgent tools:  127.0.0.1:$ECOAGENT_PORT/v1/tools  (override: ECOAGENT_PORT=...)"
step "Local model:     $OLLAMA_MODEL  (used in Step 4 diagnostics)"
step "Prompt:          $SMOKE_PROMPT"

# ── 1. Emily gateway: /health returns JSON status ok ──────────────────────
step "[1/4] Emily (Hermes gateway) /health ..."
EMILY_BODY="$(curl -sS --max-time 10 \
  "http://127.0.0.1:${EMILY_PORT}/health" 2>/dev/null || true)"
if [ -z "$EMILY_BODY" ]; then
  fail "  Emily /health returned no body on 127.0.0.1:${EMILY_PORT}."
  fail "  Hint: docker compose ps emily ; docker compose logs emily"
  exit 2
fi
if ! printf '%s' "$EMILY_BODY" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print(f"bad json: {e}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if isinstance(d, dict) and d.get("status") == "ok" else 1)
' 2>/dev/null; then
  fail "  Emily /health did not return JSON {\"status\": \"ok\"}."
  fail "  Hint: docker compose logs emily"
  exit 2
fi
step "      OK ({\"status\": \"ok\"})"

# ── 2. EcoSeek API: / returns 200 JSON status ok ──────────────────────────
step "[2/4] EcoSeek API / ..."
API_BODY="$(curl -sS --max-time 10 \
  "http://127.0.0.1:${ECOSEEK_API_PORT}/" 2>/dev/null || true)"
if [ -z "$API_BODY" ]; then
  fail "  EcoSeek API / returned no body on 127.0.0.1:${ECOSEEK_API_PORT}."
  fail "  Hint: docker compose ps ecoseek-api ; docker compose logs ecoseek-api"
  exit 3
fi
if ! printf '%s' "$API_BODY" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print(f"bad json: {e}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if isinstance(d, dict) and d.get("status") == "ok" else 1)
' 2>/dev/null; then
  fail "  EcoSeek API / did not return JSON {\"status\": \"ok\"}."
  fail "  Hint: docker compose logs ecoseek-api"
  exit 3
fi
step "      OK ({\"status\": \"ok\"})"

# ── 3. EcoAgent tool server: /v1/tools returns 200 ────────────────────────
step "[3/4] EcoAgent /v1/tools ..."
TOOLS_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  --max-time 10 \
  "http://127.0.0.1:${ECOAGENT_PORT}/v1/tools" 2>/dev/null || true)"
TOOLS_CODE="${TOOLS_CODE:-000}"
if [ "$TOOLS_CODE" != "200" ]; then
  fail "  EcoAgent /v1/tools returned ${TOOLS_CODE} (expected 200)."
  fail "  Hint: docker compose ps ecoagent ; docker compose logs ecoagent"
  exit 4
fi
step "      OK (200)"

# ── 4. Chat round-trip via EcoSeek API /v1/query (tolerant) ───────────────
# Product path: prompt → EcoSeek API → Emily (primary) → local Ollama.
# Note: /v1/query returns HTTP 200 with {"success": false} when the whole
# upstream chain fails, so the JSON body must be inspected, not the status.
# The body contains no secrets (results are assistant text only).
step "[4/4] EcoSeek API /v1/query chat round-trip ..."

CHAT_PAYLOAD="$(python3 -c '
import json, os, sys
json.dump({
  "text": os.environ["SMOKE_PROMPT"],
  "mode": "auto",
}, sys.stdout)
')"

# Request body goes through a tmp file so the prompt is never in argv.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
BODY_FILE="$TMP_DIR/body.json"
RESP_FILE="$TMP_DIR/resp.json"
printf '%s' "$CHAT_PAYLOAD" > "$BODY_FILE"
chmod 600 "$BODY_FILE"

CHAT_CODE="$(curl -sS --max-time "$SMOKE_TIMEOUT" \
  -X POST -H 'Content-Type: application/json' \
  --data-binary "@$BODY_FILE" -o "$RESP_FILE" \
  -w '%{http_code}' \
  "http://127.0.0.1:${ECOSEEK_API_PORT}/v1/query" 2>/dev/null || true)"
CHAT_CODE="${CHAT_CODE:-000}"

if [ "$CHAT_CODE" != "200" ]; then
  fail "  /v1/query returned HTTP ${CHAT_CODE} (expected 200)."
  _chat_diagnostics
  exit 5
fi

CHAT_OK="$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("no")
    sys.exit(0)
if not isinstance(d, dict) or not d.get("success"):
    print("no")
    sys.exit(0)
result = d.get("result") or {}
text = ""
if isinstance(result, dict):
    if result.get("text"):
        text = result["text"]
    elif result.get("raw"):
        raw = result["raw"]
        if isinstance(raw, dict) and raw.get("choices"):
            msg = raw["choices"][0].get("message") or {}
            text = msg.get("content") or ""
    elif result.get("choices"):
        msg = result["choices"][0].get("message") or {}
        text = msg.get("content") or ""
sys.stdout.write("yes" if text.strip() else "no")
' "$RESP_FILE" || echo "no")"

if [ "$CHAT_OK" != "yes" ]; then
  fail "  /v1/query returned no assistant text (success=false or empty)."
  _chat_diagnostics
  exit 5
fi

CHAT_TEXT="$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
result = (d.get("result") or {}) if isinstance(d, dict) else {}
text = ""
if isinstance(result, dict):
    if result.get("text"):
        text = result["text"]
    elif result.get("raw"):
        raw = result["raw"]
        if isinstance(raw, dict) and raw.get("choices"):
            msg = raw["choices"][0].get("message") or {}
            text = msg.get("content") or ""
    elif result.get("choices"):
        msg = result["choices"][0].get("message") or {}
        text = msg.get("content") or ""
sys.stdout.write(text or "")
' "$RESP_FILE" || true)"

PREVIEW="$(printf '%s' "$CHAT_TEXT" | tr -d '\r' | head -c 240)"
step "      OK — assistant returned ${#CHAT_TEXT} chars."
printf "${GREEN}[smoke]${NC} model says (via Emily): %s\n" "$PREVIEW"

echo ""
step "Smoke: PASS"
step "  - Emily (Hermes gateway) is up and serving /health."
step "  - EcoSeek API is up and serving /."
step "  - EcoAgent tool server is up (/v1/tools)."
step "  - A real chat round-trip via /v1/query returned assistant text"
step "    (Emily primary; local Ollama fallback) — no broker involved."