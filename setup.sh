#!/usr/bin/env bash
# EcoSeek one-command setup.
# Works on Linux, macOS, and Windows (WSL).
#
# Usage:
#   bash setup.sh                            # interactive, prompts for DeepSeek key
#   DEEPSEEK_API_KEY=sk-xxx bash setup.sh    # non-interactive (BYOK)
#   CI=1 bash setup.sh                        # non-interactive (keep .env on conflict)
#
# What it does:
#   1. Checks prerequisites (git, docker, docker compose v2)
#   2. Generates / updates .env with all the variables docker-compose.yml expects
#   3. Clones dependency repos into .repos/ (uses YOUR git auth)
#
# After this script, start the stack with:
#   docker compose up -d
#
# No Node.js, Python, or npm required on the host — just Git + Docker.

set -euo pipefail

# Restrict file mode for everything we create (.env, .repos/...).
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}[ecoseek]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[ecoseek]${NC} %s\n" "$*"; }
error() { printf "${RED}[ecoseek]${NC} %s\n" "$*" >&2; }

# Return 0 if the variable NAME (not value) looks like a secret marker.
is_secret_name() {
  case "$1" in
    *KEY*|*TOKEN*|*SECRET*|*PASSWORD*) return 0 ;;
    *) return 1 ;;
  esac
}

# Print a single "NAME: VALUE" summary line, redacting the value when the
# name looks like a secret marker. All status output that names a variable
# routes through this helper so a future edit that adds a new secret
# variable cannot accidentally leak its value.
print_var() {
  local name="$1"
  local value="${2:-}"
  if is_secret_name "$name"; then
    if [ -n "$value" ]; then
      info "  $name: configured (value hidden)"
    else
      info "  $name: not set"
    fi
  else
    info "  $name: $value"
  fi
}

# ── Prerequisites ─────────────────────────────────────────────────────────
check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "Required: $1 is not installed."
    error "$2"
    exit 1
  fi
}

check_cmd git    "Install git: https://git-scm.com/downloads"
check_cmd docker "Install Docker Desktop: https://docs.docker.com/get-docker/"

if ! docker compose version &>/dev/null; then
  error "docker compose (v2 plugin) not found."
  error "Update Docker Desktop or install: https://docs.docker.com/compose/install/"
  exit 1
fi

if ! docker info &>/dev/null 2>&1; then
  error "Docker daemon is not running. Start Docker Desktop and try again."
  exit 1
fi

# Detect non-interactive runs (CI, no TTY). Skip prompts; default to "keep".
NON_INTERACTIVE=0
if [ -n "${CI:-}" ] || [ ! -t 0 ]; then
  NON_INTERACTIVE=1
fi

# ── DeepSeek API key (BYOK — optional) ────────────────────────────────────
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  if [ "$NON_INTERACTIVE" -eq 0 ]; then
    echo ""
    info "No DEEPSEEK_API_KEY found in environment."
    info "Get your key at: https://platform.deepseek.com/api_keys"
    echo ""
    printf "${GREEN}[ecoseek]${NC} Enter your DeepSeek API key (or press Enter to skip): "
    read -r DEEPSEEK_API_KEY
  fi
  if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    warn "No DEEPSEEK_API_KEY provided. EcoSeek will run in local-only mode (Ollama)."
  fi
fi
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"

# ── Emily API key (shared frontend ↔ Emily backend secret) ───────────────
# The frontend's nginx injects this as the server-side Bearer token when
# proxying /v1/ to the Emily backend on port 8642 (EMILY_HERMES_KEY defaults
# to EMILY_API_KEY in docker-compose.yml). The Emily backend validates it as
# API_SERVER_KEY. If it is empty the frontend refuses to start, so generate a
# stable random value here and reuse any existing one across re-runs.
if [ -z "${EMILY_API_KEY:-}" ] && [ -f .env ]; then
  EMILY_API_KEY="$(grep -E '^EMILY_API_KEY=' .env 2>/dev/null | head -1 | cut -d= -f2-)"
fi
if [ -z "${EMILY_API_KEY:-}" ]; then
  EMILY_API_KEY="$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi
export EMILY_API_KEY

# ── Generate / update .env ────────────────────────────────────────────────
# Defaults that docker-compose.yml expects.
# OLLAMA_MODEL defaults to a small public model so the smoke test can run
# end-to-end without depending on a private/unreleased model. Override
# with `OLLAMA_MODEL=ecocoder bash setup.sh` once that model is published.
ECOSEEK_API_PORT="${ECOSEEK_API_PORT:-${ECOSEEK_UI_PORT:-3000}}"
AGENTICPLUG_PORT="${AGENTICPLUG_PORT:-8080}"
ECOAGENT_PORT="${ECOAGENT_PORT:-8000}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-tinyllama}"
ECOSEEK_AAR_ENABLED="${ECOSEEK_AAR_ENABLED:-false}"
ECOSEEK_JUDGE_MODEL="${ECOSEEK_JUDGE_MODEL:-auto}"
# PHOENIX_PORT is the loopback host port for the optional observability
# profile; the Phoenix container always listens on 6006 internally.
PHOENIX_PORT="${PHOENIX_PORT:-6006}"
PHOENIX_ENDPOINT="${PHOENIX_ENDPOINT:-http://phoenix:6006}"
PHOENIX_PROJECT_NAME="${PHOENIX_PROJECT_NAME:-ecoseek}"
# Default profile = cpu so `docker compose up` brings the CPU Ollama
# variant; the GPU profile (`--profile gpu`) is mutually exclusive.
COMPOSE_PROFILES="${COMPOSE_PROFILES:-cpu}"
# AgenticPlug session store: sqlite for alpha (persistent), memory for dev/test
BROKER_SESSION_STORE="${BROKER_SESSION_STORE:-sqlite}"

OVERWRITE=1
if [ -f .env ]; then
  if [ "$NON_INTERACTIVE" -eq 1 ]; then
    info "Non-interactive run detected — keeping existing .env unchanged"
    OVERWRITE=0
  else
    echo ""
    warn ".env already exists at $(pwd)/.env"
    printf "${GREEN}[ecoseek]${NC} Overwrite it with the latest defaults? [y/N]: "
    read -r REPLY
    case "$REPLY" in
      [yY]|[yY][eE][sS]) OVERWRITE=1 ;;
      *) OVERWRITE=0 ;;
    esac
  fi
fi

if [ "$OVERWRITE" -eq 1 ]; then
  # Write atomically (umask 077 → 0600) to avoid leaving a partial .env.
  TMP_ENV="$(mktemp .env.XXXXXX)"
  {
    echo "# Generated by setup.sh — local only, do not commit"
    echo ""
    echo "# Compose profile selector (cpu = default CPU Ollama; gpu = NVIDIA passthrough)"
    echo "COMPOSE_PROFILES=${COMPOSE_PROFILES}"
    echo ""
    echo "# Ports"
    echo "ECOSEEK_API_PORT=${ECOSEEK_API_PORT}"
    echo "AGENTICPLUG_PORT=${AGENTICPLUG_PORT}"
    echo "ECOAGENT_PORT=${ECOAGENT_PORT}"
    echo "OLLAMA_PORT=${OLLAMA_PORT}"
    echo "PHOENIX_PORT=${PHOENIX_PORT}"
    echo ""
    echo "# Local model"
    echo "OLLAMA_MODEL=${OLLAMA_MODEL}"
    echo "# Base URL only; ecoseek-api appends /v1/chat/completions"
    echo "LOCAL_LLM_URL=${LOCAL_LLM_URL:-http://ollama:${OLLAMA_PORT}}"
    echo ""
    echo "# Adaptive Autonomous Retrieval"
    echo "ECOSEEK_AAR_ENABLED=${ECOSEEK_AAR_ENABLED}"
    echo "ECOSEEK_JUDGE_MODEL=${ECOSEEK_JUDGE_MODEL}"
    echo ""
    echo "# Phoenix observability (optional profile)"
    echo "PHOENIX_ENDPOINT=${PHOENIX_ENDPOINT}"
    echo "PHOENIX_PROJECT_NAME=${PHOENIX_PROJECT_NAME}"
    echo ""
    echo "# AgenticPlug session store backend"
    echo "# Options: memory (dev/test), sqlite (default for alpha, persistent)"
    echo "# SQLite sessions survive broker restarts via broker-data Docker volume"
    echo "BROKER_SESSION_STORE=${BROKER_SESSION_STORE}"
    echo ""
    echo "# AgenticPlug GitHub allowlist for CLI session handshake. Comma-"
    echo "# separated GitHub logins. Empty = no sessions can be issued. Set"
    echo "# this to your own GitHub login if you want to exercise the"
    echo "# broker-mediated /v1/chat/completions route in scripts/smoke.sh."
    echo "AGENTICPLUG_ALLOWED_LOGINS=${AGENTICPLUG_ALLOWED_LOGINS:-}"
    echo ""
    echo "# AgenticPlug session id (opaque bearer token) for scripts/smoke.sh"
    echo "# to call /v1/chat/completions. Obtain via POST /v1/cli/session"
    echo "# with a personal GitHub access token; see docs/smoke-test.md."
    echo "# Empty = smoke.sh will skip the broker-mediated chat check and"
    echo "# print a clear hint instead of pretending it passed."
    echo "AGENTICPLUG_SESSION=${AGENTICPLUG_SESSION:-}"
    echo ""
    echo "# Hermes remote (scientific orchestrator via Tailscale funnel)"
    echo "# Set HERMES_URL and HERMES_API_KEY to connect to a remote Hermes."
    echo "# HERMES_ENABLED=true enables the adapter in AgenticPlug."
    echo "HERMES_URL=${HERMES_URL:-}"
    echo "HERMES_API_KEY=${HERMES_API_KEY:-}"
    echo "HERMES_ENABLED=${HERMES_ENABLED:-false}"
    echo ""
    echo "# BYOK — empty by default; fill in to use DeepSeek cloud"
    echo "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}"
    echo ""
    echo "# Emily API key — shared secret between the frontend proxy and the"
    echo "# Emily backend (port 8642). The frontend's nginx injects it as the"
    echo "# server-side Bearer token (EMILY_HERMES_KEY defaults to this), and"
    echo "# the Emily backend validates it as API_SERVER_KEY. Must be non-empty"
    echo "# or the frontend refuses to start (avoids silent HTTP 401 on chat)."
    echo "EMILY_API_KEY=${EMILY_API_KEY}"
    echo "# Override only if the backend on :8642 uses a different key than"
    echo "# EMILY_API_KEY (e.g. a host hermes process). Defaults to EMILY_API_KEY."
    echo "EMILY_HERMES_KEY=${EMILY_HERMES_KEY:-}"
    echo ""
    echo "# NCBI Entrez / PubMed API key (optional)"
    echo "# Without key: 3 req/s. With key: 10 req/s."
    echo "# Get one at: https://www.ncbi.nlm.nih.gov/account/settings/"
    echo "ENTREZ_API_KEY=${ENTREZ_API_KEY:-}"
    echo "ENTREZ_EMAIL=${ENTREZ_EMAIL:-ecoseek@ecoseek.org}"
    echo ""
    echo "# Upstream timeout (seconds) — applied to all gateway upstream calls"
    echo "UPSTREAM_TIMEOUT_S=${UPSTREAM_TIMEOUT_S:-30}"
  } > "$TMP_ENV"
  mv "$TMP_ENV" .env
  chmod 600 .env || true
  info ".env written to $(pwd)/.env (git-ignored, local only)"
else
  info "Keeping existing .env unchanged"
fi

# ── Provider detection (informational only — backend reads from env) ──────
if [ -n "${HERMES_URL:-}" ] && [ -n "${HERMES_API_KEY:-}" ]; then
  info "LLM provider: Hermes remote (${HERMES_URL})"
elif [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  info "LLM provider: DeepSeek API (cloud, BYOK)"
else
  info "LLM provider: Ollama (local) — pull the model with:"
  info "  docker compose exec ollama ollama pull ${OLLAMA_MODEL}"
fi

# ── Clone dependency repos ────────────────────────────────────────────────
clone_repo() {
  local repo_url="$1"
  local dest="$2"
  if [ -d "$dest/.git" ]; then
    info "Updating $dest ..."
    git -C "$dest" pull --ff-only 2>/dev/null || warn "Could not update $dest (non-fatal)"
  else
    info "Cloning $repo_url into $dest ..."
    git clone --depth 1 "$repo_url" "$dest"
  fi
}

mkdir -p .repos
clone_repo "https://github.com/alrobles/agenticplug.git" ".repos/agenticplug"
clone_repo "https://github.com/alrobles/ecoagent.git"     ".repos/ecoagent"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
info "Setup complete. Local URLs after 'docker compose up -d':"
printf "  %-25s %s\n" "EcoSeek API:"         "http://127.0.0.1:${ECOSEEK_API_PORT}"
printf "  %-25s %s\n" "AgenticPlug gateway:" "http://127.0.0.1:${AGENTICPLUG_PORT}"
printf "  %-25s %s\n" "EcoAgent tools:"      "http://127.0.0.1:${ECOAGENT_PORT}/v1/tools"
printf "  %-25s %s\n" "Ollama API:"          "http://127.0.0.1:${OLLAMA_PORT}"
printf "  %-25s %s\n" "Phoenix (optional):"  "http://127.0.0.1:${PHOENIX_PORT}  (--profile observability)"
echo ""
info "Configuration summary (values redacted for KEY/TOKEN/SECRET/PASSWORD):"
print_var COMPOSE_PROFILES   "${COMPOSE_PROFILES}"
print_var OLLAMA_MODEL       "${OLLAMA_MODEL}"
print_var ECOSEEK_AAR_ENABLED "${ECOSEEK_AAR_ENABLED}"
print_var ECOSEEK_JUDGE_MODEL "${ECOSEEK_JUDGE_MODEL}"
print_var PHOENIX_PORT       "${PHOENIX_PORT}"
print_var PHOENIX_ENDPOINT   "${PHOENIX_ENDPOINT}"
print_var BROKER_SESSION_STORE "${BROKER_SESSION_STORE}"
print_var AGENTICPLUG_ALLOWED_LOGINS "${AGENTICPLUG_ALLOWED_LOGINS:-}"
# AGENTICPLUG_SESSION is an opaque bearer token; treat as a secret.
if [ -n "${AGENTICPLUG_SESSION:-}" ]; then
  printf "  %-25s %s\n" "AGENTICPLUG_SESSION:" "configured (value hidden)"
else
  printf "  %-25s %s\n" "AGENTICPLUG_SESSION:" "not set"
fi
print_var HERMES_URL         "${HERMES_URL:-}"
print_var HERMES_API_KEY     "${HERMES_API_KEY:-}"
print_var HERMES_ENABLED     "${HERMES_ENABLED:-false}"
print_var DEEPSEEK_API_KEY   "${DEEPSEEK_API_KEY:-}"
if [ -n "${ENTREZ_API_KEY:-}" ]; then
  print_var ENTREZ_API_KEY   "configured (10 req/s)"
else
  print_var ENTREZ_API_KEY   "not set (3 req/s — get key at ncbi.nlm.nih.gov/account/settings)"
fi
echo ""
info "All host ports bind to 127.0.0.1 (loopback only). If you need LAN"
info "access, edit docker-compose.yml — do not expose Ollama or AgenticPlug"
info "to a network: they have no authentication by default."
echo ""
info "Next steps:"
info "  1. docker compose up -d"
info "  2. Wait for services to become healthy (docker compose ps)"
info "  3. curl http://127.0.0.1:${AGENTICPLUG_PORT}/healthz"
info "  4. Canonical Phase 2 smoke (one command):"
info "       bash scripts/smoke.sh"
info "     Full walk-through: docs/smoke-test.md"
echo ""
info "Frontend only (Emily chat UI):                    bash frontend-start.sh"
info "GPU stack (mutually exclusive with default CPU): docker compose --profile gpu up"
info "Observability stack:                              docker compose --profile observability up"
info "To stop:    docker compose down"
info "Logs:       docker compose logs -f"
info "Rebuild:    bash setup.sh && docker compose up --build -d"
