# Model Picker Aliases Design

## Status

V1 release blocker.

## Goal

Freeze stable Claude Code-compatible model aliases for v1 so users can pick Codex models from `/model` without confusing names or future churn.

## Background

Claude Code gateway discovery filters model ids and expects aliases that look like Claude/Anthropic model ids. Talaria currently maps Codex slugs directly:

- `gpt-5.5` -> `claude-gpt-5.5`
- `gpt-5.4-mini` -> `claude-gpt-5.4-mini`

This is simple and working, but v1 should decide whether to keep direct aliases or adopt more branded Codex aliases.

## Options

Recommended v1 option: keep direct aliases.

Direct aliases are predictable, account-derived, and avoid churn:

- `claude-gpt-5.5`
- `claude-gpt-5.4`
- `claude-gpt-5.4-mini`
- `claude-gpt-5.3-codex`
- `claude-gpt-5.3-codex-spark`
- `claude-gpt-5.2`

Alternative branded aliases:

- `claude-codex-gpt-5.5`
- `claude-codex-gpt-5.4-mini`
- `claude-codex-spark`

This is more readable but creates a second naming layer and may make user reports harder to map back to `codex debug models`.

## V1 Decision

Use direct aliases for v1 and improve `display_name` instead of changing ids. The alias should be deterministic:

```text
claude-<codex-slug>
```

The display name can remain the Codex catalog display name. If the catalog omits display name, use the slug.

## Compatibility Rules

- Alias ids must remain stable across launches for the same Codex slug.
- Hidden models from `codex debug models` must not be exposed.
- Broken catalog entries without a slug must be ignored.
- V1 should not allow user-defined alias remapping.

## Testing

Existing catalog tests should remain and expand to cover:

- deterministic alias mapping
- hidden model filtering
- display name fallback
- catalog order preservation
- no duplicate aliases if duplicate slugs appear

## Non-Goals

- No custom user alias config.
- No static model list.
- No manual model pinning outside the visible Codex catalog.
