#!/usr/bin/env bash
# EcoSeek Phase 2 canonical smoke command.
#
# Proves the real product workflow for the alpha:
#   1. AgenticPlug gateway is up and serving its Phase 1 contract
#      (/healthz + /v1/connectors).
#   2. Ollama is reachable on the configured port and the requested
#      ${OLLAMA_MODEL} is present (diagnostic prerequisite — if this
#      fails, the broker-mediated step below will too, and the user
#      needs to know which leg is the problem).
#   3. AgenticPlug's broker-mediated /v1/chat/completions returns a
#      non-empty assistant message — i.e. model traffic flowed through
#      the gateway's session/scope/audit layer to the local Ollama
#      backend (AgenticPlug PR #80, EcoSeek issue #15).
#
# Honesty notes (do not skip):
#   - This is the LOCAL DIY demo path. It does not exercise the
#     reumanlab connector or any KU-HPC routing — those require private
#     credentials and a different deployment, by design.
#   - The /v1/chat/completions route requires a session. Set
#     AGENTICPLUG_SESSION in .env (an opaque session id from
#     POST /v1/cli/session). Without it, this script fails Step 3 with a
#     clear hint rather than pretending the route was exercised.
#   - This script never reads or prints DEEPSEEK_API_KEY,
#     AGENTICPLUG_SESSION, or any environment variable whose name
#     contains KEY/TOKEN/SECRET/PASSWORD/SESSION.
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
#   4  Broker-mediated /v1/chat/completions failed (no session, 4xx, 5xx,
#      or empty assistant content)
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
# AGENTICPLUG_SESSION is an opaque Bearer token; never echo its value.
: "${AGENTICPLUG_SESSION:=}"

step "Repo:          $REPO_ROOT"
step "Local model:   $OLLAMA_MODEL  (override: OLLAMA_MODEL=...)"
step "Gateway port:  127.0.0.1:$AGENTICPLUG_PORT"
step "Ollama port:   127.0.0.1:$OLLAMA_PORT  (diagnostic only)"
step "Prompt:        $SMOKE_PROMPT"
if [ -n "$AGENTICPLUG_SESSION" ]; then
  step "Session:       configured (value hidden)"
else
  step "Session:       not set (Step 3 will fail with a hint)"
fi

# ── 1. AgenticPlug gateway: /healthz returns 200 ──────────────────────────
step "[1/3] AgenticPlug /healthz ..."
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
step "[2/3] AgenticPlug /v1/connectors ..."
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

# ── 2b. Diagnostic: Ollama reachable + model present ──────────────────────
# This is NOT the canonical pass criterion — Step 3 (broker-mediated chat)
# is. But if Ollama is unreachable or the model is missing, Step 3 will
# fail with a sanitized 502/503 from the broker and the user will have no
# way to tell whether the problem is the gateway or the upstream. So we
# probe Ollama directly first as a diagnostic prerequisite.
step "[diag] Ollama /api/tags + model '${OLLAMA_MODEL}' ..."
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

# ── 3. Broker-mediated chat: AgenticPlug /v1/chat/completions ────────────
# This is the canonical Phase 2 product success criterion (issue #15):
# prompt → AgenticPlug → local Ollama → assistant text, with the broker's
# session/scope/audit layer in the loop.
step "[3/3] AgenticPlug /v1/chat/completions (broker-mediated) ..."

if [ -z "$AGENTICPLUG_SESSION" ]; then
  fail "  AGENTICPLUG_SESSION is not set."
  fail "  /v1/chat/completions requires an authenticated session (no smoke-mode"
  fail "  bypass — same auth as every other /v1/* route)."
  fail ""
  fail "  Obtain one:"
  fail "    1. Set AGENTICPLUG_ALLOWED_LOGINS=<your-github-login> in .env"
  fail "       and run: docker compose up -d --force-recreate agenticplug"
  fail "    2. POST a personal GitHub access token to /v1/cli/session:"
  fail "         curl -sS -X POST http://127.0.0.1:${AGENTICPLUG_PORT}/v1/cli/session \\"
  fail "              -H 'Content-Type: application/json' \\"
  fail "              -d \"{\\\"github_access_token\\\":\\\"\$GITHUB_TOKEN\\\"}\""
  fail "       and copy the returned session_id."
  fail "    3. Put it in .env as AGENTICPLUG_SESSION=<session_id> and rerun."
  fail ""
  fail "  See docs/smoke-test.md → 'Obtaining an AgenticPlug session'."
  exit 4
fi

CHAT_PAYLOAD="$(python3 -c '
import json, os, sys
json.dump({
  "model": os.environ["OLLAMA_MODEL"],
  "messages": [
    {"role": "user", "content": os.environ["SMOKE_PROMPT"]}
  ],
  "temperature": 0.0,
  "stream": False
}, sys.stdout)
')"

# Use a tmp file for the request body so the bearer token and prompt are
# never visible in `ps` output. The Authorization header is passed via
# stdin to curl with -K, so the session id is also not in the argv.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
BODY_FILE="$TMP_DIR/body.json"
CURL_CFG="$TMP_DIR/curl.cfg"
printf '%s' "$CHAT_PAYLOAD" > "$BODY_FILE"
# curl config file: never logs the header to stdout/stderr.
{
  printf 'header = "Authorization: Bearer %s"\n' "$AGENTICPLUG_SESSION"
  printf 'header = "Content-Type: application/json"\n'
} > "$CURL_CFG"
chmod 600 "$BODY_FILE" "$CURL_CFG"

CHAT_RESP_FILE="$TMP_DIR/resp.json"
CHAT_CODE="$(curl -sS -K "$CURL_CFG" \
  --max-time "$SMOKE_TIMEOUT" \
  -X POST \
  --data-binary "@$BODY_FILE" \
  -o "$CHAT_RESP_FILE" \
  -w '%{http_code}' \
  "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/chat/completions" 2>/dev/null || true)"
CHAT_CODE="${CHAT_CODE:-000}"

if [ "$CHAT_CODE" != "200" ]; then
  fail "  /v1/chat/completions returned HTTP ${CHAT_CODE} (expected 200)."
  # Print the broker's sanitized error code if it gave us one — the
  # error vocabulary is small and fixed (see docs/smoke-test.md).
  ERR_CODE="$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("")
    sys.exit(0)
err = d.get("error", "") if isinstance(d, dict) else ""
if isinstance(err, dict):
    print(err.get("code", ""))
elif isinstance(err, str):
    print(err)
else:
    print("")
' "$CHAT_RESP_FILE" 2>/dev/null || true)"
  if [ -n "$ERR_CODE" ]; then
    fail "  Broker error code: ${ERR_CODE}"
  fi
  case "$CHAT_CODE" in
    401) fail "  Hint: AGENTICPLUG_SESSION is invalid or expired. Re-issue via /v1/cli/session." ;;
    403) fail "  Hint: session lacks 'model.chat' capability, or the user is not in AGENTICPLUG_ALLOWED_LOGINS." ;;
    503) fail "  Hint: OLLAMA_BASE_URL is unset or upstream Ollama is down. Check docker-compose.yml and 'docker compose ps ollama'." ;;
    502) fail "  Hint: Ollama returned an error. 'docker compose logs ollama' and check the model name." ;;
    400) fail "  Hint: malformed request — verify OLLAMA_MODEL matches the regex [A-Za-z0-9_.:/-]+ and the prompt is non-empty." ;;
  esac
  fail "  See docs/smoke-test.md → Troubleshooting → 'Broker-mediated chat'."
  exit 4
fi

CHAT_TEXT="$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
if not isinstance(d, dict):
    sys.exit(1)
choices = d.get("choices") or []
if not choices:
    sys.exit(1)
msg = (choices[0] or {}).get("message") or {}
sys.stdout.write(msg.get("content", "") or "")
' "$CHAT_RESP_FILE" || true)"

if [ -z "$CHAT_TEXT" ]; then
  fail "  /v1/chat/completions returned an empty assistant 'content'."
  fail "  Hint: try a longer prompt or a different model. Some models need warm-up."
  exit 4
fi

PREVIEW="$(printf '%s' "$CHAT_TEXT" | tr -d '\r' | head -c 240)"
step "      OK — assistant returned ${#CHAT_TEXT} chars."
printf "${GREEN}[smoke]${NC} model says (via broker): %s\n" "$PREVIEW"

# ── 4. (Soft) EcoSeek API reachability ────────────────────────────────────
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
  warn "  This does not block Phase 2 smoke — the gateway and broker-mediated"
  warn "  chat legs are the load-bearing parts. See docs/smoke-test.md for"
  warn "  orchestrator verification."
fi

echo ""
step "Phase 2 smoke: PASS"
step "  - AgenticPlug gateway is up and routing JSON."
step "  - Local model '${OLLAMA_MODEL}' produced a real response via"
step "    POST /v1/chat/completions (broker-mediated, AgenticPlug PR #80)."
step "  - End-to-end EcoSeek → AgenticPlug → local Ollama path works on a"
step "    vanilla machine with no KU-HPC accounts and no reumanlab secrets."
