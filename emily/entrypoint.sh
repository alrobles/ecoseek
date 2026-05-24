#!/usr/bin/env bash
# Emily entrypoint — write API keys from Docker env vars to ~/.hermes/.env
# then start the Hermes gateway.
set -euo pipefail

ENV_FILE="/root/.hermes/.env"

# Clear previous env file
> "$ENV_FILE"

# DeepSeek API key
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    echo "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}" >> "$ENV_FILE"
    echo "[emily] DeepSeek API key configured"
fi

# Ollama base URL (override provider in config if set)
if [ -n "${OLLAMA_BASE_URL:-}" ]; then
    echo "OLLAMA_BASE_URL=${OLLAMA_BASE_URL}" >> "$ENV_FILE"
    echo "[emily] Ollama configured at ${OLLAMA_BASE_URL}"
fi

# EcoSeek broker credentials (for escalate_remote tool)
if [ -n "${ECOSEEK_BROKER_URL:-}" ]; then
    echo "ECOSEEK_BROKER_URL=${ECOSEEK_BROKER_URL}" >> "$ENV_FILE"
fi
if [ -n "${ECOSEEK_BROKER_KEY:-}" ]; then
    echo "ECOSEEK_BROKER_KEY=${ECOSEEK_BROKER_KEY}" >> "$ENV_FILE"
fi

# API server key (for authenticating frontend requests)
if [ -n "${API_SERVER_KEY:-}" ]; then
    echo "API_SERVER_KEY=${API_SERVER_KEY}" >> "$ENV_FILE"
fi

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
exec hermes gateway run --api-only
