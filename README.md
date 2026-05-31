# Talaria

Talaria is a local Claude Code gateway that routes Claude to visible Codex models
from your existing `codex login` session.

Talaria is intentionally minimal:

- No `OPENAI_API_KEY` mode.
- No Anthropic API passthrough.
- No OpenRouter, Ollama, or local model provider routes.

## Requirements

- Python 3.10+
- Codex CLI logged into ChatGPT (`codex login`)
- Claude Code (`claude`)

## Install

```bash
npm install -g @miragesystems/talaria
```

From source:

```bash
node bin/talaria.js
```

## Quickstart

```bash
codex login
talaria doctor
talaria setup
talaria
```

In Claude Code, open `/model` and select one of the `claude-*` aliases.

## Commands

- `talaria` – run preflight checks and launch Claude Code.
- `talaria setup` – run first-run diagnostics and show next actions.
- `talaria doctor` – detailed diagnostics.
- `talaria doctor --live --model <alias>` – optional live end-to-end check.
- `talaria smoke` – local smoke test without model usage.
- `talaria smoke --live --model <alias>` – optional local + upstream smoke.
- `talaria serve` – run gateway only (`Ctrl-C` to stop).

### Launch flags

- `--host <host>` (default `127.0.0.1`)
- `--port <port>` (default `8141`)
- `--dangerously-skip-permission` (maps to Claude Code `--dangerously-skip-permissions`)
- `--help` (passed through to Claude when running `talaria`)

## Security model

- Local-only by default (`127.0.0.1` / `localhost`).
- Browser-origin and non-JSON message requests are rejected.
- Message body cap: 8 MiB.
- Codex backend is hard-pinned: `https://chatgpt.com/backend-api/codex/responses`.
- Token material only from local `~/.codex/auth.json`.

## Testing

```bash
python3 -m compileall talaria tests
python3 -m unittest discover -s tests -v
npm test
```

## Release and docs

- `CHANGELOG.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `docs/RELEASE.md`
- `docs/TROUBLESHOOTING.md`

## License

MIT
