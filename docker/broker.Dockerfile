# AgenticPlug broker — self-contained build.
# Clones the repo at build time so no sibling checkout is needed on the host.
#
#   docker build -f docker/broker.Dockerfile -t ecoseek-broker .
#
# To pin a specific commit or branch, pass --build-arg AGENTICPLUG_REF=<sha|branch>

FROM node:18-slim

ARG AGENTICPLUG_REPO=https://github.com/alrobles/agenticplug.git
ARG AGENTICPLUG_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends git python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone --depth 1 --branch "${AGENTICPLUG_REF}" "${AGENTICPLUG_REPO}" . \
    && npm install --production \
    && apt-get purge -y git python3 make g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* .git

ENV BROKER_PORT=3000 \
    BROKER_SESSION_STORE=memory

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', r => { process.exit(r.statusCode === 200 ? 0 : 1) }).on('error', () => process.exit(1))"

CMD ["node", "broker/server.js"]
