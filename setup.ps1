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
#   2. Clones dependency repos into .repos/ (uses YOUR git auth)
#   3. Builds Docker images from the local checkouts
#   4. Starts the stack and verifies services are healthy
#
# No Node.js, Python, or npm required on the host.
# Works with private repos — git clone runs on the host where you
# are already authenticated, then Docker COPY's the files in.

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

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

# ── Clone dependency repos ────────────────────────────────────────────────
function Clone-Repo($url, $dest) {
    if (Test-Path "$dest\.git") {
        Write-Info "Updating $dest ..."
        git -C $dest pull --ff-only 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Warn "Could not update $dest (non-fatal)" }
    } else {
        Write-Info "Cloning $url into $dest ..."
        git clone --depth 1 $url $dest
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to clone $url. Check your git authentication."
            exit 1
        }
    }
}

if (-not (Test-Path ".repos")) { New-Item -ItemType Directory -Path ".repos" | Out-Null }
Clone-Repo "https://github.com/alrobles/agenticplug.git" ".repos\agenticplug"

# ── Build and start ───────────────────────────────────────────────────────
Write-Info "Building EcoSeek stack (first run takes 2-5 minutes)..."
Write-Info "  - AgenticPlug broker (gateway)"
Write-Info "  - Ollama (local model inference)"
Write-Host ""

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed. Check the output above."
    exit 1
}

# ── Health check ──────────────────────────────────────────────────────────
Write-Info "Waiting for broker to become healthy..."
$maxWait = 120
$elapsed = 0

while ($elapsed -lt $maxWait) {
    $brokerHealth = docker compose ps broker --format '{{.Health}}' 2>$null
    if ($brokerHealth -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "." -NoNewline
}
Write-Host ""

if ($elapsed -ge $maxWait) {
    Write-Warn "Broker did not become healthy within ${maxWait}s."
    Write-Warn "Check logs with: docker compose logs broker"
    exit 1
}

# ── Summary ───────────────────────────────────────────────────────────────
Write-Info "EcoSeek stack is running!"
Write-Host ""
Write-Host ("  {0,-25} {1}" -f "AgenticPlug broker:", "http://localhost:3000")
Write-Host ("  {0,-25} {1}" -f "Ollama:", "http://localhost:11434")
Write-Host ""
Write-Info "To stop:    docker compose down"
Write-Info "To restart: docker compose up -d"
Write-Info "Logs:       docker compose logs -f"
Write-Info "Rebuild:    .\setup.ps1"
Write-Host ""
Write-Warn "This is a pre-alpha development stack. Do NOT use real secrets or production credentials."
Pop-Location
