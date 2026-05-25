#!/usr/bin/env bash
# Emily entrypoint — write API keys from Docker env vars to ~/.hermes/.env
# then start the Hermes gateway.
set -euo pipefail

ENV_FILE="/root/.hermes/.env"

# Clear previous env file
> "$ENV_FILE"

# Always enable the API server (this is how the frontend talks to Emily)
echo "API_SERVER_ENABLED=true" >> "$ENV_FILE"

# Bind to all interfaces inside Docker so port mapping works.
# Default 127.0.0.1 is the container's loopback — unreachable from the host.
echo "API_SERVER_HOST=0.0.0.0" >> "$ENV_FILE"

# DeepSeek API key and model
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    echo "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}" >> "$ENV_FILE"
    # DeepSeek V4 API requires explicit model names: deepseek-v4-pro or deepseek-v4-flash.
    # The old "deepseek-chat" name is no longer accepted.
    DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
    echo "DEEPSEEK_MODEL=${DEEPSEEK_MODEL}" >> "$ENV_FILE"
    echo "[emily] DeepSeek configured: model=${DEEPSEEK_MODEL}"
fi

# Ollama base URL (override provider in config if set)
if [ -n "${OLLAMA_BASE_URL:-}" ]; then
    echo "OLLAMA_BASE_URL=${OLLAMA_BASE_URL}" >> "$ENV_FILE"
    echo "[emily] Ollama configured at ${OLLAMA_BASE_URL}"
fi

# Hermes remote credentials (for DiDAL escalation to hermes.ecoseek.org)
if [ -n "${HERMES_ECOSEEK_API_KEY:-}" ]; then
    echo "HERMES_ECOSEEK_API_KEY=${HERMES_ECOSEEK_API_KEY}" >> "$ENV_FILE"
    echo "[emily] Hermes remote configured: key=***${HERMES_ECOSEEK_API_KEY: -4}"
fi
if [ -n "${HERMES_REMOTE_URL:-}" ]; then
    echo "HERMES_REMOTE_URL=${HERMES_REMOTE_URL}" >> "$ENV_FILE"
    echo "[emily] Hermes remote URL: ${HERMES_REMOTE_URL}"
fi
if [ -n "${HERMES_REMOTE_MODEL:-}" ]; then
    echo "HERMES_REMOTE_MODEL=${HERMES_REMOTE_MODEL}" >> "$ENV_FILE"
fi

# DiDAL Protocol v2 configuration
if [ -n "${DIDAL_ENABLED:-}" ]; then
    echo "DIDAL_ENABLED=${DIDAL_ENABLED}" >> "$ENV_FILE"
fi
if [ -n "${DIDAL_MAX_CRITIQUE_ROUNDS:-}" ]; then
    echo "DIDAL_MAX_CRITIQUE_ROUNDS=${DIDAL_MAX_CRITIQUE_ROUNDS}" >> "$ENV_FILE"
fi

# Literature retrieval configuration (BYOK)
if [ -n "${OPENALEX_MAILTO:-}" ]; then
    echo "OPENALEX_MAILTO=${OPENALEX_MAILTO}" >> "$ENV_FILE"
fi
if [ -n "${S2_API_KEY:-}" ]; then
    echo "S2_API_KEY=${S2_API_KEY}" >> "$ENV_FILE"
fi
if [ -n "${ENTREZ_API_KEY:-}" ]; then
    echo "ENTREZ_API_KEY=${ENTREZ_API_KEY}" >> "$ENV_FILE"
fi
if [ -n "${ENTREZ_EMAIL:-}" ]; then
    echo "ENTREZ_EMAIL=${ENTREZ_EMAIL}" >> "$ENV_FILE"
fi

# Legacy broker credentials (kept for backward compatibility)
if [ -n "${ECOSEEK_BROKER_URL:-}" ]; then
    echo "ECOSEEK_BROKER_URL=${ECOSEEK_BROKER_URL}" >> "$ENV_FILE"
fi
if [ -n "${ECOSEEK_BROKER_KEY:-}" ]; then
    echo "ECOSEEK_BROKER_KEY=${ECOSEEK_BROKER_KEY}" >> "$ENV_FILE"
fi

# API server key — required when binding to 0.0.0.0 (Hermes security check).
# Auto-generate if not provided; emily-start.sh passes a shared key so the
# frontend can authenticate.
if [ -z "${API_SERVER_KEY:-}" ]; then
    API_SERVER_KEY=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
    echo "[emily] Auto-generated API server key"
fi
echo "API_SERVER_KEY=${API_SERVER_KEY}" >> "$ENV_FILE"

# API server port — Hermes default is 8642 when API_SERVER_PORT is set
echo "API_SERVER_PORT=${API_SERVER_PORT:-8642}" >> "$ENV_FILE"

# CORS origins for the API server
if [ -n "${API_SERVER_CORS_ORIGINS:-}" ]; then
    echo "API_SERVER_CORS_ORIGINS=${API_SERVER_CORS_ORIGINS}" >> "$ENV_FILE"
fi

# Validate: at least one LLM backend must be configured
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -z "${OLLAMA_BASE_URL:-}" ]; then
    echo "[emily] WARNING: No LLM backend configured!"
    echo "[emily] Set DEEPSEEK_API_KEY or OLLAMA_BASE_URL."
    echo "[emily] Emily will start but cannot generate responses."
fi

echo "[emily] Starting Hermes gateway..."
exec hermes gateway run
