# Talaria Smoke Design

## Status

V1 release blocker.

## Goal

Add a `talaria smoke` command that proves Talaria works on a maintainer or user machine with one clear pass/fail report. It should make local failures obvious before a user opens Claude Code.

## Scope

`talaria smoke` verifies the full local gateway shape:

- Python runtime can import Talaria.
- Codex CLI is installed and logged in through ChatGPT.
- Codex model catalog discovery succeeds.
- A temporary Talaria server starts on a random loopback port.
- `GET /healthz` returns healthy.
- `GET /v1/models` returns at least one Claude-compatible model id.
- Security controls reject browser-origin and non-JSON message requests.
- Optional live mode sends a tiny prompt to one Codex model and verifies non-streaming and streaming responses.

The command must be safe by default. It should not consume Codex usage unless the user explicitly opts into live mode.

## Command Shape

- `talaria smoke`
  Runs offline checks only. No Codex model call.
- `talaria smoke --live`
  Runs offline checks plus one tiny non-streaming and one tiny streaming Codex request.
- `talaria smoke --model claude-gpt-5.4-mini --live`
  Uses a specific discovered model alias.

## Output

The output should be compact and terminal-friendly:

```text
Talaria smoke
python import: ok
codex login: ok
model catalog: ok (6 models)
server: ok (127.0.0.1:<random>)
healthz: ok
models: ok
security controls: ok
live non-stream: skipped
live stream: skipped
result: pass
```

In live mode, include the model alias used and whether text was received. Do not print bearer tokens, auth file contents, request bodies containing user prompts beyond the fixed smoke prompt, or full upstream event payloads.

## Error Handling

Known user-facing failures should print exact next steps:

- Missing Codex CLI: install Codex CLI.
- Not logged in: run `codex login`.
- Empty catalog: confirm the account has Codex models.
- Port/server failure: print the local bind error.
- TLS failure: run `talaria doctor` and show the certificate path diagnosis.
- Live upstream failure: print the HTTP status and sanitized upstream message.

## Testing

Add unit tests for the smoke command using mocked catalog and event stream objects. Add one integration-style offline test that starts the HTTP server on port `0` and hits `/healthz` plus `/v1/models`.

Live smoke is not run in CI. CI validates command behavior with mocks only.

## Non-Goals

- No long benchmark.
- No repeated model calls.
- No automatic Claude Code launch.
- No mutation of global Claude configuration beyond existing gateway cache behavior.
