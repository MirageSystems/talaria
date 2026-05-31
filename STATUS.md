# Status

## 2026-06-01 02:11 [PLAN] autonomous build start

Task:
- Build Talaria as a public OSS project under MirageSystems.
- Implement a Claude Code shim that routes only to Codex models available through local `codex login`.
- Keep commits short, clean, and signed.

Problems:
- Existing shims carry too much provider surface for this use case.
- Static model lists go stale and can advertise unavailable models.
- Public launch needs a clean repository, CI, docs, and predictable install path.

Dream state:
- Developers install `@miragesystems/talaria`, run `codex login`, then run `talaria`.
- Claude Code shows only their confirmed Codex models in `/model`.
- Tests and CI prove the shim behavior offline without consuming subscription usage.

Beneficiaries:
- Pushkar and MirageSystems as maintainers.
- Claude Code users who already pay for ChatGPT/Codex and want a narrow local bridge.
- OSS contributors who need a small, auditable runtime.

Why now:
- The fresh `MirageSystems/talaria` repo is initialized and signed.
- The Codex CLI exposes account-visible model catalog data through `codex debug models`.
- The project scope is intentionally narrow enough to ship cleanly.

Phases:
- Runtime core: catalog, auth provider, translation, and server.
- CLI and diagnostics: launcher, doctor, install metadata.
- Public polish: docs, CI, release-ready metadata.

Evidence:
- Baseline metadata check passed with `test -f README.md && test -f LICENSE && test -f .gitignore`.
