#!/usr/bin/env bash
# EcoSeek Frontend — quick start via Docker.
# Works on Linux, macOS, and Windows (WSL / Git Bash).
#
# Usage:
#   bash frontend-start.sh                                             # default: broker.ecoseek.org, port 4000
#   REACT_APP_BROKER_URL=http://localhost:9092 bash frontend-start.sh  # custom broker
#   FRONTEND_PORT=8080 bash frontend-start.sh                         # custom port
#
# No Node.js or npm required — only Docker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

CONTAINER_NAME="ecoseek-frontend"
IMAGE_NAME="ecoseek-frontend"

info()  { printf "${GREEN}[ecoseek]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[ecoseek]${NC} %s\n" "$*"; }
error() { printf "${RED}[ecoseek]${NC} %s\n" "$*" >&2; }

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
BROKER_URL="${REACT_APP_BROKER_URL:-https://broker.ecoseek.org}"
PORT="${FRONTEND_PORT:-4000}"

info "Building EcoSeek frontend..."
info "  Broker URL: $BROKER_URL"
info "  Local port: $PORT"
echo ""

# ── Stop previous container if running ────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  info "Stopping previous ${CONTAINER_NAME}..."
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# ── Build ─────────────────────────────────────────────────────────────
docker build \
  --build-arg REACT_APP_BROKER_URL="$BROKER_URL" \
  -t "$IMAGE_NAME" \
  frontend/

# ── Run ───────────────────────────────────────────────────────────────
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:${PORT}:80" \
  --restart unless-stopped \
  "$IMAGE_NAME"

echo ""
info "EcoSeek frontend is running!"
info ""
info "  Open: http://localhost:${PORT}"
info ""
info "  Emily (your ecological AI assistant) is ready."
info "  Sign in with GitHub to start chatting."
info ""
info "Commands:"
info "  Stop:    docker stop ${CONTAINER_NAME}"
info "  Logs:    docker logs -f ${CONTAINER_NAME}"
info "  Restart: docker restart ${CONTAINER_NAME}"
info "  Rebuild: bash frontend-start.sh"
