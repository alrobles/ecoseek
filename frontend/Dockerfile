# ── Build stage ──────────────────────────────────────────────────────
FROM node:18-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG REACT_APP_BROKER_URL=https://broker.ecoseek.org
ARG REACT_APP_EMILY_URL=
ARG REACT_APP_EMILY_KEY=
ENV REACT_APP_BROKER_URL=$REACT_APP_BROKER_URL
ENV REACT_APP_EMILY_URL=$REACT_APP_EMILY_URL
ENV REACT_APP_EMILY_KEY=$REACT_APP_EMILY_KEY

RUN npm run build

# ── Serve stage ──────────────────────────────────────────────────────
FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
