# AgenticPlug broker — builds from a local checkout.
# The setup script clones agenticplug into .repos/agenticplug/ before
# building, so Docker never needs GitHub credentials.
#
#   # Automatic (recommended):
#   bash setup.sh
#
#   # Manual:
#   git clone https://github.com/alrobles/agenticplug.git .repos/agenticplug
#   docker compose up --build

FROM node:18-slim

RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN npm install --production \
    && apt-get purge -y python3 make g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* .git

# BROKER_SESSION_STORE defaults to sqlite for alpha (persistent across
# restarts via the broker-data volume mounted at /data in compose).
# Override at runtime with `-e BROKER_SESSION_STORE=memory` for tests
# or dev where ephemeral state is acceptable.
ENV BROKER_PORT=3000 \
    BROKER_SESSION_STORE=sqlite

EXPOSE ${BROKER_PORT}

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:'+(process.env.BROKER_PORT||3000)+'/healthz', r => { process.exit(r.statusCode === 200 ? 0 : 1) }).on('error', () => process.exit(1))"

CMD ["node", "broker/server.js"]
