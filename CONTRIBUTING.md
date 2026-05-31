# Contributing to Talaria

## Local setup

- Python 3.10+
- Node.js 18+

```bash
python3 -m compileall talaria tests
python3 -m unittest discover -s tests -v
npm test
```

## PR style

- Keep diffs focused and minimal.
- Preserve the codex-only policy.
- Add regression tests for behavior changes.

## Security expectations

- No OpenAI key mode.
- No Anthropic passthrough.
- No additional provider backends without maintainer discussion.

## Release etiquette

- Prefer signed commits when preparing release branches.
- Update version, changelog, and docs together.

