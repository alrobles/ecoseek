#!/usr/bin/env bash
# EcoSeek one-command setup.
# Works on Linux, macOS, and Windows (WSL).
#
# Usage:
#   git clone https://github.com/alrobles/ecoseek.git
#   cd ecoseek
#   bash setup.sh
#
# What it does:
#   1. Checks prerequisites (git, docker)
#   2. Builds and starts the DIY-mode stack via Docker Compose
#   3. Verifies services are healthy
#
# No Node.js, Python, or npm required on the host.

set -euo pipefail

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

# ── Build and start ───────────────────────────────────────────────────────
info "Building EcoSeek stack (first run takes 2-5 minutes)..."
info "  - AgenticPlug broker (gateway)"
info "  - EcoAgent tool server (ecological tools)"
info "  - Ollama (local model inference)"
echo ""

docker compose up --build -d

# ── Health check ──────────────────────────────────────────────────────────
info "Waiting for services to become healthy..."
MAX_WAIT=120
ELAPSED=0

all_healthy() {
  local broker_health ecoagent_health
  broker_health=$(docker compose ps broker --format '{{.Health}}' 2>/dev/null || echo "unknown")
  ecoagent_health=$(docker compose ps ecoagent --format '{{.Health}}' 2>/dev/null || echo "unknown")
  [[ "$broker_health" == "healthy" && "$ecoagent_health" == "healthy" ]]
}

while ! all_healthy; do
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    warn "Services did not become healthy within ${MAX_WAIT}s."
    warn "Check logs with: docker compose logs"
    exit 1
  fi
  printf "."
done
echo ""

# ── Summary ───────────────────────────────────────────────────────────────
info "EcoSeek stack is running!"
echo ""
printf "  %-25s %s\n" "AgenticPlug broker:" "http://localhost:3000"
printf "  %-25s %s\n" "EcoAgent tool server:" "http://localhost:8100"
printf "  %-25s %s\n" "Ollama:" "http://localhost:11434"
echo ""
info "To stop:    docker compose down"
info "To restart: docker compose up -d"
info "Logs:       docker compose logs -f"
echo ""
warn "This is a pre-alpha development stack. Do NOT use real secrets or production credentials."
