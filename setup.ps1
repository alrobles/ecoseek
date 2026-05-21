# EcoSeek one-command setup for Windows.
# Works with Docker Desktop on Windows (no WSL required).
#
# Usage:
#   .\setup.ps1                                  # interactive, prompts for DeepSeek key
#   $env:DEEPSEEK_API_KEY="sk-xxx"; .\setup.ps1  # non-interactive (BYOK)
#   $env:CI="1"; .\setup.ps1                      # non-interactive (keep .env on conflict)
#
# What it does:
#   1. Checks prerequisites (git, docker, docker compose v2)
#   2. Generates / updates .env with all the variables docker-compose.yml expects
#   3. Generates config.ini for the EcoSeek API / orchestrator
#   4. Clones dependency repos into .repos/ (uses YOUR git auth)
#
# After this script, start the stack with:
#   docker compose up -d

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

function Write-Info { Write-Host "[ecoseek] $args" -ForegroundColor Green }
function Write-Warn { Write-Host "[ecoseek] $args" -ForegroundColor Yellow }
function Write-Err  { Write-Host "[ecoseek] $args" -ForegroundColor Red }

# Return $true if the variable NAME (not value) matches a secret marker.
function Test-SecretName($name) {
    return ($name -match '(?i)KEY|TOKEN|SECRET|PASSWORD')
}

# Print a redacted "name: value" status line, hiding the value for any
# name that matches the secret marker. All summary lines route through
# this helper so a future edit cannot accidentally leak a secret.
function Write-Var($name, $value) {
    if (Test-SecretName $name) {
        if ($value) { Write-Info "  $($name): configured (value hidden)" }
        else        { Write-Info "  $($name): not set" }
    } else {
        Write-Info "  $($name): $value"
    }
}

# Restrict .env ACL to the current user (Windows equivalent of `chmod 600`).
function Restrict-FileAcl($path) {
    try {
        $user = "$env:USERDOMAIN\$env:USERNAME"
        icacls $path /inheritance:r | Out-Null
        icacls $path /grant:r "$($user):(R,W)" | Out-Null
    } catch {
        Write-Warn "Could not restrict ACL on $path — set permissions manually if this is a shared host."
    }
}

# ── Prerequisites ─────────────────────────────────────────────────────────
function Test-Cmd($cmd, $help) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Err "Required: $cmd is not installed."
        Write-Err $help
        exit 1
    }
}

Test-Cmd "git"    "Install git: https://git-scm.com/downloads"
Test-Cmd "docker" "Install Docker Desktop: https://docs.docker.com/get-docker/"

try {
    docker compose version | Out-Null
} catch {
    Write-Err "docker compose (v2 plugin) not found."
    Write-Err "Update Docker Desktop or install: https://docs.docker.com/compose/install/"
    exit 1
}

try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    Write-Err "Docker daemon is not running. Start Docker Desktop and try again."
    exit 1
}

# Non-interactive detection (CI or no console).
$nonInteractive = $false
if ($env:CI -or -not [Environment]::UserInteractive) {
    $nonInteractive = $true
}

# ── DeepSeek API key (BYOK — optional) ────────────────────────────────────
if (-not $env:DEEPSEEK_API_KEY) {
    if (-not $nonInteractive) {
        Write-Host ""
        Write-Info "No DEEPSEEK_API_KEY found in environment."
        Write-Info "Get your key at: https://platform.deepseek.com/api_keys"
        Write-Host ""
        $key = Read-Host "[ecoseek] Enter your DeepSeek API key (or press Enter to skip)"
        if ($key) { $env:DEEPSEEK_API_KEY = $key }
    }
    if (-not $env:DEEPSEEK_API_KEY) {
        Write-Warn "No DEEPSEEK_API_KEY provided. EcoSeek will run in local-only mode (Ollama)."
    }
}

# ── Generate / update .env ────────────────────────────────────────────────
# OLLAMA_MODEL defaults to a small public model so the smoke test can run
# end-to-end without depending on a private/unreleased model.
if (-not $env:ECOSEEK_API_PORT) {
    if ($env:ECOSEEK_UI_PORT) { $env:ECOSEEK_API_PORT = $env:ECOSEEK_UI_PORT }
    else                      { $env:ECOSEEK_API_PORT = "3000" }
}
if (-not $env:AGENTICPLUG_PORT)      { $env:AGENTICPLUG_PORT      = "8080" }
if (-not $env:ECOAGENT_PORT)         { $env:ECOAGENT_PORT         = "8000" }
if (-not $env:OLLAMA_PORT)           { $env:OLLAMA_PORT           = "11434" }
if (-not $env:OLLAMA_MODEL)          { $env:OLLAMA_MODEL          = "tinyllama" }
if (-not $env:ECOSEEK_AAR_ENABLED)   { $env:ECOSEEK_AAR_ENABLED   = "false" }
if (-not $env:ECOSEEK_JUDGE_MODEL)   { $env:ECOSEEK_JUDGE_MODEL   = "auto" }
# PHOENIX_PORT is the loopback host port for the optional observability
# profile; the Phoenix container always listens on 6006 internally.
if (-not $env:PHOENIX_PORT)          { $env:PHOENIX_PORT          = "6006" }
if (-not $env:PHOENIX_ENDPOINT)      { $env:PHOENIX_ENDPOINT      = "http://phoenix:6006" }
if (-not $env:PHOENIX_PROJECT_NAME)  { $env:PHOENIX_PROJECT_NAME  = "ecoseek" }
if (-not $env:COMPOSE_PROFILES)      { $env:COMPOSE_PROFILES      = "cpu" }

$overwrite = $true
if (Test-Path ".env") {
    if ($nonInteractive) {
        Write-Info "Non-interactive run detected - keeping existing .env unchanged"
        $overwrite = $false
    } else {
        Write-Host ""
        Write-Warn ".env already exists at $(Resolve-Path .env)"
        $reply = Read-Host "[ecoseek] Overwrite it with the latest defaults? [y/N]"
        if ($reply -notmatch '^(y|Y|yes|YES)$') { $overwrite = $false }
    }
}

if ($overwrite) {
    $deepseek = if ($env:DEEPSEEK_API_KEY) { $env:DEEPSEEK_API_KEY } else { "" }
    $envContent = @"
# Generated by setup.ps1 - local only, do not commit

# Compose profile selector (cpu = default CPU Ollama; gpu = NVIDIA passthrough)
COMPOSE_PROFILES=$($env:COMPOSE_PROFILES)

# Ports
ECOSEEK_API_PORT=$($env:ECOSEEK_API_PORT)
AGENTICPLUG_PORT=$($env:AGENTICPLUG_PORT)
ECOAGENT_PORT=$($env:ECOAGENT_PORT)
OLLAMA_PORT=$($env:OLLAMA_PORT)
PHOENIX_PORT=$($env:PHOENIX_PORT)

# Local model
OLLAMA_MODEL=$($env:OLLAMA_MODEL)

# Adaptive Autonomous Retrieval
ECOSEEK_AAR_ENABLED=$($env:ECOSEEK_AAR_ENABLED)
ECOSEEK_JUDGE_MODEL=$($env:ECOSEEK_JUDGE_MODEL)

# Phoenix observability (optional profile)
PHOENIX_ENDPOINT=$($env:PHOENIX_ENDPOINT)
PHOENIX_PROJECT_NAME=$($env:PHOENIX_PROJECT_NAME)

# BYOK - empty by default; fill in to use DeepSeek cloud
DEEPSEEK_API_KEY=$deepseek
"@
    $envPath = Join-Path $PSScriptRoot '.env'
    [System.IO.File]::WriteAllText($envPath, $envContent, (New-Object System.Text.UTF8Encoding $false))
    Restrict-FileAcl $envPath
    Write-Info ".env written to $envPath (git-ignored, local only)"
} else {
    Write-Info "Keeping existing .env unchanged"
}

# ── Generate config.ini ──────────────────────────────────────────────────
# Avoid the Docker bind-mount directory trap: if `config.ini` exists as a
# directory (because compose ran before setup), remove it before writing.
if (Test-Path "config.ini" -PathType Container) {
    Write-Warn "config.ini is a directory (Docker auto-created it). Removing it."
    Remove-Item -Recurse -Force "config.ini"
}

if ($env:DEEPSEEK_API_KEY) {
    $providerName = "deepseek"
    $providerModel = "deepseek-chat"
    $providerAddress = "https://api.deepseek.com"
    $isLocal = "False"
    Write-Info "LLM provider: DeepSeek API (cloud, BYOK)"
} else {
    $providerName = "ollama"
    $providerModel = $env:OLLAMA_MODEL
    $providerAddress = "http://ollama:$($env:OLLAMA_PORT)"
    $isLocal = "True"
    Write-Info "LLM provider: Ollama (local) - pull the model with:"
    Write-Info "  docker compose exec ollama ollama pull $($env:OLLAMA_MODEL)"
}

$configContent = @"
[MAIN]
is_local = $isLocal
provider_name = $providerName
provider_model = $providerModel
provider_server_address = $providerAddress
agent_name = EcoSeek
recover_last_session = False
save_session = False
speak = False
listen = False
jarvis_personality = False
personality = ecoseek
temperature = 0.3
top_p = 0.9
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
Clone-Repo "https://github.com/alrobles/ecoagent.git"     ".repos\ecoagent"

# ── Summary ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Info "Setup complete. Local URLs after 'docker compose up -d':"
Write-Host ("  {0,-25} {1}" -f "EcoSeek API:",         "http://127.0.0.1:$($env:ECOSEEK_API_PORT)")
Write-Host ("  {0,-25} {1}" -f "AgenticPlug gateway:", "http://127.0.0.1:$($env:AGENTICPLUG_PORT)")
Write-Host ("  {0,-25} {1}" -f "EcoAgent tools:",      "http://127.0.0.1:$($env:ECOAGENT_PORT)/v1/tools")
Write-Host ("  {0,-25} {1}" -f "Ollama API:",          "http://127.0.0.1:$($env:OLLAMA_PORT)")
Write-Host ("  {0,-25} {1}" -f "Phoenix (optional):",  "http://127.0.0.1:$($env:PHOENIX_PORT)  (--profile observability)")
Write-Host ""
Write-Info "Configuration summary (values redacted for KEY/TOKEN/SECRET/PASSWORD):"
Write-Var "COMPOSE_PROFILES"     $env:COMPOSE_PROFILES
Write-Var "OLLAMA_MODEL"         $env:OLLAMA_MODEL
Write-Var "ECOSEEK_AAR_ENABLED"  $env:ECOSEEK_AAR_ENABLED
Write-Var "ECOSEEK_JUDGE_MODEL"  $env:ECOSEEK_JUDGE_MODEL
Write-Var "PHOENIX_PORT"         $env:PHOENIX_PORT
Write-Var "PHOENIX_ENDPOINT"     $env:PHOENIX_ENDPOINT
Write-Var "DEEPSEEK_API_KEY"     $env:DEEPSEEK_API_KEY
Write-Host ""
Write-Info "All host ports bind to 127.0.0.1 (loopback only). If you need LAN"
Write-Info "access, edit docker-compose.yml - do not expose Ollama or AgenticPlug"
Write-Info "to a network: they have no authentication by default."
Write-Host ""
Write-Info "Next steps:"
Write-Info "  1. docker compose up -d"
Write-Info "  2. Wait for services to become healthy (docker compose ps)"
Write-Info "  3. curl http://127.0.0.1:$($env:AGENTICPLUG_PORT)/healthz"
Write-Info "  4. Smoke test:  docs/smoke-test.md"
Write-Host ""
Write-Info "GPU stack (mutually exclusive with default CPU): docker compose --profile gpu up"
Write-Info "Observability stack:                              docker compose --profile observability up"
Write-Info "To stop:    docker compose down"
Write-Info "Logs:       docker compose logs -f"
Write-Info "Rebuild:    .\setup.ps1; docker compose up --build -d"

Pop-Location
