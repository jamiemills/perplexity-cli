# Security Policy

## Reporting Vulnerabilities

Please report security issues privately to the maintainer instead of opening a public issue.

- Contact: Jamie Mills <jamie.mills@gmail.com>

Include:

- affected version
- reproduction steps
- impact assessment
- any suggested mitigation

## Token and Cookie Handling

- Authentication tokens and optional browser cookies are stored in local encrypted files.
- This storage is machine-bound and deterministic; it reduces portability of copied files but is not equivalent to OS-backed secret storage.
- Browser cookies should be treated as sensitive session material and only stored when needed.

## Safe Testing

- The default test suite is isolated from real user config.
- Tests that intentionally use real user config must be explicitly marked and opt-in.

## Releases and Supply Chain

- PyPI publishing uses GitHub Actions with OIDC trusted publishing.
- Maintainers should run `sh .claude/scripts/release-check.sh` before tagging a release.

## Changelog Source

GitHub Releases are the authoritative public changelog for this project.
