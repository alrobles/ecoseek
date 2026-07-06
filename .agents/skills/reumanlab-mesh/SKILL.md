---
name: reumanlab-mesh
description: Complete Tailscale mesh of ReumanLab machines — connectivity, SSH, resources, and shared infrastructure.
category: devops
---

# ReumanLab Tailscale Mesh

Shared skill for managing all ReumanLab nodes on the Tailscale mesh.
Tailnet: `a.l.robles.fernandez@gmail.com`

## Node Inventory

| Node | IP | User | Role | GPU | Key Feature |
|------|-----|------|------|-----|-------------|
| reumanlab-terminal | 100.106.100.62 | alrobles | WSL workstation | — | Local dev |
| reumanlab-alpha | 100.123.27.68 | alrobles | HPC gateway | HPC GPUs | sudo NOPASSWD, SLURM |
| reumanlab | 100.100.245.62 | reumanlab | Main server | — | Hermes hub, Kaggle CLI |
| reumanlab-beta | 100.115.246.9 | reumanlab | Worker | — | 5d uptime, relay via dfw |
| reumanlab-gamma | 100.105.254.1 | a474r867 | GPU compute | Quadro P620 | 3.6TB disk, enterprise KU |

**Load gamma skill for SSH instructions:** `skill_view(name='reumanlab-gamma-ssh')`

## SSH Quick Reference

```bash
# alpha
ssh alrobles@100.123.27.68

# reumanlab (main)
ssh reumanlab@100.100.245.62

# beta
ssh reumanlab@100.115.246.9

# gamma (requires explicit bash — see reumanlab-gamma-ssh skill)
ssh -t a474r867@100.105.254.1 "/bin/bash -i"
```

## Shared Infrastructure

### mimocode API
- All machines use `mimo-v2.5-pro` via Xiaomi Mimo
- Base URL: `https://token-plan-sgp.xiaomimimo.com/v1`
- Fallback: deepseek

### Tailscale
- Tailnet admin: `a.l.robles.fernandez@gmail.com`
- API key on reumanlab: `/home/reumanlab/env/tailscale-key`
- ACL allows `autogroup:nonroot` + `root` for self SSH

### Hermes on each node
- **reumanlab**: Full deployment — gateway, skills, tasks, kanban, cron
- **reumanlab-alpha**: Minimal install
- **reumanlab-beta**: Not yet explored
- **reumanlab-gamma**: Installed, uses mimo-v2.5-pro

## Per-Node Details

### reumanlab-alpha (HPC gateway)
- Direct access to KU HPC cluster
- SLURM job management
- Kaggle submissions
- NVIDIA HPC GPUs

### reumanlab (main server)
- Kaggle CLI: `~/.local/bin/kaggle`
- Hermes gateway running
- Kanban board
- Ollama cloud models cache
- State DB: 1.4GB

### reumanlab-gamma (GPU compute)
- **GPU confirmed**: Quadro P620, CUDA 12.2, PyTorch 2.6.0+cu124, Transformers 5.12.1
- **Quick GPU check**: `bash scripts/gpu_check.sh` (in this skill) or `ssh a474r867@100.105.254.1 'bash -s' < ~/.hermes/skills/devops/reumanlab-mesh/scripts/gpu_check.sh`
- **Two inference backends**: llama.cpp Vulkan (GGUF, ~5.7 t/s) + PyTorch CUDA (Transformers)
- **Hermes**: v0.14.0 at `~/.hermes/hermes-agent/`, CLI via `~/.hermes/hermes` wrapper
- **Disk**: 3.6TB (3.4TB free)
- **RAM**: 16GB (12GB free)
- **Python**: conda 26.3.2, Python 3.13.13
- **No sudo**: enterprise KU machine
- **Internet**: Yes, public IP 129.237.90.153
- **Known quirks**:
  - No `/bin/bash -c` in SSH (use bare `ssh user@host 'cmd'`)
  - No `curl` (use `wget`)
  - Conda solver issues (use `--no-plugins` flag)
  - No gcc (can't compile from source)
- **Installed ML stack**:
  - PyTorch 2.6.0+cu124 (matrix mul verified on GPU)
  - Transformers 5.12.1 + Accelerate 1.14.0 (Qwen2.5-0.5B on CUDA, 0.99GB VRAM)
  - llama.cpp Vulkan b9672 (`/home/a474r867/llama-b9672/llama-cli`)
  - Qwen2.5-0.5B-Instruct GGUF (`/home/a474r867/models/`)
  - Qwen2.5-0.5B-Instruct HF (`~/.cache/huggingface/`)
  - **Two inference backends**: Vulkan (GGUF, 5.7 t/s) + CUDA (Transformers, 0.99GB VRAM)
  - **Full GPU setup**: `references/gamma-gpu-setup.md`
- **Internet**: Yes, public IP 129.237.90.153
- **No curl**: use `wget` instead
- **SSH quirk**: Use `ssh a474r867@... 'cmd'` (single quotes). See reumanlab-gamma-ssh skill for details.
- **Full diagnostic**: `references/gamma-diagnostic.md`

### reumanlab-beta (light worker)
- **CPU**: AMD Ryzen 5 7520U, 8c/16t
- **RAM**: 8GB (6.6GB free)
- **Disk**: 1TB (949GB free)
- **GPU**: None (Radeon integrated graphics only)
- **Python**: 3.14.4 system, no conda
- **No Docker, no Hermes installed**
- **Internet**: Yes, KU (129.237.90.179)
- **Role**: Light tasks, cron jobs, monitoring

## Common Workflows

### Skill distribution to all nodes
```bash
for node in reumanlab@100.100.245.62 alrobles@100.123.27.68 a474r867@100.105.254.1; do
  cat ~/.hermes/skills/devops/reumanlab-mesh/SKILL.md | \
    ssh "$node" 'mkdir -p ~/.hermes/skills/devops/reumanlab-mesh && cat > ~/.hermes/skills/devops/reumanlab-mesh/SKILL.md'
done
# Note: gamma requires single-quote cmd syntax, NO /bin/bash -c
```

### Check all nodes status
```bash
tailscale status | grep reumanlab
```

### Restore Tailscale ACL
```bash
curl -u "$(cat /home/reumanlab/env/tailscale-key):" \
  -X POST -H "Content-Type: application/json" \
  -d '{"grants":[{"src":["*"],"dst":["*"],"ip":["*"]}],"ssh":[{"action":"accept","src":["autogroup:member"],"dst":["autogroup:self"],"users":["autogroup:nonroot","root"]}],"nodeAttrs":[{"target":["autogroup:member"],"attr":["funnel"]}]}' \
  "https://api.tailscale.com/api/v2/tailnet/a.l.robles.fernandez@gmail.com/acl"
```

## Pitfalls

- **Gamma `/bin/bash -c` trap**: Tailscale SSH on gamma rejects explicit bash invocations. Use `ssh a474r867@... 'cmd'` with single quotes. Shell features (`&&`, `|`, `>`) work fine without explicit bash.
- **Gamma no curl**: Use `wget` instead. `conda install curl` works but the system `/usr/bin/curl` is absent.
- **NVML panic**: Don't trust `nvidia-smi` on gamma. The GPU works fine for CUDA compute. Verify with `python3 -c "import torch; print(torch.cuda.is_available())"` instead.
- **Gamma interactive**: Use `ssh -t a474r867@100.105.254.1 "/bin/bash -i"` for interactive shells (the one case where explicit bash is needed).
