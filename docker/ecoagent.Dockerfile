# EcoAgent tool server — self-contained build.
# Clones the repo at build time so no sibling checkout is needed on the host.
#
#   docker build -f docker/ecoagent.Dockerfile -t ecoseek-ecoagent .
#
# To pin a specific commit or branch, pass --build-arg ECOAGENT_REF=<sha|branch>

# ── Stage 1: builder ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ARG ECOAGENT_REPO=https://github.com/alrobles/ecoagent.git
ARG ECOAGENT_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch "${ECOAGENT_REF}" "${ECOAGENT_REPO}" . \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefix=/install ".[full,test]"

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="EcoAgent"
LABEL org.opencontainers.image.source="https://github.com/alrobles/ecoagent"

RUN groupadd --gid 1000 ecoagent \
    && useradd --uid 1000 --gid ecoagent --create-home ecoagent

COPY --from=builder /install /usr/local
COPY --from=builder /build/src/ /opt/ecoagent/src/
COPY --from=builder /build/pyproject.toml /build/README.md /opt/ecoagent/
COPY --from=builder /build/config/ /opt/ecoagent/config/

WORKDIR /opt/ecoagent
RUN pip install --no-cache-dir -e "."

ENV ECOAGENT_PROFILE=ci \
    ECOAGENT_PORT=8100 \
    ECOAGENT_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8100

USER ecoagent

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/v1/tools')"

CMD ["python", "-m", "ecoagent.tool_server", "--host", "0.0.0.0", "--port", "8100"]
