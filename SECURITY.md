# Security

## Supported Versions

Only the latest tagged release of Talaria is actively supported by this document.

## Threat Model

Talaria is a local-only bridge for Claude Code. It does not proxy or transform
authentication secrets into third-party APIs. It expects an existing local
`codex` authentication session and forwards requests to:

`https://chatgpt.com/backend-api/codex/responses`

### What Talaria intentionally does not do

- Does not accept `OPENAI_API_KEY`.
- Does not support Anthropic direct API passthrough.
- Does not support generic OpenAI-compatible providers.
- Does not support local model backends.

## Security controls

- Bound only to loopback hosts.
- Browser-origin requests are rejected on `/v1/messages`.
- `Content-Type: application/json` is required for message requests.
- Request bodies are capped at 8 MiB.
- Upstream response conversion is bounded.
- Gateway cache files are written with private permissions and symlink targets are rejected.
- Model IDs are sourced only from logged-in Codex visibility data.

## Local process boundary

Talaria v1 is intended for trusted local workstations. The gateway is loopback
only and blocks browser-origin requests, but it does not yet require a separate
gateway authentication token from non-browser local clients. Do not run Talaria
on shared machines where other local users or untrusted local processes should
not be able to connect to your loopback services.

## Reporting issues

Please open a private report with repository maintainers. Avoid posting
sensitive credentials in public issue comments.

## Deployment guidance

- Keep `talaria` installed from trusted sources only.
- Do not write or script around `~/.claude/cache/gateway-models.json`.
- If TLS verification fails for `chatgpt.com`, resolve Python trust-store issues
  before running live model commands.
