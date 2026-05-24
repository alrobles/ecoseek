#!/usr/bin/env bash
# EcoSeek Emily — one-command start via Docker.
# Launches both the Emily local agent and the frontend.
#
# Auth goes through broker.ecoseek.org (GitHub OAuth).
# Chat goes to Emily local at :8642.
#
# Usage:
#   DEEPSEEK_API_KEY=sk-... HERMES_ECOSEEK_API_KEY=agenticplu-... bash emily-start.sh
#   DEEPSEEK_API_KEY=sk-... bash emily-start.sh            # local only (no remote delegation)
#   OLLAMA_BASE_URL=http://host:11434 bash emily-start.sh  # use local Ollama
#
# No Python, Node.js, or npm required — only Docker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${GREEN}[emily]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[emily]${NC} %s\n" "$*"; }
error() { printf "${RED}[emily]${NC} %s\n" "$*" >&2; }
emily() { printf "${CYAN}🌿 Emily:${NC} %s\n" "$*"; }

# ── Prerequisites ─────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  error "Docker is not installed. Get it at: https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker info &>/dev/null 2>&1; then
  error "Docker daemon is not running. Start Docker Desktop and try again."
  exit 1
fi

# ── Configuration ─────────────────────────────────────────────────────
BROKER_URL="${ECOSEEK_BROKER_URL:-https://broker.ecoseek.org}"
BROKER_KEY="${ECOSEEK_BROKER_KEY:-}"
HERMES_KEY="${HERMES_ECOSEEK_API_KEY:-}"
HERMES_URL="${HERMES_REMOTE_URL:-https://hermes.ecoseek.org}"
EMILY_PORT="${EMILY_PORT:-8642}"
FRONTEND_PORT="${FRONTEND_PORT:-4000}"
DEEPSEEK_KEY="${DEEPSEEK_API_KEY:-}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
OLLAMA_URL="${OLLAMA_BASE_URL:-}"

# Shared key for Emily <-> frontend auth.  Hermes requires API_SERVER_KEY
# when the API server binds to 0.0.0.0 (needed inside Docker for port mapping).
EMILY_KEY="${API_SERVER_KEY:-$(openssl rand -hex 16)}"

echo ""
emily "Hi! I'm Emily, your ecological AI assistant."
emily "Setting up my workspace..."
echo ""

# ── Emily local agent ────────────────────────────────────────────────
EMILY_CONTAINER="emily-local"
EMILY_IMAGE="emily-local"

info "Building Emily agent..."

if docker ps -a --format '{{.Names}}' | grep -q "^${EMILY_CONTAINER}$"; then
  info "Stopping previous Emily..."
  docker rm -f "$EMILY_CONTAINER" >/dev/null 2>&1 || true
fi

docker build \
  -t "$EMILY_IMAGE" \
  emily/

EMILY_ENV=()
EMILY_ENV+=(-e "ECOSEEK_BROKER_URL=$BROKER_URL")
EMILY_ENV+=(-e "API_SERVER_KEY=$EMILY_KEY")
EMILY_ENV+=(-e "API_SERVER_CORS_ORIGINS=http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}")
EMILY_ENV+=(-e "HERMES_REMOTE_URL=$HERMES_URL")
[ -n "$HERMES_KEY" ] && EMILY_ENV+=(-e "HERMES_ECOSEEK_API_KEY=$HERMES_KEY")
[ -n "$BROKER_KEY" ] && EMILY_ENV+=(-e "ECOSEEK_BROKER_KEY=$BROKER_KEY")
[ -n "$DEEPSEEK_KEY" ] && EMILY_ENV+=(-e "DEEPSEEK_API_KEY=$DEEPSEEK_KEY") && EMILY_ENV+=(-e "DEEPSEEK_MODEL=$DEEPSEEK_MODEL")
[ -n "$OLLAMA_URL" ] && EMILY_ENV+=(-e "OLLAMA_BASE_URL=$OLLAMA_URL")

docker run -d \
  --name "$EMILY_CONTAINER" \
  -p "127.0.0.1:${EMILY_PORT}:8642" \
  --add-host=host.docker.internal:host-gateway \
  "${EMILY_ENV[@]}" \
  --restart unless-stopped \
  "$EMILY_IMAGE"

info "Emily agent started on port $EMILY_PORT"

# ── Frontend ──────────────────────────────────────────────────────────
FRONTEND_CONTAINER="ecoseek-frontend"
FRONTEND_IMAGE="ecoseek-frontend"

info "Building frontend..."

if docker ps -a --format '{{.Names}}' | grep -q "^${FRONTEND_CONTAINER}$"; then
  info "Stopping previous frontend..."
  docker rm -f "$FRONTEND_CONTAINER" >/dev/null 2>&1 || true
fi

# Auth goes through the broker (GitHub OAuth).
# Chat goes to Emily local at :8642.
docker build \
  --build-arg REACT_APP_BROKER_URL="${BROKER_URL}" \
  --build-arg REACT_APP_EMILY_URL="http://localhost:${EMILY_PORT}" \
  --build-arg REACT_APP_EMILY_KEY="${EMILY_KEY}" \
  -t "$FRONTEND_IMAGE" \
  frontend/

docker run -d \
  --name "$FRONTEND_CONTAINER" \
  -p "127.0.0.1:${FRONTEND_PORT}:80" \
  --restart unless-stopped \
  "$FRONTEND_IMAGE"

echo ""
emily "I'm ready! Here's what's running:"
echo ""
info "  Emily agent:  http://localhost:${EMILY_PORT}  (Alpha, local)"
info "  Hermes Beta:  ${HERMES_URL}  (remote, reumanlab)"
info "  Broker:       ${BROKER_URL}  (auth)"
info "  Frontend:     http://localhost:${FRONTEND_PORT}"
if [ -n "$HERMES_KEY" ]; then
  info "  DiDAL:        Enabled (escalate_remote + dialectical_exchange)"
else
  warn "  DiDAL:        Disabled (set HERMES_ECOSEEK_API_KEY to enable remote delegation)"
fi
echo ""
info "  Open http://localhost:${FRONTEND_PORT} in your browser."
info "  Sign in with GitHub to start chatting with Emily."
echo ""
info "Commands:"
info "  Stop:    docker stop ${EMILY_CONTAINER} ${FRONTEND_CONTAINER}"
info "  Logs:    docker logs -f ${EMILY_CONTAINER}"
info "  Restart: bash emily-start.sh"
