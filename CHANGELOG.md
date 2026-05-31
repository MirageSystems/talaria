# Changelog

## 0.1.0

### Added

- Codex-only model discovery from `codex debug models`.
- Local HTTP shim for Claude Code at `/v1/models` and `/v1/messages`.
- New command `talaria smoke` for offline validation and optional live smoke.
- New command `talaria setup` for first-run checks.
- New `talaria doctor` checks for runtime, TLS, server, security controls, and optional live probes.
- Security hardening: browser-origin rejection, JSON-only body enforcement, 8 MiB body cap, loopback default.

### Fixed

- Browser-origin and invalid `Content-Type` handling for `/v1/messages`.
- SSE parsing and streaming error propagation in Codex adapter.
- Gateway cache seeding and launch-time startup reliability.
- TLS diagnostics now treat HTTP errors from `chatgpt.com` as successful TLS establishment.
- Gateway cache writes now use private permissions and reject symlink targets.
- Upstream response conversion is capped to reduce local memory exhaustion risk.
- Upstream error responses no longer reflect raw upstream/internal messages.
