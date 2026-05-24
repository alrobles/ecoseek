# ── Build stage ──────────────────────────────────────────────────────
FROM node:18-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG REACT_APP_BROKER_URL=https://broker.ecoseek.org
ENV REACT_APP_BROKER_URL=$REACT_APP_BROKER_URL

RUN npm run build

# ── Serve stage ──────────────────────────────────────────────────────
FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html

# SPA fallback — all routes serve index.html (React Router / callback)
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  location / {\n    try_files $uri $uri/ /index.html;\n  }\n}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
