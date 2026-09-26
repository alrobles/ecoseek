# Fresh-Install Runbook — EcoSeek F2 Customer Test

> **Status:** in progress — second attempt running 2026-09-25 on
> reumanlab-terminal (node recovered; Docker daemon healthy, snap group fix
> persisted). First-attempt findings below are REAL (observed 2026-09-04).
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

## Remaining steps (when the target is back)

```bash
# 1. Verify daemon + group
docker info >/dev/null && echo OK

# 2. Fresh clone + customer path (literal)
rm -rf ~/ecoseek-fresh-test && git clone --depth 1 https://github.com/alrobles/ecoseek.git ~/ecoseek-fresh-test
cd ~/ecoseek-fresh-test
CI=1 bash setup.sh                 # or: cp .env.example .env (then fill keys)
docker compose up -d --build       # core stack: emily, ecoseek-api, ecoagent, ollama, searxng, redis

# 3. Health
docker compose ps                  # all healthy
curl -s http://127.0.0.1:3000/     # ecoseek-api status ok
curl -s http://127.0.0.1:8642/health  # emily

# 4. Canonical smoke
bash scripts/smoke.sh              # Emily /health → API / → EcoAgent /v1/tools → chat via /v1/query

# 5. Frontend profile
docker compose --profile frontend up -d --build
curl -sI http://127.0.0.1:4000/ | head -1

# 6. Time-to-value: record `date` at clone start and at first successful chat.
```

## Definition of Done (from #127)

- [ ] Target has git + Docker only (no pre-existing ecoSeek state)
- [ ] No undocumented steps in clone → .env → up
- [ ] `scripts/smoke.sh` passes in full
- [ ] `--profile frontend` builds and serves; chat round-trips through nginx
- [ ] Every deviation fixed and committed back; this runbook updated
- [ ] Time-to-value recorded