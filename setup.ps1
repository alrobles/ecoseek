# EcoSeek one-command setup for Windows.
# Works with Docker Desktop on Windows (no WSL required).
#
# Usage:
#   $env:DEEPSEEK_API_KEY="sk-xxx"; .\setup.ps1   # with DeepSeek API
#   .\setup.ps1                                     # prompts for API key
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

# ── DeepSeek API key ──────────────────────────────────────────────────────
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Host ""
    Write-Info "No DEEPSEEK_API_KEY found in environment."
    Write-Info "Get your key at: https://platform.deepseek.com/api_keys"
    Write-Host ""
    $key = Read-Host "[ecoseek] Enter your DeepSeek API key (or press Enter to skip)"
    if ($key) {
        $env:DEEPSEEK_API_KEY = $key
    } else {
        Write-Warn "No API key provided. The stack will start but AI features won't work."
        Write-Warn "You can set it later: `$env:DEEPSEEK_API_KEY='sk-xxx'; docker compose up -d"
    }
}

# Write .env file for docker compose (persists across restarts)
if ($env:DEEPSEEK_API_KEY) {
    "DEEPSEEK_API_KEY=$($env:DEEPSEEK_API_KEY)" | Set-Content -Path ".env" -NoNewline
    Write-Info "API key saved to .env (git-ignored, local only)"
}

# -- Generate config.ini --------------------------------------------------------
# The backend reads config.ini at startup. We generate it here so Docker
# networking hostnames are used (ollama:11434 instead of 127.0.0.1:11434)
# and the provider is set based on whether an API key was provided.
if ($env:DEEPSEEK_API_KEY) {
    $providerName = "deepseek"
    $providerModel = "deepseek-chat"
    $providerAddress = "https://api.deepseek.com"
    $isLocal = "False"
    Write-Info "LLM provider: DeepSeek API (cloud)"
} else {
    $providerName = "ollama"
    $providerModel = "deepseek-r1:14b"
    $providerAddress = "http://ollama:11434"
    $isLocal = "True"
    Write-Info "LLM provider: Ollama (local) - pull a model with: docker compose exec ollama ollama pull deepseek-r1:14b"
}

$configContent = @"
[MAIN]
is_local = $isLocal
provider_name = $providerName
provider_model = $providerModel
provider_server_address = $providerAddress
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
"@
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'config.ini'), $configContent, (New-Object System.Text.UTF8Encoding $false))
Write-Info "Generated config.ini (provider: $providerName)"

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
Clone-Repo "https://github.com/alrobles/agenticSeek.git"  ".repos\agenticSeek"

# ── Build and start ───────────────────────────────────────────────────────
Write-Info "Building EcoSeek stack (first run takes 5-10 minutes)..."
Write-Info "  - AgenticSeek backend  (API + agents)"
Write-Info "  - AgenticSeek frontend (React UI)"
Write-Info "  - AgenticPlug broker   (gateway)"
Write-Info "  - SearxNG              (private web search)"
Write-Info "  - Redis                (task queue)"
Write-Info "  - Ollama               (local model inference)"
Write-Host ""

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed. Check the output above."
    exit 1
}

# ── Health check ──────────────────────────────────────────────────────────
Write-Info "Waiting for services to become healthy..."
$maxWait = 180
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
    Write-Warn "The other services may still be starting — check: docker compose ps"
    exit 1
}

# ── Summary ───────────────────────────────────────────────────────────────
Write-Info "EcoSeek stack is running!"
Write-Host ""
Write-Host ("  {0,-25} {1}" -f "AgenticSeek UI:",     "http://localhost:3000")
Write-Host ("  {0,-25} {1}" -f "AgenticSeek API:",    "http://localhost:7777")
Write-Host ("  {0,-25} {1}" -f "AgenticPlug broker:", "http://localhost:3100")
Write-Host ("  {0,-25} {1}" -f "SearxNG:",            "http://localhost:8080")
Write-Host ("  {0,-25} {1}" -f "Ollama:",             "http://localhost:11434")
Write-Host ""
if ($env:DEEPSEEK_API_KEY) {
    Write-Info "DeepSeek API key: configured"
} else {
    Write-Warn "DeepSeek API key: not set (AI features disabled)"
    Write-Warn "Set it with: `$env:DEEPSEEK_API_KEY='sk-xxx'; docker compose up -d"
}
Write-Host ""
Write-Info "To stop:    docker compose down"
Write-Info "To restart: docker compose up -d"
Write-Info "Logs:       docker compose logs -f"
Write-Info "Rebuild:    .\setup.ps1"
Write-Host ""
Write-Info "Open http://localhost:3000 in your browser to start using EcoSeek."
Pop-Location
