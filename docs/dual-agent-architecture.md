# EcoSeek Dual-Agent Architecture: Emily Local + Hermes Remote

## Overview

EcoSeek operates a **dual-agent** system where a lightweight local agent (Emily)
handles routine queries and automatically escalates complex tasks to a powerful
remote agent on reumanlab.

```
User's Machine                              reumanlab (remote)
┌──────────────┐                           ┌──────────────────┐
│  Frontend    │                           │  Hermes Remote   │
│  (React SPA) │                           │  (DeepSeek v4)   │
│  :4000       │                           │  :8642           │
└──────┬───────┘                           │  + ku-hpc tool   │
       │                                   │  + HPC cluster   │
       ▼                                   │  + memory/skills │
┌──────────────┐       escalate_remote     └────────▲─────────┘
│  Emily Local │ ─────────────────────────────────► │
│  (Hermes)    │  POST broker.ecoseek.org           │
│  :8642       │  /v1/chat/completions              │
│  + Ollama or │ ◄──────────────────────────────────┘
│    DeepSeek  │       response
│  + ecoseek   │
│    toolset   │
└──────────────┘
```

## Components

### 1. Emily Local (Hermes instance on user's machine)

**What:** A local `hermes-agent` (from `alrobles/hermes-agent` fork) running
with a lightweight LLM.

**LLM options (user's choice):**
- **Ollama local**: `qwen2.5:14b-instruct-q4_K_M` (GPU) or `qwen2.5:1.5b` (CPU)
- **DeepSeek API (BYOK)**: User provides their own DeepSeek API key
- **HPC Ollama**: Tunnel to KU HPC GPU node via `ku-hpc` + SSH tunnel

**Configuration** (`~/.hermes/config.yaml`):
```yaml
agent:
  personalities:
    emily:
      system: |
        You are Emily, an expert ecological scientist and AI assistant for EcoSeek.
        Your specialties: ecological niche modeling (ENM), species distribution
        models (SDMs), biogeography, GBIF biodiversity data, phylogenetics,
        R/Python for ecological analysis.
        You are warm, knowledgeable, and passionate about biodiversity.
        You always suggest reproducible workflows and cite data sources.
        When a task requires heavy computation, HPC resources, or access to
        reumanlab tools, use the escalate_remote tool to delegate to the
        remote Hermes agent.
      style: scientific

  toolsets:
    - hermes-cli
    - ecoseek          # custom toolset (see below)

display:
  personality: emily
```

**Custom toolset** (`~/.hermes/plugins/ecoseek/plugin.yaml`):
```yaml
name: ecoseek
version: 0.1.0
description: EcoSeek ecological tools and remote escalation
tools:
  - escalate_remote
  - gbif_query        # future: direct GBIF API queries
  - sdm_pipeline      # future: local SDM workflow
```

### 2. Hermes Remote (existing, on reumanlab)

**What:** The existing Hermes instance already running on reumanlab with
DeepSeek v4 Pro, `ku-hpc` access, and full tool capabilities.

**No changes needed** — it already:
- Runs on port 8642
- Accepts OpenAI-compatible requests
- Has tools: terminal, ku-hpc, web search, file ops
- Is exposed via `broker.ecoseek.org` (Cloudflare tunnel)

### 3. Broker (AgenticPlug)

**Current routing** (from PR #114):
```
Frontend → broker.ecoseek.org/v1/chat/completions → Hermes Remote
```

**New routing** for dual-agent:
```
Frontend → Emily Local → (decides) → either respond directly
                                    → or escalate_remote → broker → Hermes Remote
```

The frontend talks to Emily Local (`:8642`) instead of the broker directly.
Emily Local uses `escalate_remote` tool to call broker when needed.

## Implementation: `escalate_remote` Tool

A Hermes plugin tool that calls the remote Hermes via the broker API:

```python
# ~/.hermes/plugins/ecoseek/__init__.py
import json, os, urllib.request
from tools.registry import registry

BROKER_URL = os.getenv("ECOSEEK_BROKER_URL", "https://broker.ecoseek.org")
BROKER_KEY = os.getenv("ECOSEEK_BROKER_KEY", "")

def escalate_remote(task: str, context: str = "", task_id: str = None) -> str:
    """Send a task to the remote Hermes agent on reumanlab."""
    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": task})

    body = json.dumps({
        "model": "hermes",
        "messages": messages,
    }).encode()

    req = urllib.request.Request(
        f"{BROKER_URL}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {BROKER_KEY}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        return json.dumps({
            "success": True,
            "remote_response": content,
            "model": data.get("model", "unknown"),
        })

registry.register(
    name="escalate_remote",
    toolset="ecoseek",
    schema={
        "name": "escalate_remote",
        "description": (
            "Escalate a task to the remote Hermes agent on reumanlab. "
            "Use this when the task requires: heavy computation (HPC), "
            "access to reumanlab resources, specialized ecological tools, "
            "or capabilities beyond your local LLM."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task to send to the remote agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context or system instructions for the remote agent.",
                },
            },
            "required": ["task"],
        },
    },
    handler=lambda args, **kw: escalate_remote(
        task=args.get("task", ""),
        context=args.get("context", ""),
        task_id=kw.get("task_id"),
    ),
)
```

## Escalation Criteria

Emily Local decides to escalate when:

| Trigger | Example |
|---------|---------|
| HPC computation needed | "Run MaxEnt on 10,000 occurrence records" |
| Large dataset processing | "Download all GBIF mammal records for Mexico" |
| Access to reumanlab tools | "Check the Slurm queue", "Submit a training job" |
| Complex multi-step orchestration | "Build a full SDM pipeline with cross-validation" |
| Model limitations | Query exceeds local LLM's capability |

Emily handles locally:
- Simple Q&A about ecology, methods, species
- Code generation (R/Python snippets)
- Explaining concepts, reviewing manuscripts
- Quick GBIF API lookups
- Planning and suggesting workflows

## Deployment

### Phase 1: Docker-based (immediate)

```bash
# docker-compose.yml adds Emily as a service
# Uses Ollama for local inference + escalate_remote for heavy tasks
docker compose --profile emily up -d
```

### Phase 2: Native install (for power users)

```bash
# Install hermes-agent from alrobles/hermes-agent fork
curl -fsSL https://raw.githubusercontent.com/alrobles/hermes-agent/main/scripts/install.sh | bash

# Configure Emily persona + ecoseek plugin
hermes config set display.personality emily
hermes config set agent.personalities.emily.system "You are Emily..."

# Set broker credentials
echo "ECOSEEK_BROKER_URL=https://broker.ecoseek.org" >> ~/.hermes/.env
echo "ECOSEEK_BROKER_KEY=<session_id>" >> ~/.hermes/.env
```

### Phase 3: Frontend integration

Update the React frontend to talk to Emily Local instead of the broker:
```javascript
// broker.js — change default to local Emily
const BROKER_URL = process.env.REACT_APP_BROKER_URL || "http://localhost:8642";
```

The frontend sends messages to Emily Local's API server (OpenAI-compatible).
Emily decides whether to respond locally or escalate to the remote.

## Advantages

1. **Cost**: Most queries handled by free local LLM, only complex tasks use DeepSeek API
2. **Speed**: Local responses are instant, no network latency for simple queries
3. **Privacy**: User data stays local unless explicitly escalated
4. **Resilience**: Works offline for basic ecological Q&A
5. **Scalability**: Emily's personality and tools can grow independently

## Dependencies

- `alrobles/hermes-agent` — Emily's runtime (fork of NousResearch/hermes-agent)
- `alrobles/agenticplug` — broker for auth + remote forwarding
- `alrobles/hermes-agent` (Hermes) — remote gateway at hermes.ecoseek.org
- `alrobles/ecoseek` — frontend + docker-compose orchestration

## Future: EcoAgent Integration

When `ecoagent` is ready, Emily Local gains direct access to 25+ ecological
tools via MCP (Model Context Protocol). The architecture becomes:

```
Emily Local → EcoAgent MCP server → GBIF, SDM, phylo tools (local)
Emily Local → escalate_remote → Hermes Remote → ku-hpc → HPC cluster
```
