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

- Exit code `0`: success.
- Exit code `1`: user-facing command failure.
- Exit code `130`: explicit user interruption.

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
- For unexpected top-level failures, route through `handle_unexpected_cli_error()`.
- Use broad catch-all handlers only as intentional top-level or rendering safety nets, and document them when they remain broad by design.

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
