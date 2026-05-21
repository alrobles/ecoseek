# reumanlab Connector — Deployment Guide

Tracking issue: [alrobles/agenticplug#82](https://github.com/alrobles/agenticplug/issues/82).  
Contract reference: [kuhpc-connector-contract.md](https://github.com/alrobles/agenticplug/blob/main/docs/kuhpc-connector-contract.md).

---

## Overview

The reumanlab connector is a persistent Node.js service that runs on the
`reumanlab` workstation. It exposes the Phase 3 read-only capabilities to
EcoSeek via AgenticPlug, and relays bounded commands to KU-HPC over SSH.

```
EcoSeek (laptop)
  └─► AgenticPlug broker  (HTTPS, OAuth)
        └─► reumanlab connector  (bearer token, local/tunnel)
              └─► KU-HPC  (SSH, Slurm)
```

---

## Prerequisites

- **Node.js ≥ 18** on the reumanlab workstation.
- **SSH key** with access to `hpc.crc.ku.edu` (no passphrase, or via
  `ssh-agent`). The key path is configured via `HPC_SSH_KEY`.
- **`known_hosts`** entry for the HPC host.

---

## 1. Install

```bash
# Clone the ecoseek repo (or pull the connector directory)
cd /home/reumanlab
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek/connector/reumanlab

# No npm install needed — zero external dependencies
node --version  # must be >= 18
```

---

## 2. Configure

Create an environment file at a **protected** location. This file must
**not** be committed to any repository.

```bash
sudo mkdir -p /etc/reumanlab-connector
sudo tee /etc/reumanlab-connector/env > /dev/null << 'EOF'
# Required — connector fails closed without these
HPC_USER=a474r867
HPC_HOST=hpc.crc.ku.edu
CONNECTOR_TOKEN=<generate-a-strong-random-token>

# Optional
CONNECTOR_ID=reumanlab
CONNECTOR_PORT=8000
CONNECTOR_HOST=127.0.0.1
HPC_ALLOWED_LOG_PATHS=/home/a474r867/work,/home/a474r867/scratch
COMMAND_TIMEOUT_MS=30000
MAX_OUTPUT_BYTES=1048576
HPC_SSH_KEY=/home/reumanlab/.ssh/id_ed25519_hpc
EOF

# Lock permissions — only root and the service user can read
sudo chmod 600 /etc/reumanlab-connector/env
```

Generate a strong token:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 3. systemd Service

Create the unit file:

```bash
sudo tee /etc/systemd/system/reumanlab-connector.service > /dev/null << 'EOF'
[Unit]
Description=reumanlab connector for AgenticPlug Phase 3
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=reumanlab
Group=reumanlab
WorkingDirectory=/home/reumanlab/ecoseek/connector/reumanlab
EnvironmentFile=/etc/reumanlab-connector/env
ExecStart=/usr/bin/node main.js

# Restart on failure with back-off
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ReadOnlyPaths=/
ReadWritePaths=/var/log

# Resource limits
LimitNOFILE=1024
MemoryMax=256M

# Logging to journald (structured JSON)
StandardOutput=journal
StandardError=journal
SyslogIdentifier=reumanlab-connector

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable reumanlab-connector
sudo systemctl start reumanlab-connector
```

---

## 4. Verify

```bash
# Check service status
sudo systemctl status reumanlab-connector

# Check structured logs
journalctl -u reumanlab-connector --no-pager -n 20

# Health probe (unauthenticated)
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
# Expected: {"status": "ok", "connector_id": "reumanlab"}

# Authenticated capability test
TOKEN="<your-connector-token>"
curl -s -X POST http://127.0.0.1:8000/v1/capabilities \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"capability":"remote.health","payload":{}}' | python3 -m json.tool
# Expected: {"status": "ok", "connector_id": "reumanlab", "version": "0.3.0", ...}
```

---

## 5. Recovery

### Connector stops / crashes

systemd `Restart=on-failure` with 5 s back-off handles transient crashes.
Check logs:

```bash
journalctl -u reumanlab-connector --since "1 hour ago" --no-pager
```

### Tunnel / transport drops

If the Cloudflare tunnel between the broker and reumanlab drops:

1. The broker will see task timeouts for `connector_id: reumanlab`.
2. The connector itself stays running — it only listens locally.
3. Once the tunnel re-establishes, traffic resumes automatically.

### Configuration changes

After editing `/etc/reumanlab-connector/env`:

```bash
sudo systemctl restart reumanlab-connector
```

The connector will fail closed and refuse to start if any required
variable is removed.

### SSH key rotation

1. Generate a new key pair on reumanlab.
2. Add the public key to `~/.ssh/authorized_keys` on KU-HPC.
3. Update `HPC_SSH_KEY` in the env file.
4. Restart the service.

---

## 6. Security Notes

- The env file at `/etc/reumanlab-connector/env` contains the bearer
  token and is the **only** place secrets are stored. It is **never**
  committed to any repository.
- The connector binds to `127.0.0.1` by default. External access is
  only via the Cloudflare tunnel (terminated by the broker).
- All error messages returned to callers are sanitized per the contract
  (§4.2): no hostnames, IPs, paths, or tokens leak.
- Write capabilities (`hpc.submit`, `hpc.cancel`, `hpc.write`,
  `hpc.delete`) are hard-disabled (HTTP 501) in Phase 3.
- The systemd unit runs with `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, and `PrivateTmp=true`.

---

## 7. Running Tests

```bash
cd /path/to/ecoseek
node test/reumanlab-connector.test.js
```

Tests run with mock SSH — no real HPC connection needed.
