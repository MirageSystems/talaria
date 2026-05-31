# Doctor++ Design

## Status

V1 release blocker.

## Goal

Upgrade `talaria doctor` from a basic prerequisite check into a reliable diagnostic command for setup, runtime, TLS, model discovery, local gateway behavior, and optional live Codex verification.

## Scope

`talaria doctor` should check:

- Python executable and version.
- Node/npm presence when useful for npm-installed Talaria.
- Claude Code CLI path and version.
- Codex CLI path and version.
- `codex login status` with stdout/stderr handling.
- Codex model catalog discovery.
- Python TLS certificate verification for `chatgpt.com`.
- Loopback server bind availability.
- Gateway cache directory writability.
- Talaria HTTP server-only smoke: `/healthz` and `/v1/models`.
- Security controls: browser-origin rejection, JSON-only message requests, body cap.

Optional:

- `talaria doctor --live`
  Sends one tiny live model prompt and verifies streaming plus non-streaming.

## Output

Keep output concise but more structured than today:

```text
Talaria doctor
python: ok (3.14.0)
claude: ok (2.1.159)
codex: ok (0.135.0)
codex login: ok
model catalog: ok (6 visible)
tls: ok (/etc/ssl/cert.pem)
gateway cache: ok
server smoke: ok
security controls: ok
live: skipped
result: pass
```

Failures should include the exact next action. Example:

```text
tls: fail
Python cannot verify chatgpt.com certificates.
Detected fallback cert file: /etc/ssl/cert.pem
Talaria can use this fallback, but your Python install should be repaired.
```

## Relationship To `talaria smoke`

Doctor++ diagnoses environment and setup. Smoke proves runtime behavior.

Doctor may call shared helper functions used by smoke, but the commands should keep distinct intent:

- `doctor`: what is wrong with my setup?
- `smoke`: does Talaria work end to end?

## Testing

Use mocked check providers for unit tests:

- all checks pass
- missing Claude Code
- Codex login emitted on stderr
- TLS default CA missing but system cert fallback present
- gateway cache not writable
- server smoke failure
- live mode upstream failure

CI should not run live mode.

## Non-Goals

- No automatic repair.
- No credential printing.
- No API key diagnostics.
- No Anthropic account diagnostics.
