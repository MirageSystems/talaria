# Security Mode Defaults Design

## Status

V1 release blocker.

## Goal

Make Talaria's local security posture explicit at runtime and keep secure defaults non-negotiable. Users should be able to see that Talaria is local-only, browser-origin hardened, JSON-only, body-capped, and pinned to the Codex backend.

## Scope

On startup, Talaria should print a concise security summary:

```text
Talaria listening on http://127.0.0.1:8141
Codex backend: https://chatgpt.com/backend-api/codex/responses
Browser-origin requests: blocked
Message content type: application/json required
Request body cap: 8 MiB
Gateway cache: ~/.claude/cache/gateway-models.json
Models: claude-gpt-5.5, claude-gpt-5.4, ...
```

The summary should appear for `talaria serve` and default `talaria` launch. It should not print secrets, bearer tokens, auth file paths beyond `CODEX_HOME`, or full prompts.

## Security Invariants

These behaviors are required for v1:

- Bind to `127.0.0.1` by default.
- Reject browser-originated message requests.
- Require `Content-Type: application/json` for `POST /v1/messages`.
- Cap request bodies at 8 MiB.
- Pin Codex requests to `https://chatgpt.com/backend-api/codex/responses`.
- Do not support `OPENAI_API_KEY`.
- Do not support Anthropic passthrough.
- Do not support generic OpenAI-compatible routing.

## Configuration Policy

The following may remain configurable:

- `TALARIA_HOST`
- `TALARIA_PORT`
- `TALARIA_SERVICE_TIER`
- `TALARIA_REASONING_EFFORT`
- `TALARIA_MAX_OUTPUT_TOKENS`
- `CODEX_HOME`

The Codex backend URL must not be configurable in v1.

## Error Handling

If a user binds outside loopback, Talaria should print a warning and require an explicit unsafe flag only if the project chooses to support that later. For v1, the recommended behavior is to reject non-loopback binds.

## Testing

Add tests that assert:

- startup summary includes the security controls
- no token-like auth strings are printed
- non-loopback bind is rejected or guarded according to the final implementation choice
- existing browser-origin, content-type, body-size, and pinned-backend tests remain in place

## Non-Goals

- No TLS server on localhost.
- No authentication token between Claude Code and Talaria for v1 unless Claude Code compatibility requires it later.
- No remote/shared-host mode.
