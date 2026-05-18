# EcoAgent tool server — builds from a local checkout.
# The setup script clones ecoagent into .repos/ecoagent/ before
# building, so Docker never needs GitHub credentials.
#
#   # Automatic (recommended):
#   bash setup.sh
#
#   # Manual:
#   git clone https://github.com/alrobles/ecoagent.git .repos/ecoagent
#   docker compose up --build

# ── Stage 1: builder ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY . .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
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
