# Security posture

EcoSeek is pre-alpha. This document describes the **target** security posture and the rules contributors must follow today, even before the product is finished. If a rule here conflicts with code in the repository, the rule wins and the code is a bug.

## No secrets in the repository

- No API keys, no tokens, no signed URLs, no private tunnel hostnames, no `.env` files with real values, no service-account JSON.
- This applies to commits, PR descriptions, issue comments, code comments, and docs.
- Use placeholders (`YOUR_DEEPSEEK_API_KEY`) and document the *shape* of a secret, never an example value that could be mistaken for a real one.
- If a secret is committed by accident, rotate it first, then remove it from history. Do not assume that deleting the file is sufficient.

## BYOK key rules

For users who supply their own keys (e.g. DeepSeek):

1. **Custody.** Keys are held only by AgenticPlug, the gateway. EcoAgent and EcoCoder never read a raw key.
2. **Scope.** A key is bound to the AgenticPlug instance that received it. It is not synced, backed up to a third party, or transmitted to any service other than the provider it targets.
3. **Lifecycle.** Keys can be rotated or revoked from AgenticPlug without rebuilding any other component. Revocation must be reflected immediately in subsequent gateway calls.
4. **Visibility.** AgenticPlug must be able to answer "which keys do you currently hold, and when was each last used?" without exposing the key material itself.
5. **Lab-managed exception.** In lab-managed mode, the lab's operator holds the keys on behalf of users. Users still never see raw keys.

## AgenticPlug auth principle

> Every call that crosses the gateway has an identified caller and an explicit policy decision.

Concretely:

- Intelligence-layer code (EcoAgent / EcoCoder) authenticates to AgenticPlug as a specific actor (a user, a lab member, or a local-only DIY identity).
- The gateway maps the actor to a policy and decides whether the requested action is allowed for that actor in the current mode.
- Decisions are logged with enough detail to reconstruct *who asked for what, when, and what the gateway said*. Logs must not contain the secrets the call depended on.
- "Allow all" is not a valid default. The gateway must fail closed when no policy matches.

## Risky actions are gated

The following are considered risky and must go through the gateway, not be performed directly by intelligence-layer code:

- Any outbound network call.
- Any use of a stored secret (BYOK key, OAuth token, signed identity).
- Any filesystem write outside the agent's declared workspace.
- Any shell or process exec.
- Any action that can spend money, send a message, or otherwise affect a third party.

The gateway's job for these calls is not to silently allow or silently deny — it is to make an explicit, auditable decision based on the caller, the requested action, and the active policy.

## Threat model placeholder

A full threat model is not yet written. Until it is, contributors should assume:

- The user's machine is trusted; the network is not.
- The intelligence layer can be tricked by adversarial inputs (prompt injection, malicious tool output). It must not be the thing that decides whether to release a secret or perform a risky action — the gateway is.
- Upstream model providers are honest-but-curious. Do not send them data that the user has not explicitly authorized.

## Reporting

EcoSeek does not yet have a public security contact. Until one is published here, report suspected issues by opening a **private** issue in the relevant repository, or contacting the maintainers directly through the channel they used to invite you to the project.
