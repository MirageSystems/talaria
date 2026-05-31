# Talaria Troubleshooting

## claude not found

Install Claude Code:

```bash
npm install -g @anthropic-ai/claude-code
```

## codex not logged in

Run:

```bash
codex login
```

Then confirm:

```bash
codex login status
```

## Empty model catalog

Check:

```bash
codex debug models
```

Ensure your account has visible Codex models.

## TLS errors with chatgpt.com

Run:

```bash
talaria doctor
```

and fix local Python CA trust store, then retry.

## Claude cannot discover models

Confirm the gateway cache is writable:

```bash
ls -la ~/.claude/cache/gateway-models.json
```

Re-run setup/doctor and then `talaria`.

