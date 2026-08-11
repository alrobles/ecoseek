# ── Build stage ──────────────────────────────────────────────────────
FROM node:18-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG REACT_APP_BROKER_URL=https://broker.ecoseek.org
ARG REACT_APP_EMILY_URL=
ARG REACT_APP_EMILY_KEY=
ARG REACT_APP_DEMO_MODE=
ENV REACT_APP_BROKER_URL=$REACT_APP_BROKER_URL
ENV REACT_APP_EMILY_URL=$REACT_APP_EMILY_URL
ENV REACT_APP_EMILY_KEY=$REACT_APP_EMILY_KEY
ENV REACT_APP_DEMO_MODE=$REACT_APP_DEMO_MODE

RUN npm run build

# ── Serve stage ──────────────────────────────────────────────────────
FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /tmp/nginx.conf

# La API key del gateway se inyecta en BUILD time (envsubst), nunca se
# hardcodea en el repo. Build: --build-arg EMILY_HERMES_KEY=<canonical-key>
# (para emily.ecoseek.org = API_SERVER_KEY del gateway nativo :8642).
ARG EMILY_HERMES_KEY=
RUN envsubst '${EMILY_HERMES_KEY}' < /tmp/nginx.conf > /etc/nginx/conf.d/default.conf \
    && grep -Eq 'Bearer [A-Za-z0-9_-]{8,}' /etc/nginx/conf.d/default.conf \
    || { echo "ERROR: EMILY_HERMES_KEY build-arg vacío — build abortado"; exit 1; }

RUN mkdir -p /workspace

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
