# Emily — EcoSeek local ecological AI assistant
# Runs the Hermes agent fork with the ecoseek plugin and Emily personality.
#
# Build:
#   docker build -t emily .
#
# Run:
#   docker run -d -p 8642:8642 \
#     -e ECOSEEK_BROKER_URL=https://broker.ecoseek.org \
#     -e ECOSEEK_BROKER_KEY=<key> \
#     emily

FROM python:3.11-slim

LABEL maintainer="EcoSeek <alrobles@ku.edu>"
LABEL description="Emily — EcoSeek ecological AI assistant (Hermes agent)"

# System deps for hermes-agent
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install hermes-agent from the EcoSeek fork
RUN pip install --no-cache-dir \
    "git+https://github.com/alrobles/hermes-agent.git@main#egg=hermes-agent"

# Create hermes home directory
RUN mkdir -p /root/.hermes/plugins /root/.hermes/skills /root/.hermes/logs

# Copy Emily configuration
COPY config.yaml /root/.hermes/config.yaml
COPY plugins/ /root/.hermes/plugins/
COPY skills/ /root/.hermes/skills/

# Emily gateway listens on 8642
EXPOSE 8642

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -sf http://localhost:8642/health || exit 1

# Start the Hermes API gateway
CMD ["hermes", "gateway", "run", "--api-only"]
