---
name: meta-hermes
description: Meta-orchestration across the ReumanLab Tailscale mesh — deploy, monitor, and coordinate Hermes agents on all nodes.
category: devops
---

# Meta-Hermes: ReumanLab Mesh Orchestration

Coordinate all Hermes instances across the ReumanLab Tailscale mesh. Each node runs Hermes Agent with mimo-v2.5-pro via xiaomi provider.

## Mesh Topology

All nodes run **fork** `alrobles/hermes-agent` (v0.16.0) at `~/.hermes/hermes-agent/venv/bin/python hermes`.
All tagged `tag:reumanlab` with cross-node SSH enabled.
Load `skill_view(name='reumanlab-mesh')` for per-node details and SSH instructions.

**Providers**: xiaomi (mimo-v2.5-pro, free), deepseek (v4-pro, free), openrouter (hundreds of models, paid). opencode-go CANCELLED.
OpenRouter Fusion available for multi-model panel + judge synthesis.

```
reumanlab-terminal (100.106.100.62) ← orchestrator [WSL]
    ├── reumanlab (100.100.245.62)      [HUB] gateway, kanban, tasks, cron — MOST POWERFUL
    ├── reumanlab-alpha (100.123.27.68) [HPC] 62GB RAM, 916GB disk, Ubuntu
    ├── reumanlab-beta (100.115.246.9)  [LIGHT] 8GB RAM, 1TB disk (reinstalling Ubuntu)
    └── reumanlab-gamma                 [GPU] Quadro P620, 3.6TB — SSH BROKEN, use ~/gamma.sh
```

**Gamma note**: SSH direct doesn't work (Tailscale AllowGroups blocks pubkey, no sudo to fix). Use shell server: `~/gamma.sh "command"`. See `reumanlab-gamma-ssh` skill for setup details.

## Providers (distributed to all nodes, Jun 2026)

| Provider | Model | Cost | Status |
|----------|-------|------|--------|
| xiaomi | mimo-v2.5-pro | Free (Token Plan) | Primary |
| deepseek | deepseek-v4-pro | Free | Fallback |
| openrouter | 100+ models | Paid (sk-or-...) | Fallback |

Fallback chain: `xiaomi → deepseek → openrouter`

API keys in `~/env/` on all nodes (mimo-key, deepseek-token, openrouter-key).
Use Python to write `.env` over SSH — shell `$(cat ...)` gets stripped. See `hermes-provider-setup` skill.

## OpenRouter Fusion (multi-model + judge)

Fusion sends a prompt to a panel of models in parallel, then a judge synthesizes structured analysis. Can be imitated for free using xiaomi + deepseek as panel, one as judge. See `hermes-provider-setup` skill → `references/openrouter-setup.md` for API details.

## Hermes Agent Paths (fork v0.16.0)

| Node | Binary Path | Python |
|------|------------|--------|
| terminal | `hermes` (in PATH) | venv |
| alpha | `~/.hermes/hermes-agent/venv/bin/python hermes` | system |
| reumanlab | `~/.hermes/hermes-agent/venv/bin/hermes` | venv |
| beta | `~/.hermes/hermes-agent/venv/bin/hermes-agent` | system 3.14 |
| gamma | `~/.hermes/hermes` (wrapper) | conda 3.13 |

### Run command on all nodes
```bash
# alpha, reumanlab, beta — direct SSH
for node in alrobles@100.123.27.68 reumanlab@100.100.245.62 reumanlab@100.115.246.9; do
    echo "=== $node ==="
    ssh $node 'your_command' 2>&1
done

# gamma — shell server (no SSH direct)
echo "=== gamma ==="
~/gamma.sh "your_command"
```

### Deploy skill to all nodes
```bash
SKILL=reumanlab-mesh
# alpha, reumanlab, beta — direct SSH
for dest in alrobles@100.123.27.68 reumanlab@100.100.245.62 reumanlab@100.115.246.9; do
    echo "=== $dest ==="
    ssh $dest "mkdir -p ~/.hermes/skills/devops/$SKILL"
    cat ~/.hermes/skills/devops/$SKILL/SKILL.md | ssh $dest "cat > ~/.hermes/skills/devops/$SKILL/SKILL.md && echo OK"
done

# gamma — via shell server (write file command)
~/gamma.sh "mkdir -p ~/.hermes/skills/devops/$SKILL"
# Note: file transfer via shell server is limited; scp alternative if tunnel supports it
```

## Node-Specific SSH

| From any node → | Command |
|-----------------|---------|
| → alpha | `ssh alrobles@reumanlab-alpha` |
| → reumanlab | `ssh reumanlab@reumanlab` |
| → beta | `ssh reumanlab@reumanlab-beta` |
| → gamma | `~/gamma.sh "command"` (shell server, no SSH direct) |

**Gamma requires shell server** — SSH direct blocked by Tailscale AllowGroups (no sudo). See `reumanlab-gamma-ssh` skill. For gamma, use `~/gamma.sh "cmd"` from reumanlab, or `ssh reumanlab '~/gamma.sh "cmd"'` from other nodes.

**File transfer to gamma**: Not possible via shell server. Use base64 encoding through gamma.sh:
```bash
b64=$(base64 -w0 /path/to/file)
~/gamma.sh "echo '$b64' | base64 -d > /dest/path/file"
```

## Resource Allocation Strategy

| Task Type | Assign To | Why |
|-----------|-----------|-----|
| GPU training (HPC scale) | alpha → SLURM | HPC cluster |
| GPU inference (small) | gamma | Quadro P620, local |
| Web scraping/API calls | beta | Light, 8GB RAM |
| Cron jobs, monitoring | reumanlab | Gateway always on |
| Interactive dev | terminal | Local workstation |
| Kaggle submissions | alpha (via SLURM) | HPC access |

## Hermes Agent Paths and Invocation

| Node | Hermes Path | Version | CLI Command |
|------|------------|---------|-------------|
| terminal | `~/.hermes/` | current | `hermes` |
| alpha | `~/.hermes/hermes-agent/venv/bin/hermes` | v0.16.0 | `~/.hermes/hermes-agent/venv/bin/hermes` |
| reumanlab | `~/.hermes/` | v0.16.0 | `~/.hermes/hermes-agent/venv/bin/hermes` |
| beta | `~/.hermes/hermes-agent/` | v0.16.0 | `~/.hermes/hermes-agent/venv/bin/hermes` |
| gamma | `~/.hermes/hermes-agent/` | v0.14.0 | `~/.hermes/hermes` (custom wrapper) |

## Bootstrapping a New Node for Meta-Hermes

When a node has Hermes but doesn't know about the mesh:

### 1. Distribute API key
```bash
# Copy from reumanlab (source of truth) — xiaomi
ssh reumanlab@100.100.245.62 'grep XIAOMI ~/.hermes/.env' | ssh USER@TARGET_IP 'cat >> ~/.hermes/.env'

# OpenRouter key
ssh reumanlab@100.100.245.62 'grep OPENROUTER ~/.hermes/.env' | ssh USER@TARGET_IP 'cat >> ~/.hermes/.env'
```
Source keys: `/home/reumanlab/env/mimo-key`, `/home/reumanlab/env/openrouter-key`

### 2. Distribute skills
```bash
SKILL=meta-hermes
ssh USER@TARGET_IP "mkdir -p ~/.hermes/skills/devops/$SKILL"
cat ~/.hermes/skills/devops/$SKILL/SKILL.md | ssh USER@TARGET_IP "cat > ~/.hermes/skills/devops/$SKILL/SKILL.md"
```
Distribute all three: `reumanlab-mesh`, `reumanlab-gamma-ssh`, `meta-hermes`.

### 3. Verify
```bash
ssh USER@TARGET_IP 'HERMES_CLI -z "Carga el skill meta-hermes y dime los nodos de la malla"'
```

## Common Pitfalls

1. **Skills copied but Hermes doesn't know about mesh**: The node is missing the xiaomi API key. Hermes can't load skills without a working provider. Always distribute API key with skills.
2. **Gamma SSH**: Direct SSH doesn't work (Tailscale AllowGroups blocks pubkey, no sudo). Use `~/gamma.sh "cmd"` shell server. File transfer via base64 encoding through gamma.sh.
3. **Gamma no curl**: Use `wget` instead
4. **Gamma Hermes broken**: Source tree uses system Python which lacks dependencies. Run venv repair (see `reumanlab-gamma-ssh` skill) and use `~/.hermes/hermes` wrapper.
5. **Beta no conda**: Use system Python 3.14.4
6. **Alpha Hermes path**: `/home/alrobles/.hermes/hermes-agent/venv/bin/hermes` (not in PATH, use full path)
7. **reumanlab (main) gateway**: May have active sessions — be careful with restarts

## Using as a Compute Mesh

To run a task on the best available node:
1. Check `skill_view(name='reumanlab-mesh')` for resource availability
2. Pick the best node for the task type
3. SSH and execute
4. Collect results

Example: Running LLM inference
```bash
# On gamma (GPU available)
ssh a474r867@100.105.254.1 'cd ~/llama-b9672 && LD_LIBRARY_PATH=. ./llama-cli -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf -p "Your prompt" -n 100 -ngl 99 --no-display-prompt'
```
