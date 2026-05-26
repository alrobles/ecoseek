# NOTICE

## License

EcoSeek as a combined work is distributed under the **GNU Affero General Public License v3.0** (AGPLv3).
See [LICENSE](./LICENSE) for the full text.

**Copyright holders:** EcoSeek maintainers and contributors.

## Why AGPLv3

AGPLv3 was chosen because:

1. **Upstream compatibility.** EcoSeek incorporates GPLv3-licensed code from [AgenticSeek](https://github.com/Fosowl/agenticSeek) (via the fork alrobles/agenticseek). AGPLv3 is fully compatible with GPLv3 as a derivative license — it adds the network-use clause without conflicting with GPLv3 obligations.

2. **SaaS protection.** The Affero clause ensures that anyone offering EcoSeek as a network service must also provide their modifications to users of that service. This keeps the platform open regardless of how it's deployed.

3. **Scientific open access.** EcoSeek exists to advance ecological research. AGPLv3 guarantees that improvements — whether models, analysis pipelines, or agent capabilities — flow back to the scientific community.

## Upstream dependencies and attribution

| Dependency | Upstream | License | Relationship |
|---|---|---|---|
| AgenticSeek fork | [Fosowl/agenticSeek](https://github.com/Fosowl/agenticSeek) | GPL-3.0 | Base system (connector, gateway, agent runtime). Modified and extended. |
| Hermes Agent | [nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent) | MIT | Orchestrator, memory, skills, tool system. Integrated as-is. |

- **AgenticSeek-derived files** (under `.repos/agenticplug/`, `connector/`, and the gateway layer) are modifications of GPLv3 code. They remain under GPLv3+AGPLv3 as part of the combined work.
- **Hermes Agent** is MIT-licensed. Its inclusion does not impose additional restrictions.
- **EcoSeek-original components** (EcoCoder, EcoAgent, Emily, R workspace, benchmark tools, Docker infrastructure, CI/CD) are licensed under AGPLv3.

## No relicensing of AgenticSeek-derived code

Files originating from the AgenticSeek fork carry GPLv3 attribution obligations. They are distributed as part of the combined AGPLv3 work — this does not relicense the GPLv3 portions, it extends them with AGPLv3 for the aggregate distribution as permitted by GPLv3 §13.

## Trademarks and naming

"EcoSeek", "AgenticPlug", "EcoCoder", "EcoAgent", and "Emily" are project names used by this repository's maintainers. "AgenticSeek", "DeepSeek", "Hermes Agent", and "Nous Research" are names belonging to their respective upstream projects and are referenced here only for attribution and interoperability. No affiliation or endorsement is claimed.

## License decision

Decided 2026-05-26. See commit history for this file. The previous "undecided / source-available" notice is superseded by this document and the accompanying LICENSE file.
