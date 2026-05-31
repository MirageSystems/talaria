# First-Run Setup UX Design

## Status

V1 release blocker.

## Goal

Make the first `talaria` run understandable for a user who has installed the package but may not have Claude Code, Codex CLI, Codex login, working TLS certificates, or a writable Claude gateway cache.

The user should never see a Python traceback for expected setup problems.

## Scope

Improve the default launch path and setup diagnostics:

- Detect Python runtime compatibility.
- Detect Claude Code CLI and version.
- Detect Codex CLI and version.
- Detect ChatGPT-backed `codex login`.
- Detect visible Codex model catalog.
- Detect Python TLS certificate usability for `chatgpt.com`.
- Detect loopback bind availability for the selected host/port.
- Detect gateway cache directory writability.

## User Flow

When the user runs `talaria`, Talaria performs preflight checks before launching Claude Code. If all required checks pass, it starts the local server and launches `claude`.

If a required check fails, Talaria exits with a concise message:

```text
Talaria cannot start yet.

Missing: Claude Code CLI
Install: npm install -g @anthropic-ai/claude-code

Then run:
talaria doctor
```

For multiple failures, print them together with exact commands.

## Command Behavior

- `talaria`
  Runs preflight, starts server, seeds gateway cache, launches Claude Code.
- `talaria setup`
  Runs setup checks only and prints next steps. Does not start server.
- `talaria doctor`
  Remains the deeper diagnostic command.

If `talaria setup` overlaps with Doctor++, keep `setup` as a short first-run assistant and `doctor` as the detailed diagnostic.

## Error Design

Expected setup errors should return nonzero exit codes and plain text messages. Internal bugs should still surface enough detail for maintainers, but common user issues should be mapped to friendly remediation.

Examples:

- Missing Claude Code -> `npm install -g @anthropic-ai/claude-code`
- Missing Codex CLI -> install Codex CLI using the official instructions.
- Codex not logged in -> `codex login`
- Catalog empty -> confirm account access and run `codex debug models`
- TLS failure -> show Python certificate path and suggest Doctor++ output

## Testing

Add tests for setup result objects and rendered messages. Avoid testing by shelling out to real global CLIs in CI. Use dependency injection or mocks for version checks.

## Non-Goals

- No automatic installation of Claude Code or Codex CLI.
- No browser login automation.
- No modification of Codex auth files.
- No API key fallback.
