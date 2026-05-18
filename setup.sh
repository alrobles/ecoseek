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
#   2. Clones dependency repos into .repos/ (uses YOUR git auth)
#   3. Builds Docker images from the local checkouts
#   4. Starts the stack and verifies services are healthy
#
# No Node.js, Python, or npm required on the host.
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

# ── Build and start ───────────────────────────────────────────────────────
info "Building EcoSeek stack (first run takes 2-5 minutes)..."
info "  - AgenticPlug broker (gateway)"
info "  - Ollama (local model inference)"
echo ""

docker compose up --build -d

# ── Health check ──────────────────────────────────────────────────────────
info "Waiting for broker to become healthy..."
MAX_WAIT=120
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
    exit 1
  fi
  printf "."
done
echo ""

# ── Summary ───────────────────────────────────────────────────────────────
info "EcoSeek stack is running!"
echo ""
printf "  %-25s %s\n" "AgenticPlug broker:" "http://localhost:3000"
printf "  %-25s %s\n" "Ollama:" "http://localhost:11434"
echo ""
info "To stop:    docker compose down"
info "To restart: docker compose up -d"
info "Logs:       docker compose logs -f"
info "Rebuild:    bash setup.sh"
echo ""
warn "This is a pre-alpha development stack. Do NOT use real secrets or production credentials."
