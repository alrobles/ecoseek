# EcoSeek one-command setup for Windows.
# Works with Docker Desktop on Windows (no WSL required).
#
# Usage:
#   git clone https://github.com/alrobles/ecoseek.git
#   cd ecoseek
#   .\setup.ps1
#
# What it does:
#   1. Checks prerequisites (git, docker)
#   2. Builds and starts the DIY-mode stack via Docker Compose
#   3. Verifies services are healthy
#
# No Node.js, Python, or npm required on the host.

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host "[ecoseek] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[ecoseek] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ecoseek] $args" -ForegroundColor Red }

# ── Prerequisites ─────────────────────────────────────────────────────────
function Test-Command($cmd, $help) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Err "Required: $cmd is not installed."
        Write-Err $help
        exit 1
    }
}

Test-Command "git"    "Install git: https://git-scm.com/downloads"
Test-Command "docker" "Install Docker Desktop: https://docs.docker.com/get-docker/"

# Check docker compose v2
try {
    docker compose version | Out-Null
} catch {
    Write-Err "docker compose (v2 plugin) not found."
    Write-Err "Update Docker Desktop or install: https://docs.docker.com/compose/install/"
    exit 1
}

# Check Docker daemon
try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    Write-Err "Docker daemon is not running. Start Docker Desktop and try again."
    exit 1
}

# ── Build and start ───────────────────────────────────────────────────────
Write-Info "Building EcoSeek stack (first run takes 2-5 minutes)..."
Write-Info "  - AgenticPlug broker (gateway)"
Write-Info "  - EcoAgent tool server (ecological tools)"
Write-Info "  - Ollama (local model inference)"
Write-Host ""

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed. Check the output above."
    exit 1
}

# ── Health check ──────────────────────────────────────────────────────────
Write-Info "Waiting for services to become healthy..."
$maxWait = 120
$elapsed = 0

while ($elapsed -lt $maxWait) {
    $brokerHealth = docker compose ps broker --format '{{.Health}}' 2>$null
    $ecoagentHealth = docker compose ps ecoagent --format '{{.Health}}' 2>$null
    if ($brokerHealth -eq "healthy" -and $ecoagentHealth -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "." -NoNewline
}
Write-Host ""

if ($elapsed -ge $maxWait) {
    Write-Warn "Services did not become healthy within ${maxWait}s."
    Write-Warn "Check logs with: docker compose logs"
    exit 1
}

# ── Summary ───────────────────────────────────────────────────────────────
Write-Info "EcoSeek stack is running!"
Write-Host ""
Write-Host ("  {0,-25} {1}" -f "AgenticPlug broker:", "http://localhost:3000")
Write-Host ("  {0,-25} {1}" -f "EcoAgent tool server:", "http://localhost:8100")
Write-Host ("  {0,-25} {1}" -f "Ollama:", "http://localhost:11434")
Write-Host ""
Write-Info "To stop:    docker compose down"
Write-Info "To restart: docker compose up -d"
Write-Info "Logs:       docker compose logs -f"
Write-Host ""
Write-Warn "This is a pre-alpha development stack. Do NOT use real secrets or production credentials."
