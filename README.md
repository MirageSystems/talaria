# Talaria

Minimal Claude Code gateway for ChatGPT/Codex subscription models.

Talaria is a local shim that routes Claude Code requests from `~/.claude` to your
Codex models through your existing `codex login` session. It does not use:

- `OPENAI_API_KEY`
- OpenAI API key billing
- Anthropic passthrough APIs
- OpenRouter / Ollama / local backends

Only models visible in `codex debug models` are exposed, and only through a
`codex`-logged-in account.

## Install

- Requirements: Python 3 and the Codex CLI (`codex`) logged into ChatGPT.
- `npm i -g @miragesystems/talaria`
- Ensure `codex login` is set up:
  - `codex login`
  - `codex login status` should show “Logged in using ChatGPT”.
- Run `talaria doctor` and `talaria`.

`talaria` starts Talaria, seeds Claude Code’s gateway cache, and launches
`claude` with gateway model discovery enabled.

## Runtime model

1. `talaria` discovers visible models with:
   - `codex login status`
   - `codex debug models`
2. Local server serves:
   - `GET /healthz`
   - `GET /v1/models`
   - `POST /v1/messages`
3. Claude Code sees those model aliases in `/model`.
4. Messages are translated to Codex Responses API payloads and streamed back as
   Anthropic Events.

## Commands

- `talaria`  
  Launches Claude Code through Talaria.
- `talaria serve`  
  Runs Talaria server only (`Ctrl+C` to stop).
- `talaria doctor`  
  Runs offline diagnostics.
- Optional launch flags:
  - `--host <host>` (default `127.0.0.1`)
  - `--port <port>` (default `8141`)
  - `--dangerously-skip-permission` (passes Claude Code's `--dangerously-skip-permissions`)
  - extra args are passed through to `claude`

## Env overrides

- `TALARIA_HOST`
- `TALARIA_PORT`
- `TALARIA_SERVICE_TIER`
- `TALARIA_REASONING_EFFORT`
- `TALARIA_MAX_OUTPUT_TOKENS`
- `TALARIA_DANGEROUSLY_SKIP_PERMISSIONS=1`
- `CODEX_HOME`

Talaria intentionally does not expose a Codex base URL override. Subscription
tokens from `codex login` are only sent to
`https://chatgpt.com/backend-api/codex/responses`.

## Local server security

Talaria binds to `127.0.0.1` by default. The message endpoint rejects
browser-originated requests, requires `Content-Type: application/json`, and caps
request bodies at 8 MiB.

## Development

- Run tests: `python3 -m unittest discover -s tests -v`
- Compile check: `python3 -m compileall talaria tests`

## License

MIT
