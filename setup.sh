#!/usr/bin/env bash
# EcoSeek one-command setup.
# Works on Linux, macOS, and Windows (WSL).
#
# Usage:
#   DEEPSEEK_API_KEY=sk-xxx bash setup.sh   # with DeepSeek API
#   bash setup.sh                            # prompts for API key
#
# What it does:
#   1. Checks prerequisites (git, docker)
#   2. Asks for your DeepSeek API key (if not set)
#   3. Clones dependency repos into .repos/ (uses YOUR git auth)
#   4. Builds Docker images from the local checkouts
#   5. Starts the full stack and verifies services are healthy
#
# No Node.js, Python, or npm required on the host — just Git + Docker.
# Works with private repos — git clone runs on the host where you
# are already authenticated, then Docker COPY's the files in.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}[ecoseek]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[ecoseek]${NC} %s\n" "$*"; }
error() { printf "${RED}[ecoseek]${NC} %s\n" "$*" >&2; }

# ── Prerequisites ─────────────────────────────────────────────────────────
check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "Required: $1 is not installed."
    error "$2"
    exit 1
  fi
}

check_cmd git   "Install git: https://git-scm.com/downloads"
check_cmd docker "Install Docker Desktop: https://docs.docker.com/get-docker/"

# Check docker compose (v2 plugin)
if ! docker compose version &>/dev/null; then
  error "docker compose (v2 plugin) not found."
  error "Update Docker Desktop or install: https://docs.docker.com/compose/install/"
  exit 1
fi

# Check Docker daemon is running
if ! docker info &>/dev/null 2>&1; then
  error "Docker daemon is not running. Start Docker Desktop and try again."
  exit 1
fi

# ── DeepSeek API key ──────────────────────────────────────────────────────
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo ""
  info "No DEEPSEEK_API_KEY found in environment."
  info "Get your key at: https://platform.deepseek.com/api_keys"
  echo ""
  printf "${GREEN}[ecoseek]${NC} Enter your DeepSeek API key (or press Enter to skip): "
  read -r DEEPSEEK_API_KEY
  if [ -z "$DEEPSEEK_API_KEY" ]; then
    warn "No API key provided. The stack will start but AI features won't work."
    warn "You can set it later: DEEPSEEK_API_KEY=sk-xxx docker compose up -d"
  fi
fi
export DEEPSEEK_API_KEY

# Write .env file for docker compose (persists across restarts)
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  echo "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}" > .env
  info "API key saved to .env (git-ignored, local only)"
fi

# ── Generate config.ini ──────────────────────────────────────────────────
# The backend reads config.ini at startup. We generate it here so Docker
# networking hostnames are used (ollama:11434 instead of 127.0.0.1:11434)
# and the provider is set based on whether an API key was provided.
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  PROVIDER_NAME="deepseek"
  PROVIDER_MODEL="deepseek-chat"
  PROVIDER_ADDRESS="https://api.deepseek.com"
  IS_LOCAL="False"
  info "LLM provider: DeepSeek API (cloud)"
else
  PROVIDER_NAME="ollama"
  PROVIDER_MODEL="deepseek-r1:14b"
  PROVIDER_ADDRESS="http://ollama:11434"
  IS_LOCAL="True"
  info "LLM provider: Ollama (local) — pull a model with: docker compose exec ollama ollama pull deepseek-r1:14b"
fi

cat > config.ini <<EOF
[MAIN]
is_local = ${IS_LOCAL}
provider_name = ${PROVIDER_NAME}
provider_model = ${PROVIDER_MODEL}
provider_server_address = ${PROVIDER_ADDRESS}
agent_name = Jarvis
recover_last_session = False
save_session = False
speak = False
listen = False
jarvis_personality = False
languages = en
[BROWSER]
headless_browser = True
stealth_mode = False
EOF
info "Generated config.ini (provider: ${PROVIDER_NAME})"

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
clone_repo "https://github.com/alrobles/agenticSeek.git"  ".repos/agenticSeek"

# ── Build and start ───────────────────────────────────────────────────────
info "Building EcoSeek stack (first run takes 5-10 minutes)..."
info "  - AgenticSeek backend  (API + agents)"
info "  - AgenticSeek frontend (React UI)"
info "  - AgenticPlug broker   (gateway)"
info "  - SearxNG              (private web search)"
info "  - Redis                (task queue)"
info "  - Ollama               (local model inference)"
echo ""

docker compose up --build -d

# ── Health check ──────────────────────────────────────────────────────────
info "Waiting for services to become healthy..."
MAX_WAIT=180
ELAPSED=0

broker_healthy() {
  local health
  health=$(docker compose ps broker --format '{{.Health}}' 2>/dev/null || echo "unknown")
  [[ "$health" == "healthy" ]]
}

while ! broker_healthy; do
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    warn "Broker did not become healthy within ${MAX_WAIT}s."
    warn "Check logs with: docker compose logs broker"
    warn "The other services may still be starting — check: docker compose ps"
    exit 1
  fi
  printf "."
done
echo ""

# ── Summary ───────────────────────────────────────────────────────────────
info "EcoSeek stack is running!"
echo ""
printf "  %-25s %s\n" "AgenticSeek UI:"     "http://localhost:3000"
printf "  %-25s %s\n" "AgenticSeek API:"    "http://localhost:7777"
printf "  %-25s %s\n" "AgenticPlug broker:" "http://localhost:3100"
printf "  %-25s %s\n" "SearxNG:"            "http://localhost:8080"
printf "  %-25s %s\n" "Ollama:"             "http://localhost:11434"
echo ""
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  info "DeepSeek API key: configured"
else
  warn "DeepSeek API key: not set (AI features disabled)"
  warn "Set it with: DEEPSEEK_API_KEY=sk-xxx docker compose up -d"
fi
echo ""
info "To stop:    docker compose down"
info "To restart: docker compose up -d"
info "Logs:       docker compose logs -f"
info "Rebuild:    bash setup.sh"
echo ""
info "Open http://localhost:3000 in your browser to start using EcoSeek."
