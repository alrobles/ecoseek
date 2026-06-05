# Emily Production Deployment — State as of 2026-06-04

## emily.ecoseek.org — Full Stack

```
Browser → Cloudflare Tunnel (154c1f8f) → :4000 → ecoseek-frontend (nginx :80)
                                                    ├── / → React SPA (static files)
                                                    ├── /v1/* → proxy to emily:8642
                                                    └── /health → proxy to emily:8642
                                                              │
                                                    ┌─────────┘
                                                    ▼
                                              Emily container (emily-net, :8642)
                                              Hermes Gateway + API Server
                                              DeepSeek V4 Pro backend
                                              DiDAL Protocol v2
```

## Container Inventory

| Container | Image | Network | Ports | Restart |
|---|---|---|---|---|
| ecoseek-frontend | ecoseek-frontend-v2 | emily-net | 127.0.0.1:4000→80 | unless-stopped |
| emily | emily-ecoseek | emily-net | :8642 (internal) | unless-stopped |

## Key Configuration

### Cloudflare Ingress (`/etc/cloudflared/config.yml`)
```yaml
- hostname: emily.ecoseek.org
  service: http://127.0.0.1:4000
```

### Emily Container
- **Image**: `emily-ecoseek` (built from `/home/reumanlab/ecoseek/emily/`)
- **API key**: `API_SERVER_KEY=emily-ecoseek-key-2026`
- **Volume**: `emily-data-v2:/root/.hermes` (persistent memory, skills, sessions)
- **DeepSeek**: `deepseek-v4-pro`
- **Gateway**: `GATEWAY_ALLOW_ALL_USERS=true` (public-facing, auth via API key)
- **Entrypoint**: `/app/entrypoint.sh` writes `.env` then runs `hermes gateway run`

### Frontend Container
- **Image**: `ecoseek-frontend-v2` (built from `/home/reumanlab/ecoseek/frontend/`)
- **Build args**:
  - `REACT_APP_BROKER_URL=https://broker.ecoseek.org`
  - `REACT_APP_EMILY_URL=https://emily.ecoseek.org`
  - `REACT_APP_EMILY_KEY=emily-ecoseek-key-2026`
- **nginx config**: proxies `/v1/*` and `/health` to `emily:8642` on emily-net
- **Chat flow**: Auth via broker (GitHub OAuth), chat via Emily (same domain, nginx proxy)

### Broker CORS
`/etc/agenticplug-broker/env` includes `https://emily.ecoseek.org` in `CORS_ORIGINS`

## Rebuild Commands

### Frontend
```bash
cd /home/reumanlab/ecoseek
docker build \
  --build-arg REACT_APP_BROKER_URL=https://broker.ecoseek.org \
  --build-arg REACT_APP_EMILY_URL=https://emily.ecoseek.org \
  --build-arg REACT_APP_EMILY_KEY=emily-ecoseek-key-2026 \
  -t ecoseek-frontend-v2 \
  frontend/

docker stop ecoseek-frontend && docker rm ecoseek-frontend
docker run -d --name ecoseek-frontend --network emily-net \
  -p 127.0.0.1:4000:80 --restart unless-stopped ecoseek-frontend-v2
```

### Emily
```bash
cd /home/reumanlab/ecoseek
docker build -t emily-ecoseek emily/

docker stop emily && docker rm emily
DS_KEY=$(cat /home/reumanlab/env/deepseek-token | tr -d '\n')
docker run -d --name emily --network emily-net \
  -e DEEPSEEK_API_KEY=$DS_KEY \
  -e DEEPSEEK_MODEL=deepseek-v4-pro \
  -e API_SERVER_KEY=emily-ecoseek-key-2026 \
  -e API_SERVER_PORT=8642 \
  -e API_SERVER_HOST=0.0.0.0 \
  -v emily-data-v2:/root/.hermes \
  --restart unless-stopped \
  emily-ecoseek
```

## Verification
```bash
# Health
curl -s https://emily.ecoseek.org/health
# → {"status":"ok","platform":"hermes-agent"}

# Models
curl -s https://emily.ecoseek.org/v1/models \
  -H "Authorization: Bearer emily-ecoseek-key-2026"
# → 3 models listed

# Chat
curl -s https://emily.ecoseek.org/v1/chat/completions \
  -H "Authorization: Bearer emily-ecoseek-key-2026" \
  -H "Content-Type: application/json" \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"Hola"}]}'
# → 200, Emily responds in Spanish
```

## Pitfalls Fixed

1. **nginx no proxying /health or /v1/**: Old image had only `/api/hermes-health` proxy.
   Fixed: rebuilt with correct `frontend/nginx.conf` that proxies `/v1/*` and `/health` to `emily:8642`.

2. **Frontend on wrong Docker network**: Old frontend was on `bridge`, Emily on `emily-net`.
   Fixed: redeployed frontend on `emily-net` so nginx can reach `emily:8642`.

3. **GATEWAY_ALLOW_ALL_USERS not set**: Gateway rejected chat users with 403 ("No user allowlists configured").
   Fixed: added `GATEWAY_ALLOW_ALL_USERS=true` to entrypoint.sh, rebuilt and redeployed Emily container.

4. **EMILY_URL empty in frontend build**: Frontend was using broker for chat instead of the nginx proxy.
   Fixed: rebuilt with `REACT_APP_EMILY_URL=https://emily.ecoseek.org`.

## Git Commits
- `89e82e1` fix(emily): set GATEWAY_ALLOW_ALL_USERS=true in entrypoint.sh (branch `feat/emily-frontend-proxy`)
