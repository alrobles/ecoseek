# Upstream credits

EcoSeek is an independent downstream scientific adaptation built on top of a fork of **AgenticSeek**. The upstream project and its contributors are the reason this work is possible.

## AgenticSeek

- Upstream project: [AgenticSeek](https://github.com/Fosowl/agenticSeek)
- License: GNU General Public License v3.0 (GPLv3)
- Fork used by EcoSeek: [`alrobles/agenticSeek`](https://github.com/alrobles/agenticSeek)

EcoSeek relies on AgenticSeek for foundational ideas and (over time) code in areas such as:

- the core agent loop and tool-use scaffolding
- browser and research interaction patterns
- local-first model orchestration
- prompt and behavior templates

Where AgenticSeek-derived code is incorporated, EcoSeek will:

1. Preserve original copyright and license headers.
2. Keep the GPLv3 license intact for the derivative files.
3. Document any modifications, in line with GPLv3 §5.

## Acknowledgements

Thank you to the AgenticSeek authors and to every contributor whose pull requests, issues, and discussions shaped the upstream project. EcoSeek is a derivative effort with a different audience (scientific labs, reproducibility-focused workflows), but it stands on the work of that community.

## Disclaimer

EcoSeek is **not** affiliated with, endorsed by, or maintained by the AgenticSeek project. References to AgenticSeek in this repository are attribution, not endorsement. Issues with EcoSeek should be filed against EcoSeek, not upstream.

## Other referenced projects

- **DeepSeek** — optional BYOK provider for stronger low-cost reasoning. EcoSeek does not embed DeepSeek code; it integrates with the DeepSeek API when the user supplies their own key. Not affiliated with DeepSeek.
- Local model runtimes and libraries used by the AgenticSeek fork will be credited in their respective module-level NOTICE entries as code lands in this repository.
