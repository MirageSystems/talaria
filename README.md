# Talaria

Run Claude Code with the Codex models available through your ChatGPT subscription.

Talaria is a small local shim for developers who use Claude Code but want to route model calls through their existing `codex login` account. It does not use `OPENAI_API_KEY`, OpenAI Platform billing, Anthropic passthrough, OpenRouter, Ollama, or local model backends.

## Status

Early development. The first public release will focus on one path:

```text
Claude Code -> Talaria local shim -> Codex subscription models
```

## Scope

- Discover available Codex models from `codex debug models`.
- Expose only visible, account-confirmed Codex models in Claude Code's `/model` menu.
- Authenticate only through `codex login`.
- Keep the runtime small, dependency-light, and testable offline.

## Install

Installation instructions will be added with the first release.

## License

MIT
