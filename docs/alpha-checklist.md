# Alpha checklist

EcoSeek is pre-alpha. This checklist is the honest accounting of where things stand and the gate for the first public alpha. It is meant to be uncomfortable: nothing here is a marketing claim, and "mocked" and "unsafe" appear on purpose.

## What works

- The documentation shell in this repository.
- The high-level architecture (three layers: substrate, gateway, intelligence) is articulated and consistent across docs.
- The product modes (DIY / BYOK / Lab-managed) are defined.
- The relationship to upstream AgenticSeek is acknowledged, attributed, and license-aware.

## What is mocked or partial

- **AgenticPlug gateway.** The trust boundary exists in design only. There is no production-grade auth, no real BYOK custody, no audit pipeline that an external reviewer could verify yet.
- **EcoCoder / EcoAgent.** The authoring and runtime surfaces are not yet pinned. Any agent written today will need to be rewritten against the final interface.
- **DeepSeek BYOK.** No working integration yet. Treat references to DeepSeek as forward-looking.
- **Knowledgebase wiring.** Not connected. Documentation references it as a future read-only source.
- **Local model substrate.** Inherited (in concept) from the AgenticSeek fork; not yet exercised end-to-end through the EcoSeek gateway.
- **Reproducibility hooks.** Designed, not implemented. Seeds, dataset pins, and environment captures do not yet land in any artifact.

## What is unsafe or not production

- **No real secrets.** Do not configure EcoSeek (or any component) with a real API key, OAuth token, or production credential.
- **No public exposure.** Do not expose AgenticPlug or EcoAgent on a public network. There is no hardened auth yet.
- **No multi-user assumptions.** Lab-managed mode is a future target, not a current capability. Treat every install as single-user, single-machine.
- **No data handling guarantees.** Any data you give EcoSeek now may end up in logs, working directories, or — if you misconfigure a substrate — in cloud calls you did not intend.
- **No security review.** No external review of AgenticPlug's gating logic has happened. The audit trail is not yet structured for after-the-fact verification.
- **License is undecided.** See [`NOTICE.md`](../NOTICE.md). Until that is resolved, do not redistribute.

## Minimum alpha demo

The bar for calling something an "alpha" is a single end-to-end path that a reviewer can run and inspect:

1. A reviewer clones the relevant repos and runs EcoSeek in **DIY mode** with no real secrets.
2. EcoAgent loads a tiny EcoCoder-authored scientific agent.
3. The agent makes at least one call through AgenticPlug to a local model substrate.
4. AgenticPlug emits an audit log entry that names the actor, the requested action, the policy decision, and the timestamp — without leaking any inputs that look like secrets.
5. The reviewer can re-run the agent and get a deterministic-enough result to compare against the previous run.

If any of the five fails, it is not alpha yet.

## Before public alpha

Even after the minimum demo works internally, the following must be true before anything is published as a public alpha:

- [ ] Final license decision committed to the repository and reflected in `NOTICE.md`.
- [ ] All AgenticSeek-derived code in any EcoSeek component carries its GPLv3 headers and is identifiable.
- [ ] A written threat model in [`security.md`](./security.md) (replacing the current placeholder).
- [ ] A documented BYOK flow that has been exercised with at least one provider, with keys held only by AgenticPlug.
- [ ] An audit log format that a second person, not the author, can read and reason about.
- [ ] A "how to report a security issue" contact published in `security.md`.
- [ ] A clear public statement that EcoSeek is not affiliated with or endorsed by AgenticSeek or DeepSeek.
- [ ] At least one independent reviewer has run the minimum alpha demo and confirmed each step.

Until every box is checked, the project stays pre-alpha, regardless of how good the demo looks.
