# ecoSeek Architecture — June 2026

## Domain Map

```
emily.ecoseek.org ─── Cloudflare Tunnel ─── :4000 (Docker React SPA)
chat.ecoseek.org  ─── Cloudflare Tunnel ─── :3001 (Open WebUI + Hermes)
hermes.ecoseek.org ── Cloudflare Tunnel ─── :8642 (Hermes API server)
monitor.ecoseek.org ─ Cloudflare Tunnel ─── :9200 (ClusterPulse dashboard)
broker.ecoseek.org ── Cloudflare Tunnel ─── :9092 (AgenticPlug broker)
```

All services bind to 127.0.0.1 — no direct exposure. Cloudflare Tunnel handles HTTPS, DNS, and DDoS protection.

## Cluster Nodes (Tailscale Mesh)

| Node | Cores | RAM | GPU | Tailscale IP |
|------|-------|-----|-----|-------------|
| reumanlab | 22 | 62GB | RTX 2000 Ada 8GB | 127.0.0.1 (local) |
| reumanlab-beta | 8 | 7.4GB | — | 100.115.246.9 |
| reumanlab-terminal | 8 | 15GB | — | 100.106.100.62 |
| **Total** | **38** | **84GB** | **1 GPU** | |

## Emily Frontend

- **Repo:** `alrobles/ecoseek` → `frontend/`
- **Tech:** React SPA, nginx, Docker
- **Auth:** GitHub OAuth via broker.ecoseek.org
- **Chat:** Hermes API at hermes.ecoseek.org/v1
- **System prompt:** Emily ecological scientist persona with cluster awareness

### Build & Deploy

```bash
cd ecoseek
docker build \
  --build-arg REACT_APP_BROKER_URL=https://broker.ecoseek.org \
  --build-arg REACT_APP_EMILY_URL=https://hermes.ecoseek.org \
  --build-arg REACT_APP_EMILY_KEY=<api-key> \
  -t ecoseek-frontend frontend/

docker run -d --name ecoseek-frontend \
  -p 127.0.0.1:4000:80 \
  --restart unless-stopped ecoseek-frontend
```

## ClusterPulse Monitor

- **Repo:** `alrobles/ecoseek-monitor`
- **Tech:** Python FastAPI, psutil, vanilla JS dashboard
- **Auth:** GitHub OAuth (same OAuth App as Emily)
- **Architecture:** Collector (per node, :9100) → Aggregator (:9200) → Dashboard

## Hermes Backend

- **Model:** DeepSeek v4 Pro (reasoning_effort=high)
- **Fallback:** OpenCode Go → OpenCode → DeepSeek
- **API key:** agenticplug-local-... (61 chars)
- **Profiles:** default (main), emily (ecological + skills)

## Task Bridge

- **Path:** ~/.hermes/task-bridge/server.py
- **Port:** :8643
- **Functions:** /health, /tasks, /v1/* → Hermes :8642 proxy

## Cloudflare Tunnel Config

Path: /etc/cloudflared/config.yml
Tunnel ID: 154c1f8f-ad87-4dbe-b949-cf8a067dd4f9

```yaml
ingress:
  - hostname: reumanlab.ecoseek.org  → :3101
  - hostname: hermes.ecoseek.org     → :8642
  - hostname: broker.ecoseek.org     → :9092
  - hostname: chat.ecoseek.org       → :3001
  - hostname: emily.ecoseek.org      → :4000
  - hostname: monitor.ecoseek.org    → :9200
  - service: http_status:404
```

## Security

- All ports bound to 127.0.0.1 (no external exposure)
- Cloudflare Tunnel provides TLS termination + DDoS protection
- GitHub OAuth on monitor + Emily frontend
- ufw firewall active
- Tailscale mesh encrypted between nodes
- No gateway/messaging platforms (attack surface reduction)
