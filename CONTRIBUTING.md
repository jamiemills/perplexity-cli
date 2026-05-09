# Contributing

## Development Setup

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv run lefthook install
```

## Test Taxonomy

- Default safe suite:

```bash
uv run pytest
```

- Security-focused tests:

```bash
uv run pytest -m security
```

- Live API tests:

```bash
uv run pytest -m "integration and real_api and real_user_config"
```

- Manual auth tests:

```bash
uv run pytest -m manual -s
```

## Code Quality

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run ty check src
```

## Pull Requests

- Keep changes small and focused.
- Do not commit secrets, tokens, cookies, or local config files.
- Preserve the safe test selection for default local and CI runs.
- Add or update tests when behaviour changes.

## CLI Failure Policy

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure |
| `2` | Usage error (bad arguments, missing input) |
| `3` | Not found |
| `4` | Authentication required |
| `5` | Conflict |
| `6` | Transient error (retry may help) |
| `7` | Validation error |
| `130` | Interrupted (Ctrl+C) |

Prefer the existing failure families when adding or changing command behaviour:

- `AuthenticationError`
- `ConfigurationError`
- `AttachmentError`
- `AttachmentUploadError`
- `RateLimitError`
- `UpstreamSchemaError`
- `PerplexityHTTPStatusError`
- `PerplexityRequestError`

Guidance:

- Keep user-facing stderr messages helpful, but treat them as presentation, not a machine contract.
- In `--json` mode, errors are output as JSON envelopes on stdout with `"ok": false`.
- For unexpected top-level failures, route through `handle_error()` (for `--json` mode) or `handle_unexpected_cli_error()` (for human mode).

## Release Process

Releases are tag-driven from `master`.

```bash
sh .claude/scripts/prepare-release.sh X.Y.Z
```

This updates both version files, refreshes `uv.lock`, runs release checks, creates the release commit, and creates the local `vX.Y.Z` tag. Then push `master` and the tag. See `.claude/PUBLISHING.md` for the detailed flow.

## Python and Dependency Policy

- Supported Python versions: `3.12`, `3.13`
- Do not assume Python `3.14` support until CI and release validation include it.
- Keep `uv.lock` current and validate with `uv sync --locked`.
- Validate dependency updates with the safe default test suite, build checks, and installed-package smoke test.

## Security Notes

- Treat saved browser cookies as sensitive session material.
- Default tests must not touch real user config unless explicitly marked `real_user_config`.
- The current file encryption is machine-bound, but it is not equivalent to OS keychain-backed secret storage.
