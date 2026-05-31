# Talaria Release Process

## Versioning

- Follow semver.
- Update `package.json`, `CHANGELOG.md`, and release notes together.

## Pre-release checks

```bash
python3 -m compileall talaria tests
python3 -m unittest discover -s tests -v
npm test
python3 -m talaria.cli doctor
talaria smoke
talaria smoke --live
npm pack --dry-run
```

## Release

```bash
npm publish --access public
git tag -s vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --generate-notes
```

## Post-release

- Run a quick smoke check on clean shell.
- Verify publish package page and installation.

