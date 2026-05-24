# EcoSeek Plugin — DiDAL Phase 2

Emily (Alpha, local) ↔ Hermes (Beta, remote on reumanlab) via `hermes.ecoseek.org`.

## Tools

| Tool | Description |
|------|-------------|
| `hermes_status` | Check if Hermes Beta is available |
| `escalate_remote` | One-shot delegation to Beta (simple tasks) |
| `dialectical_exchange` | DiDAL structured debate (complex multi-step tasks) |

## Setup

```bash
# Pass your Hermes API key when starting Emily:
HERMES_ECOSEEK_API_KEY=agenticplu... DEEPSEEK_API_KEY=sk-... bash emily-start.sh
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_REMOTE_URL` | `https://hermes.ecoseek.org` | Remote Hermes endpoint |
| `HERMES_ECOSEEK_API_KEY` | *(required for escalation)* | API key for hermes.ecoseek.org |
| `HERMES_REMOTE_MODEL` | `hermes` | Model name on the remote |
| `HERMES_REMOTE_TIMEOUT` | `300` | Request timeout in seconds |
| `DIDAL_MAX_TURNS` | `12` | Max dialectical dialogue turns |
| `DIDAL_STUCK_THRESHOLD` | `3` | Repeated errors before stopping |

## Architecture

```
User → localhost:4000 (frontend)
         → localhost:8642 (Emily/Alpha)
              → hermes.ecoseek.org (Hermes/Beta on reumanlab)
                   → eco_analyze (GBIF, SDM, diversity, taxonomy)
                   → ku_hpc (Slurm → A100/MI210 GPUs)
                   → shell, GitHub CLI, DeepSeek v4 Pro
```

## When Emily escalates to Beta

- Heavy computation (HPC cluster, GPU jobs, model training)
- Ecological pipelines (SDMs, MaxEnt, phylogenetics, GBIF bulk downloads)
- Large dataset processing (spatial analysis, raster operations)
- Code execution on reumanlab infrastructure
- Tasks requiring DeepSeek v4 Pro reasoning

## When Emily handles locally

- Simple Q&A about ecology, species, methods
- Generating short code snippets (R/Python)
- Explaining concepts, reviewing manuscripts
- Quick calculations, literature guidance
