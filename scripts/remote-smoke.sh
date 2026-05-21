#!/usr/bin/env bash
# EcoSeek Phase 3 remote smoke command (issue #22).
#
# Verifies the reumanlab / KU-HPC remote path that EcoSeek will use once
# AgenticPlug issue #83 (read-only KU-HPC capabilities) lands. This script
# is a SCAFFOLD: it proves that the local environment can reach the
# documented remote surfaces and that the request construction is
# token-safe, but it does not require — and does not pretend to require —
# the #83 capabilities to be implemented yet. When the broker reports the
# capabilities are missing, this script reports "waiting for AgenticPlug
# #83" and exits with a documented non-zero code so callers can tell the
# difference between "real failure" and "expected, not ready yet".
#
# Honesty notes (do not skip):
#   - This is the REMOTE path. The local DIY smoke is scripts/smoke.sh;
#     this script is purely additive and does not modify that workflow.
#   - This script never SSHes anywhere. All remote calls go through
#     AgenticPlug HTTPS. SSH from EcoSeek to KU-HPC is out of scope and
#     intentionally disallowed — the reumanlab connector is the only
#     component permitted to hold an HPC SSH key.
#   - No KU-HPC password or private key is read or required.
#   - This script never prints AGENTICPLUG_SESSION, CONNECTOR_TOKEN, or
#     any environment variable whose name contains KEY/TOKEN/SECRET/
#     PASSWORD/SESSION. Bearer headers are passed via curl `-K` config
#     files with mode 600 so they never appear in `ps` output.
#
# Environment variables (all optional unless noted):
#   AGENTICPLUG_URL          Base URL for the AgenticPlug broker.
#                            Default: http://127.0.0.1:${AGENTICPLUG_PORT:-8080}
#   AGENTICPLUG_PORT         Port for local broker (default 8080).
#   AGENTICPLUG_SESSION      Opaque session id (Bearer). Required for any
#                            /v1/tasks probe; without it, the script
#                            reports "session missing" and exits 4.
#   ECOSEEK_REMOTE_HEALTH_URL Optional Cloudflare-backed health URL for
#                            the reumanlab edge. If unset the script
#                            uses https://reumanlab.ecoseek.org/healthz.
#                            Set to "" (empty) to skip this leg.
#   ECOSEEK_REMOTE_CONNECTOR Connector id the broker should dispatch to
#                            (default: reumanlab).
#   ECOSEEK_REMOTE_TIMEOUT   Per-request timeout in seconds (default 15).
#   SMOKE_REMOTE_STRICT      When 1, an "AgenticPlug #83 not ready"
#                            outcome is treated as a hard failure. The
#                            default (0) is the safer choice while #83
#                            is still in flight.
#
# Exit codes:
#   0  all required legs passed; capabilities either present or
#      explicitly "not ready yet" with SMOKE_REMOTE_STRICT=0
#   1  prerequisite missing (curl, python3, .env)
#   2  AgenticPlug broker /healthz probe failed
#   3  Cloudflare/edge health probe failed (only if explicitly configured)
#   4  AGENTICPLUG_SESSION missing or task dispatch HTTP-level failure
#   5  AgenticPlug #83 capabilities not ready AND SMOKE_REMOTE_STRICT=1
#   6  KU-HPC leg reported a clear failure from the connector

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

step()  { printf "${GREEN}[remote-smoke]${NC} %s\n" "$*"; }
info()  { printf "${BLUE}[remote-smoke]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[remote-smoke]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[remote-smoke]${NC} %s\n" "$*" >&2; }

# ── 0. Prerequisites ──────────────────────────────────────────────────────
for bin in curl python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    fail "Missing prerequisite: $bin"
    fail "  See docs/remote-smoke.md → Troubleshooting → 'Missing prerequisites'."
    exit 1
  fi
done

# .env is optional for remote-smoke: a CI runner may pass everything via
# env vars directly. Source it only if present, and never echo values
# named like secrets.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export AGENTICPLUG_PORT="${AGENTICPLUG_PORT:-8080}"
export AGENTICPLUG_URL="${AGENTICPLUG_URL:-http://127.0.0.1:${AGENTICPLUG_PORT}}"
# Default to the documented Cloudflare-fronted reumanlab edge. Callers
# can pin to a different host (lab-internal staging, local mock) by
# exporting ECOSEEK_REMOTE_HEALTH_URL, or skip the edge leg with "".
if [ -z "${ECOSEEK_REMOTE_HEALTH_URL+x}" ]; then
  ECOSEEK_REMOTE_HEALTH_URL="https://reumanlab.ecoseek.org/healthz"
fi
export ECOSEEK_REMOTE_HEALTH_URL
export ECOSEEK_REMOTE_CONNECTOR="${ECOSEEK_REMOTE_CONNECTOR:-reumanlab}"
export ECOSEEK_REMOTE_TIMEOUT="${ECOSEEK_REMOTE_TIMEOUT:-15}"
export SMOKE_REMOTE_STRICT="${SMOKE_REMOTE_STRICT:-0}"
: "${AGENTICPLUG_SESSION:=}"

step "Repo:          $REPO_ROOT"
step "Broker:        $AGENTICPLUG_URL"
step "Connector id:  $ECOSEEK_REMOTE_CONNECTOR"
if [ -n "$ECOSEEK_REMOTE_HEALTH_URL" ]; then
  step "Edge health:   $ECOSEEK_REMOTE_HEALTH_URL"
else
  step "Edge health:   (skipped — ECOSEEK_REMOTE_HEALTH_URL=\"\")"
fi
if [ -n "$AGENTICPLUG_SESSION" ]; then
  step "Session:       configured (value hidden)"
else
  step "Session:       not set (Step 3 will report a hint and exit 4)"
fi
if [ "$SMOKE_REMOTE_STRICT" = "1" ]; then
  step "Strict mode:   ON  — '#83 not ready' will be a hard failure"
else
  step "Strict mode:   OFF — '#83 not ready' is reported but non-fatal"
fi

# ── Helpers ──────────────────────────────────────────────────────────────
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
chmod 700 "$TMP_DIR"

# write_curl_cfg <session> <out_path>
# Writes an Authorization header to a curl config file with mode 600.
# Never echoes the token to stdout, stderr, or the process argv.
write_curl_cfg() {
  local session="$1" out="$2"
  : > "$out"
  chmod 600 "$out"
  {
    printf 'header = "Authorization: Bearer %s"\n' "$session"
    printf 'header = "Content-Type: application/json"\n'
    printf 'header = "Accept: application/json"\n'
  } > "$out"
}

# Validate that a payload string is JSON-parseable to an object. Used
# defensively — the broker should return JSON, but we never assume.
is_json_object() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(d, (dict, list)) else 1)
PY
}

# ── 1. Local AgenticPlug broker /healthz ──────────────────────────────────
step "[1/4] AgenticPlug broker /healthz ..."
HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  --max-time "$ECOSEEK_REMOTE_TIMEOUT" \
  "${AGENTICPLUG_URL%/}/healthz" 2>/dev/null || true)"
HEALTH_CODE="${HEALTH_CODE:-000}"
if [ "$HEALTH_CODE" != "200" ]; then
  fail "  Broker /healthz returned ${HEALTH_CODE} (expected 200)."
  fail "  Hint: is AgenticPlug running? See docs/remote-smoke.md."
  exit 2
fi
step "      OK (200)"

# ── 2. Optional Cloudflare/edge health URL ────────────────────────────────
if [ -n "$ECOSEEK_REMOTE_HEALTH_URL" ]; then
  step "[2/4] Edge health (${ECOSEEK_REMOTE_HEALTH_URL}) ..."
  # Refuse to probe non-HTTPS public hosts. Loopback http is allowed for
  # local mocks.
  case "$ECOSEEK_REMOTE_HEALTH_URL" in
    https://*) ;;
    http://127.0.0.1*|http://localhost*) ;;
    *)
      fail "  ECOSEEK_REMOTE_HEALTH_URL must be https:// or loopback. Got: $ECOSEEK_REMOTE_HEALTH_URL"
      exit 3
      ;;
  esac
  EDGE_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    --max-time "$ECOSEEK_REMOTE_TIMEOUT" \
    "$ECOSEEK_REMOTE_HEALTH_URL" 2>/dev/null || true)"
  EDGE_CODE="${EDGE_CODE:-000}"
  if [ "$EDGE_CODE" != "200" ]; then
    fail "  Edge health returned ${EDGE_CODE} (expected 200)."
    fail "  Hint: the reumanlab Cloudflare tunnel may be down, or the"
    fail "  temporary health server has been swapped for the real"
    fail "  connector before #83 landed. See docs/remote-smoke.md."
    exit 3
  fi
  step "      OK (200)"
else
  info "[2/4] Edge health probe skipped (empty ECOSEEK_REMOTE_HEALTH_URL)."
fi

# ── 3. Broker-mediated /v1/tasks dispatch ────────────────────────────────
# Phase 3 capabilities live behind AgenticPlug #83. Until that lands the
# broker is expected to return one of:
#   - 404 / 501            — capability not implemented
#   - 200 with an error    body of shape {"error": {"code":
#     "capability_not_ready"...}}
# Either should be reported as "waiting for #83", not a hard failure
# (unless SMOKE_REMOTE_STRICT=1).
step "[3/4] AgenticPlug /v1/tasks dispatch (remote.health, hpc.status, hpc.queue) ..."

if [ -z "$AGENTICPLUG_SESSION" ]; then
  fail "  AGENTICPLUG_SESSION is not set."
  fail "  /v1/tasks requires an authenticated session — there is no smoke-mode bypass."
  fail "  See docs/remote-smoke.md → 'Obtaining a session' for instructions."
  exit 4
fi

CURL_CFG="$TMP_DIR/curl.cfg"
write_curl_cfg "$AGENTICPLUG_SESSION" "$CURL_CFG"

# A response from the broker is one of three categories:
#   ready    — 200 + well-formed task envelope (capability succeeded
#              from the broker's perspective; KU-HPC errors surface in
#              category 'connector_error' below)
#   not_yet  — 404, 501, or a 200 whose body carries an error code
#              matching capability_not_ready / capability_not_found /
#              not_implemented / no_such_connector
#   connector_error — 200 + body whose 'connector_status' or
#              'error.code' indicates the connector reported a real
#              failure (e.g. ssh_failed, hpc_unreachable). Always a
#              hard failure regardless of strict mode — the connector
#              is supposed to be live.
#   http_error      — any other non-200, non-404, non-501 response
classify_response() {
  python3 - "$1" "$2" <<'PY'
import json, sys
http_code = sys.argv[1]
path = sys.argv[2]

NOT_YET_ERRORS = {
    "capability_not_ready",
    "capability_not_found",
    "capability_disabled",
    "not_implemented",
    "no_such_connector",
    "connector_not_ready",
    "unknown_capability",
}
CONNECTOR_ERRORS = {
    "ssh_failed",
    "hpc_unreachable",
    "command_timeout",
    "permission_denied",
}

if http_code in ("404", "501"):
    print("not_yet")
    sys.exit(0)

try:
    with open(path, "r") as f:
        body = json.load(f)
except Exception:
    if http_code == "200":
        print("http_error")
    else:
        print("http_error")
    sys.exit(0)

def err_code(b):
    if not isinstance(b, dict):
        return ""
    err = b.get("error")
    if isinstance(err, dict):
        return err.get("code", "") or ""
    if isinstance(err, str):
        return err
    return ""

code = err_code(body)
if http_code == "200":
    if code in NOT_YET_ERRORS:
        print("not_yet")
    elif code in CONNECTOR_ERRORS:
        print("connector_error")
    elif code:
        print("http_error")
    else:
        print("ready")
elif http_code in ("400", "403"):
    if code in NOT_YET_ERRORS:
        print("not_yet")
    else:
        print("http_error")
else:
    print("http_error")
PY
}

# Build a /v1/tasks payload. Keep the schema minimal — the contract is
# documented in AgenticPlug's kuhpc-connector-contract.md and we want
# the scaffold to not over-specify fields that #83 may refine.
build_payload() {
  local capability="$1"
  python3 - "$capability" "$ECOSEEK_REMOTE_CONNECTOR" <<'PY'
import json, sys
cap = sys.argv[1]
connector = sys.argv[2]
json.dump({
    "connector": connector,
    "capability": cap,
    "arguments": {},
}, sys.stdout)
PY
}

CAPABILITIES=("remote.health" "hpc.status" "hpc.queue")
ANY_NOT_YET=0
ANY_READY=0
ANY_CONNECTOR_ERROR=0

for CAP in "${CAPABILITIES[@]}"; do
  BODY_FILE="$TMP_DIR/body_${CAP//./_}.json"
  RESP_FILE="$TMP_DIR/resp_${CAP//./_}.json"
  build_payload "$CAP" > "$BODY_FILE"
  chmod 600 "$BODY_FILE"

  HTTP_CODE="$(curl -sS -K "$CURL_CFG" \
    --max-time "$ECOSEEK_REMOTE_TIMEOUT" \
    -X POST \
    --data-binary "@$BODY_FILE" \
    -o "$RESP_FILE" \
    -w '%{http_code}' \
    "${AGENTICPLUG_URL%/}/v1/tasks" 2>/dev/null || true)"
  HTTP_CODE="${HTTP_CODE:-000}"

  CATEGORY="$(classify_response "$HTTP_CODE" "$RESP_FILE" 2>/dev/null || echo http_error)"

  case "$CATEGORY" in
    ready)
      step "      ${CAP}: READY (HTTP ${HTTP_CODE})"
      ANY_READY=1
      ;;
    not_yet)
      warn "      ${CAP}: waiting for AgenticPlug #83 (HTTP ${HTTP_CODE})"
      ANY_NOT_YET=1
      ;;
    connector_error)
      fail "      ${CAP}: connector reported a failure (HTTP ${HTTP_CODE})."
      fail "        Inspect connector logs on reumanlab. See docs/remote-smoke.md."
      ANY_CONNECTOR_ERROR=1
      ;;
    http_error|*)
      fail "      ${CAP}: HTTP ${HTTP_CODE} — unexpected response shape."
      case "$HTTP_CODE" in
        401) fail "        Hint: session invalid or expired. Re-issue via /v1/cli/session." ;;
        403) fail "        Hint: session lacks the required scope for ${CAP}." ;;
        000) fail "        Hint: broker unreachable mid-run (network blip?)." ;;
      esac
      ANY_CONNECTOR_ERROR=1
      ;;
  esac
done

if [ "$ANY_CONNECTOR_ERROR" = "1" ]; then
  fail "One or more capabilities returned a real failure. See messages above."
  exit 6
fi

# ── 4. Outcome ───────────────────────────────────────────────────────────
echo ""
if [ "$ANY_NOT_YET" = "1" ] && [ "$ANY_READY" = "0" ]; then
  if [ "$SMOKE_REMOTE_STRICT" = "1" ]; then
    fail "[4/4] Phase 3 remote smoke: NOT READY"
    fail "  AgenticPlug #83 capabilities are not yet wired."
    fail "  Re-run without SMOKE_REMOTE_STRICT=1 to treat this as expected."
    exit 5
  fi
  warn "[4/4] Phase 3 remote smoke: SCAFFOLD OK — waiting for AgenticPlug #83"
  warn "  Broker /healthz, edge /healthz, and request construction all"
  warn "  verified. Capability dispatch returned 'not ready yet' for all"
  warn "  probed capabilities — this is the expected state until"
  warn "  https://github.com/alrobles/agenticplug/issues/83 lands."
  exit 0
fi

if [ "$ANY_NOT_YET" = "1" ]; then
  warn "[4/4] Phase 3 remote smoke: PARTIAL"
  warn "  Some capabilities are READY, others are waiting for #83."
  warn "  Re-run after #83 merges to confirm full readiness."
  exit 0
fi

step "[4/4] Phase 3 remote smoke: PASS"
step "  Broker, edge, and all probed capabilities returned READY."
step "  AgenticPlug #83 looks fully wired for ${ECOSEEK_REMOTE_CONNECTOR}."
