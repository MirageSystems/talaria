# Public Docs And Release Engineering Design

## Status

V1 release blocker.

## Goal

Make Talaria publishable as a serious OSS project under MirageSystems with clear installation, testing, security, contribution, and release instructions.

## Docs Scope

V1 should include:

- `README.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- release checklist in `docs/RELEASE.md`
- troubleshooting guide in `docs/TROUBLESHOOTING.md`

## README Requirements

The README should explain:

- What Talaria does in one sentence.
- What it does not do: no API keys, no Anthropic passthrough, no OpenRouter, no local models.
- Requirements: Python 3, Codex CLI logged into ChatGPT, Claude Code.
- Install:
  - published package: `npm install -g @miragesystems/talaria`
  - source checkout: `node bin/talaria.js`
- Quickstart:
  - `codex login`
  - `talaria doctor`
  - `talaria`
  - open `/model` in Claude Code
- Smoke testing:
  - `talaria smoke`
  - `talaria smoke --live`
- Security model.
- Troubleshooting links.

## Release Engineering Scope

V1 release process should define:

- version bump policy
- changelog update rule
- required checks before release
- signed commit expectation
- npm publish command
- GitHub release creation
- post-release smoke test

Minimum release checklist:

```text
python3 -m compileall talaria tests
python3 -m unittest discover -s tests -v
npm test
python3 -m talaria.cli doctor
talaria smoke
talaria smoke --live
npm pack --dry-run
npm publish --access public
gh release create vX.Y.Z
```

## Security Documentation

`SECURITY.md` should cover:

- supported versions
- how to report vulnerabilities
- local threat model
- no API key support
- token handling statement
- pinned backend statement
- browser-origin protection

## Contribution Documentation

`CONTRIBUTING.md` should cover:

- local setup
- test commands
- style expectations
- signed commits preference
- no new provider backends without maintainer discussion
- no API-key mode

## Testing

Add CI checks that required docs exist and package metadata is publishable. Do not publish from CI for v1 unless a later explicit release workflow is approved.

## Non-Goals

- No automated npm publish in v1.
- No complex release bot.
- No generated website required for v1.
