# Upstream Tracking

EcoSeek is built on forks of two upstream projects. This document tracks the fork strategy and sync procedures.

## Repositories

| EcoSeek fork | Upstream | Role |
|---|---|---|
| [alrobles/agenticSeek](https://github.com/alrobles/agenticSeek) | [Fosowl/agenticSeek](https://github.com/Fosowl/agenticSeek) | Client foundation (API, agents, frontend) |
| [alrobles/agenticplug](https://github.com/alrobles/agenticplug) | (original, no upstream) | Secure gateway and connector layer |

## Fork strategy: agenticSeek

`alrobles/agenticSeek` is a fork of `Fosowl/agenticSeek`. We maintain our own modifications while staying compatible with upstream improvements.

### Our modifications (on top of upstream)

- **DeepSeek BYOK provider** — Fernet-encrypted local keystore for API keys
- **EcoCoder local/cluster providers** — domain-specialized ecological LLM integration
- **AgenticPlug connector discovery** — runtime service registration
- **Sandbox security hardening** — save_block jail, entrypoint safety, TruffleHog pre-commit
- **EcoSeek entrypoint** — scientific agent orchestration

### Syncing with upstream

```bash
cd agenticSeek

# Add upstream remote (one-time)
git remote add upstream https://github.com/Fosowl/agenticSeek.git

# Fetch upstream changes
git fetch upstream

# Merge upstream main into our main
git checkout main
git merge upstream/main

# Resolve conflicts if any, then push
git push origin main
```

### When to sync

- Before each EcoSeek release
- When upstream adds features we want (new agents, browser improvements, etc.)
- Monthly check at minimum

### Conflict-prone areas

These files are likely to have merge conflicts since we've modified them:

- `sources/llm_provider.py` — we added BYOK, EcoCoder, and AgenticPlug providers
- `config.ini` — we added EcoSeek-specific provider configurations
- `api.py` — we added AgenticPlug task endpoints
- `requirements.txt` — we may have added/changed dependencies

## TODO

- [ ] Set up automated upstream sync check (GitHub Action or scheduled Devin session)
- [ ] Create a `CHANGELOG-ecoseek.md` in agenticSeek to track our divergence from upstream
- [ ] Evaluate upstreaming non-EcoSeek-specific improvements back to Fosowl/agenticSeek
- [ ] Consider using `git rebase` instead of `git merge` for cleaner history (discuss with team)

## agenticplug

`alrobles/agenticplug` is an original project (not a fork). It serves as the secure gateway layer for EcoSeek. All development happens directly on this repo.
