# Fresh-Install Runbook — EcoSeek F2 Customer Test

> **Status:** PASS — second attempt completed 2026-09-26 on
> reumanlab-terminal (node recovered; Docker daemon healthy, snap group fix
> persisted). `smoke.sh` green and frontend chat round-trip verified.
> Three blocking bugs found and fixed in-repo (#137, #138, #139).
> **Owner:** Angel Robles · **Issue:** #127 · **Roadmap:** F2

## Goal

Prove the customer promise: `git clone → .env → docker compose up -d` on a
machine that never ran EcoSeek, then `bash scripts/smoke.sh` green.

## Target

- **Node:** reumanlab-terminal (100.65.103.68, tagged-devices), user `alrobles`
- **Specs:** 8 cores, 30 GB RAM, 166 GB free disk
- **OS:** Ubuntu with Docker installed via **snap** (revision 3579)

## Findings so far (real, from first attempt)

### F2-FIND-01 · Docker daemon not running / not reachable for the user
- `docker --version` works (CLI present) but `docker info` fails:
  - First: `Docker daemon is not running. Start Docker Desktop and try again.`
    (setup.sh's prerequisite check)
  - Then: `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`
- **Root cause A (daemon):** on Ubuntu, Docker from **snap** starts dockerd via
  snapd, NOT via `systemctl start docker` (`docker.service` does not exist).
  `sudo snap restart docker` is the correct way to (re)start it.
- **Root cause B (permissions):** the snap socket `/var/run/docker.sock` is
  `root:root 660` and the system group `docker` did not exist. Fix applied:
  ```bash
  sudo groupadd --system docker
  sudo usermod -aG docker alrobles
  sudo snap restart docker
  ```
- **Side effect observed:** immediately after `sudo snap restart docker`,
  the node dropped off Tailscale (`offline, last seen …`) and SSH to
  100.65.103.68 times out. Suspected: snap restart disturbed networking or the
  host rebooted; REQUIRES physical/interactive recovery — not repeatable from
  the mesh while the node is down. **Takeaway for the runbook:** do the snap
  docker group fix in an interactive session / with console access, or
  document it as a one-time prerequisite performed by the admin.

### F2-FIND-02 · setup.sh run order (CI mode)
- `CI=1 ARCEE_API_KEY= bash setup.sh` runs correctly when the daemon is up:
  it skips prompts, writes `.env` (0600), and clones `.repos/ecoagent`.
- On this node it aborted at the `docker info` check (expected, see FIND-01).

### F2-FIND-03 · `docker compose up --build` fails — emily image can't build (second attempt, 2026-09-25)
- `pip install git+https://github.com/alrobles/hermes-agent.git@main` in
  `emily/Dockerfile` aborts: upstream `setup.py` (synced in via
  alrobles/hermes-agent#22, v2026.8.18) raises `RuntimeError` on
  `bdist_wheel`/`sdist` outside a Nix build — a wheel would ship without
  bundled assets (locales, skills, plugin manifests) that resolve from the
  source-checkout layout at runtime.
- CI never caught it: `docker-compose.ci.yml` mocks emily with
  `nginx:alpine` — the real Dockerfile is never built in CI.
- **Fix (PR #137):** clone the fork to `/opt/hermes-agent` and
  `pip install -e` — editable installs use `build_editable` (not
  `bdist_wheel`) and keep the runtime asset layout. Verified: image builds,
  gateway boots.
- **Customer-facing note:** the stack *cannot* have worked for any external
  customer between 2026-08-20 (upstream sync) and this fix — only existing
  deployments with prebuilt images were unaffected.

### F2-FIND-04 · Test environment carried ambient API keys (second attempt)
- The test shell exported `ARCEE_API_KEY`/`ENTREZ_API_KEY`, so
  `CI=1 bash setup.sh` wrote real keys into `.env` ("configured" in the
  summary). A customer without keys takes the local-only Ollama path; this
  run exercises the BYOK path. Noted for honesty — the clone/build/smoke
  steps are identical either way.
- Prior-state caveat: this node hosts the dev checkout
  (`~/GitHub/ecoseek`) but had **zero** ecoseek Docker state (no images,
  volumes, or `~/.ecoseek`) — the compose build was a genuine cold build.

### F2-FIND-05 · `ecoagent` crash-loops — package unreadable by uid 1000 (second attempt)
- Symptom: `No module named ecoagent.tool_server`, container restart loop.
- Root cause: `setup.sh` sets `umask 077` (intended: `.env` at 0600), so the
  `.repos/ecoagent` clone came out 700-dirs/600-files. Docker `COPY`
  preserved those modes; the container's `ecoagent` user (uid 1000) could
  not read `/opt/ecoagent/src` — `import ecoagent` degraded to an
  unreadable namespace package → `PermissionError` → crash loop.
- **Fix (PR #138, merged `b77458d`):**
  - `setup.sh` clones `.repos/` under `umask 022` + `chmod -R a+rX`
    self-heal (re-runs repair old checkouts; `.env` still 0600).
  - `docker/ecoagent.Dockerfile` does `chmod -R a+rX /opt/ecoagent` after
    COPY — build is correct regardless of host umask.
- Verified: image built from a 700/600 context imports
  `ecoagent.tool_server` as uid 1000.

### F2-FIND-06 · Host port 8642 already in use (second attempt — environment, not a bug)
- A host-native `hermes` dev instance (pid 2524, v0.21.5) already owned
  `127.0.0.1:8642`, so `emily` could not bind.
- **Handling (no code change):** `EMILY_PORT=8643` in `.env` — compose
  publishes `127.0.0.1:8643:8642` and `smoke.sh` reads the override from
  `.env`. The dev instance was left untouched.
- Runbook note: on a shared/dev machine, pick a free `EMILY_PORT` before
  `compose up`; on a dedicated customer box the default works.

### F2-FIND-07 · Frontend nginx proxy unreachable — hardcoded `host.docker.internal:8642` (second attempt)
- Symptom: `ecoseek-frontend` served the SPA but every `/v1/*`, `/health`,
  `/api/hermes-health` call returned **502 Bad Gateway**.
- Root cause: `host.docker.internal` resolves to the docker bridge gateway
  IP (172.17.0.1), but `emily` publishes `127.0.0.1:${EMILY_PORT}` —
  loopback-only, so container→gateway-IP traffic is refused. This breaks
  the **default** customer path, not just port overrides.
- **Fix (PR #139):** new `EMILY_PROXY_TARGET` build arg (envsubst, default
  `http://emily:8642` — the compose service DNS name, always reachable on
  `ecoseek-net` regardless of host port mappings). Native-gateway
  deployments override with
  `EMILY_PROXY_TARGET=http://host.docker.internal:<port>`.
- Verified: rebuilt image → `GET :4000/health` → `{"status":"ok"}` and a
  real `POST :4000/v1/chat/completions` round-trip returned assistant text
  (`hermes-fast` → "pong").

### F2-FIND-08 · Frontend image tech-debt (second attempt — non-blocking)
- `node:18-alpine` base vs packages wanting `node>=20` (EBADENGINE
  warnings: cross-env, pdfjs-dist, rimraf, lru-cache) — build still
  succeeds.
- `npm audit`: 64 vulnerabilities (3 critical) in the CRA toolchain —
  expected for `react-scripts` era; schedule a Vite migration or audit
  pass separately. Not an F2 blocker.

## Steps executed (second attempt, 2026-09-26 — all green)

```bash
# 1. Verify daemon + group
docker info >/dev/null && echo OK                      # PASS

# 2. Fresh clone + customer path (literal)
git clone --depth 1 https://github.com/alrobles/ecoseek.git ~/ecoseek-fresh-test
cd ~/ecoseek-fresh-test
CI=1 bash setup.sh                                     # PASS (.env 0600, ecoagent cloned)
docker compose up -d --build                           # PASS after #137/#138 fixes

# 3. Health
docker compose ps                  # all 6 services healthy — PASS
curl -s http://127.0.0.1:3000/     # {"status":"ok"} — PASS
curl -s http://127.0.0.1:8643/health  # {"status":"ok","platform":"hermes-agent"} — PASS (EMILY_PORT=8643)

# 4. Canonical smoke
bash scripts/smoke.sh              # PASS — /health, API /, /v1/tools, chat round-trip ("pong")

# 5. Frontend profile
docker compose --profile frontend up -d --build        # PASS after #139
curl -sI http://127.0.0.1:4000/ | head -1              # 200 + SPA — PASS
curl -s http://127.0.0.1:4000/health                   # {"status":"ok"} via nginx proxy — PASS
# POST :4000/v1/chat/completions → "pong" (hermes-fast) — PASS
```

**Time-to-value:** ~70 min wall-clock from `git clone` to first chat
(23:20 → 00:31 CDT) — but that figure **includes finding, fixing,
reviewing and merging three blocking bugs** (#137, #138, #139). The clean
happy path on this hardware is ~20–25 min: clone+setup ~2 min, cold
docker build ~15 min (dominated by the ecoagent torch/CUDA wheels and the
emily editable install), `compose up`+smoke ~3 min.

## Definition of Done (from #127)

- [x] Target has git + Docker only (no pre-existing ecoSeek state)
- [x] No undocumented steps in clone → .env → up
- [x] `scripts/smoke.sh` passes in full
- [x] `--profile frontend` builds and serves; chat round-trips through nginx
- [x] Every deviation fixed and committed back; this runbook updated
- [x] Time-to-value recorded