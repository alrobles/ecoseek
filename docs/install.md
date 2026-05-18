# Install

> **Status: alpha / stub.** There is no installable EcoSeek product yet. This document describes how to set up a *local, mocked* environment for development and review. **Do not use real secrets, real API keys, or real production data with EcoSeek at this stage.**

## What you can do today

- Read the documentation in this repository and the related repos linked from the [README](../README.md).
- Run the companion components (AgenticPlug, EcoCoder, EcoAgent) in their own repositories in their own development modes, where they exist.
- Wire them together against **mock** providers — no real DeepSeek key, no real cloud calls.

## What you should not do today

- Point EcoSeek at a real BYOK provider with a real key.
- Connect EcoSeek to a shared lab AgenticPlug.
- Use EcoSeek to handle data you would not be comfortable losing or leaking.
- Expose any EcoSeek component on a public network or behind a tunnel that bypasses local-only assumptions.

## Local / mock setup (target shape)

The intended local development flow, once the companion repos catch up, is:

1. **Clone the relevant repos** under a single parent directory:
   - `alrobles/agenticplug`
   - `alrobles/ecoagent`
   - `alrobles/ecocoder`
   - `alrobles/knowledgebase` (read-only references)
2. **Run AgenticPlug in local-only mode.** No real keys configured. The gateway should refuse outbound calls that require credentials it does not have.
3. **Run a local model substrate** (inherited from the AgenticSeek fork — see [`alrobles/agenticSeek`](https://github.com/alrobles/agenticSeek)).
4. **Author a trivial agent in EcoCoder** that performs a deterministic, offline task (e.g. transform a small input file).
5. **Run it under EcoAgent**, pointed at the local AgenticPlug.
6. **Inspect the audit log** AgenticPlug emits. The gateway's audit trail is the source of truth for what happened.

Each of these steps will be documented in the respective companion repository as it stabilizes.

## BYOK (when you are ready, and not before)

When BYOK is documented as supported (not yet):

- Configure your API key **only** inside AgenticPlug, using its documented configuration surface.
- Do not commit the key, do not put it in an environment variable that other processes inherit, do not paste it into chat logs.
- Verify in AgenticPlug's audit output that the key is being used only for the providers and actors you expect.
- Rotate the key on a schedule that matches your provider's recommendations.

## Reporting setup issues

If something here is wrong, unclear, or unsafe, open an issue against this repository. Do not include logs that contain secrets; redact aggressively.
