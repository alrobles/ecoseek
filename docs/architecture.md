# Architecture

EcoSeek is structured as a **three-layer architecture** with a clear trust boundary between layers. This document describes the layers, their responsibilities, and the supported product modes.

**Last updated:** 2026-05-23, after Phoenix tracing instrumentation (Sprint 0).

For the full canonical architecture with ADRs, see the [knowledgebase architecture doc](https://github.com/alrobles/knowledgebase/blob/main/plans/ecoSeek/architecture.md).

## Three layers

```
+---------------------------------------------------------------+
|  Layer 3: Intelligence                                         |
|  EcoCoder (authoring & inference)  +  EcoAgent (runtime)      |
|  Scientific agents, 30+ ecological tools, OpenAI-compat API   |
|  Repos: alrobles/ecocoder, alrobles/ecoagent                  |
+---------------------------------------------------------------+
                        |
                        | typed calls, no raw secrets
                        v
+---------------------------------------------------------------+
|  Layer 2: Gateway (AgenticPlug)                                |
|  Dual-layer auth, scoped sessions, approval workflow,          |
|  connector discovery, persistent session store, audit logging  |
|  Repo: alrobles/agenticplug                                    |
+---------------------------------------------------------------+
                        |
                        | brokered, policy-checked calls
                        v
+---------------------------------------------------------------+
|  Layer 1: Substrate                                            |
|  Local models (Ollama), browser, filesystem, OS,               |
|  DeepSeek BYOK (Fernet-encrypted keystore),                   |
|  EcoCoder cluster (via AgenticPlug), HPC (via connector),      |
|  Hermes remote orchestration (optional, via AgenticPlug)       |
|  Client: alrobles/ecoseek-client                               |
+---------------------------------------------------------------+
```

### Layer 1 — Substrate

The substrate is everything EcoSeek talks to but does not own: local model runtimes (Ollama with EcoCoder models), a controlled browser surface, the local filesystem, and — only when the user opts in — cloud LLM providers such as DeepSeek (via Fernet-encrypted BYOK keystore), remote HPC clusters (via AgenticPlug connectors), or the optional Hermes remote orchestration service.

Substrate components are assumed to be untrusted from EcoSeek's point of view. They are wrapped by the gateway, not exposed directly to the intelligence layer.

The **EcoSeek API gateway** (`backend/`) lives at this layer: it is a lightweight FastAPI service that accepts queries and routes them through AgenticPlug to Hermes, AgenticPlug chat completions, or a local OpenAI-compatible LLM, with a configurable fallback chain. It holds no secrets and performs no auth — that lives in AgenticPlug.

When `PHOENIX_ENABLED=true`, the gateway emits OpenTelemetry traces to Arize Phoenix (`--profile observability`). Every request produces a trace tree: `ecoseek.route` (routing decision + fallback chain) → `ecoseek.call.{backend}` (upstream HTTP calls with success/failure attributes). Phoenix is optional and disabled by default.

### Layer 2 — Gateway (AgenticPlug)

AgenticPlug is the only component allowed to:

- hold long-lived secrets (BYOK API keys, OAuth tokens, signed device identities)
- authenticate clients via GitHub Device Flow → opaque session ID
- enforce role-based access (`admin`, `operator`, `read_only`) and session scoping
- gate risky actions through the approval workflow (6 capabilities: submit, cancel, write, delete, credential, systemd)
- emit an audit trail of policy decisions with secret redaction
- discover and register connectors with typed capabilities

The gateway is the *single* point at which "is this allowed?" is answered. Intelligence-layer code never reads a raw key or makes an unmediated outbound call.

**Current state:** Fully functional with 600+ tests across 26 suites. See [agenticplug](https://github.com/alrobles/agenticplug).

### Layer 3 — Intelligence (EcoCoder + EcoAgent)

- **EcoCoder** exposes an OpenAI-compatible `/v1/chat/completions` endpoint for domain-specialized ecological inference. Supports local (Ollama) and cluster (AgenticPlug) backends.
- **EcoAgent** provides 30+ ecological tools (species distribution modeling, host-parasite interaction extraction, biodiversity data access, etc.) via an HTTP server with connector manifest for AgenticPlug discovery.

Both speak to the world only through AgenticPlug.

## Product modes

EcoSeek supports three deployment modes. The architecture is identical across modes; what changes is *who runs the gateway and whose keys it holds.*

| Mode | Client | Gateway | Compute | Cost |
|------|--------|---------|---------|------|
| **DIY / Community** | EcoSeek client | Optional (local or none) | EcoCoder local, Ollama, or mock | Free |
| **BYOK / BYOT** | EcoSeek client | Optional | DeepSeek API (user's key, Fernet-encrypted) | User pays provider |
| **Lab / Managed** | EcoSeek client | AgenticPlug (hosted/on-prem) | Any backend via gateway | Support fee |

### DIY

- Single user, single machine.
- AgenticPlug, EcoAgent, and any local models all run on the user's device.
- No external accounts, no BYOK. Local models only.
- Best for offline work, privacy-sensitive workflows, and demos.

### BYOK

- Single user (or small team), self-hosted.
- AgenticPlug holds the user's own keys for one or more cloud providers (DeepSeek is the recommended low-cost reasoning option, but not the only one).
- Keys are stored in a Fernet-encrypted local keystore. Keys never leave the user's machine.
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
- **Fail closed.** If auth, policy, or approval state is ambiguous, the request is denied.
- **Reproducibility hooks belong with the agent, not the model.** EcoCoder captures inputs, seeds, and tool versions; EcoAgent records what actually ran.
- **Upstream compatibility.** AgenticSeek-derived code in Layer 1 has been replaced by an independent lightweight gateway (`backend/`), eliminating the direct dependency on the agenticSeek fork.
