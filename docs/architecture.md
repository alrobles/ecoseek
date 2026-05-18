# Architecture

EcoSeek is structured as a **three-layer architecture** with a clear trust boundary between layers. This document describes the layers, their responsibilities, and the supported product modes. It is a target architecture; not all of it is implemented yet (see [`alpha-checklist.md`](./alpha-checklist.md)).

## Three layers

```
+------------------------------------------------------+
|  Layer 3: Intelligence                               |
|  EcoCoder (authoring)  +  EcoAgent (runtime)         |
|  Scientific agents, tools, evaluation harnesses      |
+------------------------------------------------------+
                        |
                        | typed calls, no raw secrets
                        v
+------------------------------------------------------+
|  Layer 2: Gateway                                    |
|  AgenticPlug                                         |
|  Auth, BYOK secret custody, action gating, audit     |
+------------------------------------------------------+
                        |
                        | brokered, policy-checked calls
                        v
+------------------------------------------------------+
|  Layer 1: Substrate                                  |
|  Local models, browser, filesystem, OS,              |
|  optional cloud providers (DeepSeek, etc.)           |
+------------------------------------------------------+
```

### Layer 1 — Substrate

The substrate is everything EcoSeek talks to but does not own: local model runtimes (e.g. llama.cpp / Ollama-style backends inherited from the AgenticSeek fork), a controlled browser surface, the local filesystem, and — only when the user opts in — cloud LLM providers such as DeepSeek.

Substrate components are assumed to be untrusted from EcoSeek's point of view. They are wrapped by the gateway, not exposed directly to the intelligence layer.

### Layer 2 — Gateway (AgenticPlug)

AgenticPlug is the only component allowed to:

- hold long-lived secrets (BYOK API keys, OAuth tokens, signed device identities)
- authenticate clients (a developer's EcoCoder session, a lab user's EcoAgent runtime)
- decide whether a risky action (filesystem write outside a workspace, outbound network call, shell exec, key use) is allowed for the current actor and context
- emit an audit trail of those decisions

The gateway is the *single* point at which "is this allowed?" is answered. Intelligence-layer code never reads a raw key or makes an unmediated outbound call.

### Layer 3 — Intelligence (EcoCoder + EcoAgent)

- **EcoCoder** is the developer surface: scaffolds for writing new scientific agents and tools, local evaluation, reproducibility hooks (seeds, dataset pins, environment captures).
- **EcoAgent** is the runtime that loads an EcoCoder-authored agent and executes it against the gateway. It is the thing a lab user actually runs.

Both speak to the world only through AgenticPlug.

## Product modes

EcoSeek supports three deployment modes. The architecture is identical across modes; what changes is *who runs the gateway and whose keys it holds.*

### DIY

- Single user, single machine.
- AgenticPlug, EcoAgent, and any local models all run on the user's device.
- No external accounts, no BYOK. Local models only.
- Best for offline work, privacy-sensitive workflows, and demos.

### BYOK

- Single user (or small team), self-hosted.
- AgenticPlug holds the user's own keys for one or more cloud providers (DeepSeek is the recommended low-cost reasoning option, but not the only one).
- Keys never leave the user's AgenticPlug. EcoAgent receives results, not keys.
- Best for individuals who want frontier-quality reasoning without giving credentials to the intelligence layer.

### Lab-managed

- Multiple users share an AgenticPlug operated by a lab, institution, or research group.
- The gateway authenticates lab members and brokers access to lab-owned keys, datasets, and compute.
- Audit and policy live in AgenticPlug. Members do not handle keys directly.
- Best for shared scientific work where reproducibility and accountability matter.

## Cross-cutting principles

- **Local-first by default.** Cloud providers are optional and gated.
- **No secrets above the gateway.** Intelligence-layer code must be runnable against a mocked gateway with no real keys.
- **Risky actions are gated, not hidden.** The gateway makes refusals explicit and auditable, rather than silently sandboxing.
- **Reproducibility hooks belong with the agent, not the model.** EcoCoder captures inputs, seeds, and tool versions; EcoAgent records what actually ran.
- **Upstream compatibility.** AgenticSeek-derived code in Layer 1 is kept GPLv3-clean and identifiable, so upstream changes can be tracked.
