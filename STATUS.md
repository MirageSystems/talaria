# Status

## 2026-06-01 02:45 [SECURITY] pre-test hardening

Before live testing, reviewed the local gateway security boundary and fixed:

- Codex CLI status parsing when `codex login status` writes to stderr.
- Browser-origin POST rejection on `/v1/messages`.
- `Content-Type: application/json` enforcement for message requests.
- 8 MiB request body cap.
- Pinned Codex backend URL; no environment override can receive the Codex bearer token.
- Removed shell-based npm wrapper Python override.
- Changed upstream SSE parsing to yield incrementally instead of buffering the full stream.

Validation:
- `python3 -m compileall talaria tests`
- `python3 -m unittest discover -s tests -v` (13 tests)
- `npm test`
- `python3 -m talaria.cli doctor`
- `node bin/talaria.js doctor`

## 2026-06-01 02:28 [IMPLEMENTATION] talaria runtime committed

Implemented a Codex-only runtime in this repo:

- `talaria` package (`catalog`, `codex`, `translate`, `server`, `doctor`, `cli`).
- Local-only auth path via `~/.codex/auth.json` and `codex` command checks; no OpenAI API key flow.
- Gateway cache seeding + launcher flow for `talaria` default and `talaria serve`.
- Minimal npm wrapper and CI pipeline for compile + test.
- Offline test coverage in `tests/test_runtime.py`.

Commit:
- `28dc9f1` (signed)

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
