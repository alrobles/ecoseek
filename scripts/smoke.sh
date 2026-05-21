#!/usr/bin/env bash
# EcoSeek Phase 2 canonical smoke command.
#
# Proves the real product workflow for the alpha:
#   1. AgenticPlug gateway is up and serving its Phase 1 contract
#      (/healthz + /v1/connectors).
#   2. A local model backend (Ollama) responds to a real prompt with
#      non-empty generated text.
#   3. The same ${OLLAMA_MODEL} that the EcoSeek API orchestrator is
#      configured to use is the one that answers — i.e. there is one
#      consistent local model path through the stack.
#
# Honesty notes (do not skip):
#   - AgenticPlug Phase 1 does NOT expose an OpenAI-compatible
#     /v1/chat/completions or /v1/proxy/ollama route. Step 3 below talks
#     to Ollama directly through the same loopback port the gateway and
#     orchestrator point at. That is the strongest honest demonstration
#     of the local model leg until the gateway model-routing contract
#     lands (tracked as a Phase 2 follow-up in docs/smoke-test.md).
#   - This script never reads or prints DEEPSEEK_API_KEY or any
#     environment variable whose name contains KEY/TOKEN/SECRET/PASSWORD.
#   - All probes use 127.0.0.1; nothing is exposed off-host.
#
# Usage:
#   bash scripts/smoke.sh                 # default: prompts tinyllama
#   OLLAMA_MODEL=ecocoder bash scripts/smoke.sh   # once that model is published
#   SMOKE_PROMPT="..." bash scripts/smoke.sh      # override the prompt
#   SMOKE_PULL=0 bash scripts/smoke.sh            # skip the model pull
#
# Exit codes:
#   0  all checks passed
#   1  prerequisite missing (docker, curl, .env)
#   2  AgenticPlug gateway probe failed
#   3  Ollama model unavailable (pull failed or model not present)
#   4  Ollama generate call returned empty / error
#   5  EcoSeek API not reachable (warning only — see SMOKE_REQUIRE_API)

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

export ECOSEEK_API_PORT="${ECOSEEK_API_PORT:-3000}"
export AGENTICPLUG_PORT="${AGENTICPLUG_PORT:-8080}"
export OLLAMA_PORT="${OLLAMA_PORT:-11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-tinyllama}"
export SMOKE_PROMPT="${SMOKE_PROMPT:-Reply with exactly the single word: pong.}"
export SMOKE_PULL="${SMOKE_PULL:-1}"
export SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-120}"
export SMOKE_REQUIRE_API="${SMOKE_REQUIRE_API:-0}"

step "Repo:          $REPO_ROOT"
step "Local model:   $OLLAMA_MODEL  (override: OLLAMA_MODEL=...)"
step "Gateway port:  127.0.0.1:$AGENTICPLUG_PORT"
step "Ollama port:   127.0.0.1:$OLLAMA_PORT"
step "Prompt:        $SMOKE_PROMPT"

# ── 1. AgenticPlug gateway: /healthz returns 200 ──────────────────────────
step "[1/4] AgenticPlug /healthz ..."
HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  --max-time 10 \
  "http://127.0.0.1:${AGENTICPLUG_PORT}/healthz" 2>/dev/null || true)"
HEALTH_CODE="${HEALTH_CODE:-000}"
if [ "$HEALTH_CODE" != "200" ]; then
  fail "  AgenticPlug /healthz returned ${HEALTH_CODE} (expected 200)."
  fail "  Hint: docker compose ps agenticplug ; docker compose logs agenticplug"
  fail "  See docs/smoke-test.md → Troubleshooting → 'AgenticPlug unhealthy'."
  exit 2
fi
step "      OK (200)"

# ── 2. AgenticPlug Phase 1 contract: /v1/connectors returns JSON ──────────
step "[2/4] AgenticPlug /v1/connectors ..."
CONNECTORS_BODY="$(curl -sS --max-time 10 \
  "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/connectors" || true)"
if [ -z "$CONNECTORS_BODY" ]; then
  fail "  /v1/connectors returned no body."
  exit 2
fi
# Validate JSON without printing the body (it can be empty/array/object).
if ! printf '%s' "$CONNECTORS_BODY" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print(f"bad json: {e}", file=sys.stderr)
    sys.exit(1)
sys.exit(0 if isinstance(d, (list, dict)) else 1)
' 2>/dev/null; then
  fail "  /v1/connectors did not return well-formed JSON."
  fail "  Hint: docker compose logs agenticplug"
  exit 2
fi
step "      OK (JSON body)"

# ── 3. Ollama model present (pull if missing) ─────────────────────────────
step "[3/4] Ollama model '${OLLAMA_MODEL}' ..."
TAGS_BODY="$(curl -sS --max-time 10 \
  "http://127.0.0.1:${OLLAMA_PORT}/api/tags" || true)"
if [ -z "$TAGS_BODY" ]; then
  fail "  Ollama /api/tags returned no body on 127.0.0.1:${OLLAMA_PORT}."
  fail "  Hint: docker compose ps ollama ; docker compose logs ollama"
  fail "  See docs/smoke-test.md → Troubleshooting → 'Ollama not reachable'."
  exit 3
fi

HAS_MODEL="$(printf '%s' "$TAGS_BODY" | python3 -c '
import json, sys, os
want = os.environ.get("OLLAMA_MODEL", "")
try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("no")
    sys.exit(0)
models = d.get("models", []) if isinstance(d, dict) else []
for m in models:
    name = m.get("name", "") if isinstance(m, dict) else ""
    if name == want or name.startswith(want + ":"):
        print("yes")
        sys.exit(0)
print("no")
' || echo "no")"

if [ "$HAS_MODEL" != "yes" ]; then
  if [ "$SMOKE_PULL" = "1" ]; then
    warn "  Model '${OLLAMA_MODEL}' not present. Pulling (this can take minutes)..."
    if ! docker compose exec -T ollama ollama pull "${OLLAMA_MODEL}"; then
      fail "  Failed to pull '${OLLAMA_MODEL}'."
      fail "  - For the default 'tinyllama', verify network egress on the Ollama container."
      fail "  - For 'ecocoder', confirm the model is published in the public Ollama"
      fail "    registry. EcoCoder is not yet public — keep OLLAMA_MODEL=tinyllama"
      fail "    until it is."
      fail "  See docs/smoke-test.md → Troubleshooting → 'Missing model'."
      exit 3
    fi
  else
    fail "  Model '${OLLAMA_MODEL}' not present and SMOKE_PULL=0."
    fail "  Run: docker compose exec ollama ollama pull ${OLLAMA_MODEL}"
    exit 3
  fi
fi
step "      OK ('${OLLAMA_MODEL}' available)"

# ── 4. End-to-end: prompt → local model → non-empty response ──────────────
step "[4/4] Ollama /api/generate with prompt ..."
# We POST a tiny JSON body and parse the 'response' field. stream=false so
# we get a single JSON document, not a stream of chunks.
GEN_PAYLOAD="$(python3 -c '
import json, os, sys
json.dump({
  "model": os.environ["OLLAMA_MODEL"],
  "prompt": os.environ["SMOKE_PROMPT"],
  "stream": False,
  "options": {"num_predict": 64, "temperature": 0.0}
}, sys.stdout)
')"

GEN_RAW="$(curl -sS --max-time "$SMOKE_TIMEOUT" \
  -H 'Content-Type: application/json' \
  -d "$GEN_PAYLOAD" \
  "http://127.0.0.1:${OLLAMA_PORT}/api/generate" || true)"

if [ -z "$GEN_RAW" ]; then
  fail "  /api/generate returned no body (timeout after ${SMOKE_TIMEOUT}s?)."
  exit 4
fi

GEN_TEXT="$(printf '%s' "$GEN_RAW" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(1)
txt = d.get("response", "") if isinstance(d, dict) else ""
sys.stdout.write(txt)
' || true)"

if [ -z "$GEN_TEXT" ]; then
  fail "  /api/generate returned an empty 'response' field."
  fail "  Raw body (first 400 chars): $(printf '%.400s' "$GEN_RAW")"
  fail "  Hint: try a longer prompt or a different model. Some models need warm-up."
  exit 4
fi

# Trim to first 240 chars for the user-visible step output.
PREVIEW="$(printf '%s' "$GEN_TEXT" | tr -d '\r' | head -c 240)"
step "      OK — model returned ${#GEN_TEXT} chars."
printf "${GREEN}[smoke]${NC} model says: %s\n" "$PREVIEW"

# ── 5. (Soft) EcoSeek API reachability ────────────────────────────────────
# This is informational only by default. Set SMOKE_REQUIRE_API=1 to make
# an unreachable orchestrator API a hard failure.
API_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  --max-time 10 \
  "http://127.0.0.1:${ECOSEEK_API_PORT}/health" 2>/dev/null || true)"
API_CODE="${API_CODE:-000}"
if [ "$API_CODE" = "200" ] || [ "$API_CODE" = "404" ] || [ "$API_CODE" = "307" ]; then
  step "EcoSeek API:  reachable on 127.0.0.1:${ECOSEEK_API_PORT} (status ${API_CODE})"
else
  if [ "$SMOKE_REQUIRE_API" = "1" ]; then
    fail "EcoSeek API not reachable (status ${API_CODE}). Set SMOKE_REQUIRE_API=0 to ignore."
    exit 5
  fi
  warn "EcoSeek API not reachable on 127.0.0.1:${ECOSEEK_API_PORT} (status ${API_CODE})."
  warn "  This does not block Phase 2 smoke — the gateway and local model legs"
  warn "  are the load-bearing parts. See docs/smoke-test.md for orchestrator"
  warn "  verification."
fi

echo ""
step "Phase 2 smoke: PASS"
step "  - AgenticPlug gateway is up and routing JSON."
step "  - Local model '${OLLAMA_MODEL}' produced a real response."
step "  - End-to-end Ollama path on 127.0.0.1:${OLLAMA_PORT} is consistent"
step "    with the OLLAMA_URL the EcoSeek API orchestrator is configured to use."
step ""
step "Tracked follow-up (NOT covered by this smoke):"
step "  - AgenticPlug OpenAI-compatible /v1/chat/completions (or"
step "    /v1/proxy/ollama/api/generate) route. Until that lands, model"
step "    traffic does not yet pass through the gateway's policy layer."
step "    See docs/smoke-test.md → 'Known follow-ups'."
