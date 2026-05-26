# Emily — EcoSeek local ecological AI assistant
# Runs the Hermes agent fork with the ecoseek plugin and Emily personality.
#
# Build:
#   docker build -t emily-local .
#
# Run:
#   docker run -d -p 8642:8642 \
#     -e DEEPSEEK_API_KEY=sk-... \
#     -e ECOSEEK_BROKER_URL=https://broker.ecoseek.org \
#     emily-local

FROM python:3.11-slim

LABEL maintainer="EcoSeek <alrobles@ku.edu>"
LABEL description="Emily — EcoSeek ecological AI assistant (Hermes agent)"

# System deps for hermes-agent
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install hermes-agent from the EcoSeek fork.
# aiohttp is required by the gateway API server adapter but is an optional
# dependency of hermes-agent (in the "messaging" extras group).
# OpenTelemetry + OTLP exporter enable Phoenix tracing when
# PHOENIX_COLLECTOR_ENDPOINT is set (no-op otherwise).
RUN pip install --no-cache-dir \
    "git+https://github.com/alrobles/hermes-agent.git@main#egg=hermes-agent" \
    aiohttp \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http \
    opentelemetry-api \
    pdfplumber

# Create hermes home directory
RUN mkdir -p /root/.hermes/plugins /root/.hermes/skills /root/.hermes/logs

# Copy Emily configuration and entrypoint
COPY config.yaml /root/.hermes/config.yaml
COPY entrypoint.sh /app/entrypoint.sh
COPY plugins/ /root/.hermes/plugins/
COPY skills/ /root/.hermes/skills/

# Emily gateway listens on 8642
EXPOSE 8642

# Health check — longer start period to allow pip install + gateway init
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=60s \
    CMD curl -sf http://localhost:8642/health || exit 1

# Entrypoint writes .env from Docker env vars, then starts gateway
ENTRYPOINT ["/app/entrypoint.sh"]
