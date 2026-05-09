# Perplexity CLI

A command-line interface for querying Perplexity.ai with persistent authentication and encrypted token storage.

[![PyPI](https://img.shields.io/pypi/v/pxcli)](https://pypi.org/project/pxcli/)

## Features

- **Query Perplexity.ai from the terminal** with a single command
- **Persistent authentication** with encrypted token storage (PBKDF2-HMAC key derivation)
- **Multiple output formats** -- plain text, Markdown, rich terminal, or structured JSON
- **Real-time streaming** -- optional incremental output as the response arrives
- **File attachments** -- attach files or entire directories to queries for context-aware answers
- **Source references** -- web sources extracted and displayed with inline citations
- **Citation stripping** -- remove citation markers and references section from output
- **Response style presets** -- configure a persistent style prompt applied to all queries
- **Thread library export** -- export your entire Perplexity thread history to CSV
- **Date filtering** -- filter exported threads by date range
- **Automatic retry** -- exponential backoff on transient errors and rate limits
- **Cloudflare bypass** -- Chrome TLS fingerprint impersonation via curl_cffi
- **Diagnostics** -- `doctor security` reports local storage state and file permissions
- **Agent integration** -- built-in skill definition for use with AI agents
- **Configurable** -- URLs, rate limits, cookie storage, and debug mode all configurable via file or environment variables

## Prerequisites

- Python 3.12 or later
- Google Chrome (for initial authentication only)

## Installation

### From PyPI (recommended)

Install from PyPI and run using either `pxcli` or `perplexity-cli` (both are equivalent):

```bash
# Install with uv
uv pip install pxcli

# Or run directly without installing
uvx pxcli --help
```

Then query using whichever name you prefer:

```bash
pxcli query "Tell me what happened in AI this week"
perplexity-cli query "Tell me what happened in AI this week"
```

### From source

Clone the repository and install in development mode:

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest  # verify setup
```

Both `pxcli` and `perplexity-cli` are available after installation:

```bash
pxcli query "Tell me what happened in AI this week"
perplexity-cli query "Tell me what happened in AI this week"
```

## Quick start

### 1. Try it immediately (no authentication required)

```bash
pxcli query "Tell me what happened in AI this week"
```

The `query` command works without authentication for simple questions.

### 2. Authenticate for full features (optional, one-time setup)

```bash
pxcli auth
```

This opens Chrome via the DevTools Protocol, waits for you to log in to Perplexity.ai, extracts your session token, and saves it encrypted locally. See [Authentication setup](#authentication-setup) for full instructions.

### 3. Use authenticated features

After authentication, you can:

```bash
# Attach files to queries (requires auth)
pxcli query --attach README.md "What is this project?"

# Export your thread library to CSV
pxcli export-threads

# Check your authentication status
pxcli status

# Configure a response style to apply to all queries
pxcli configure "be concise and technical"
```

## Querying

### Basic usage

```bash
# Default: rich terminal output, batch mode (waits for complete response)
pxcli query "What is machine learning?"

# Stream the response as it arrives
pxcli query --stream "What is machine learning?"

# Remove citation markers [1], [2] and the references section
pxcli query --strip-references "What is machine learning?"
```

### Output formats

Use `--format` (or `-f`) to choose the output format. The default is `rich`.

```bash
# Rich terminal output with colours and formatted tables (default)
pxcli query "What is Python?"

# Plain text with underlined headers (good for scripts and piping)
pxcli query --format plain "What is Python?"

# GitHub-flavoured Markdown
pxcli query --format markdown "What is Python?" > answer.md

# Structured JSON with answer text and references array
pxcli query --format json "What is Python?" > answer.json
```

#### JSON format

The JSON output has this structure:

```json
{
  "format_version": "1.0",
  "answer": "Python is a high-level programming language...",
  "references": [
    {
      "index": 1,
      "title": "Python.org",
      "url": "https://www.python.org",
      "snippet": "Python is a programming language..."
    }
  ]
}
```

Useful with `jq`:

```bash
# Extract just the answer text (use -r so newlines render properly)
pxcli query --format json "What is Python?" | jq -r '.answer'

# Extract reference URLs
pxcli query --format json "What is Python?" | jq -r '.references[].url'

# Count references
pxcli query --format json "What is Python?" | jq '.references | length'

# Strip references from JSON output
pxcli query --format json --strip-references "What is Python?"
```

### File attachments

Attach files to provide context for your query. Requires authentication.

```bash
# Single file
pxcli query --attach README.md "What is this project?"

# Multiple files (comma-separated)
pxcli query --attach config.json,data.txt "Analyse these files"

# Repeated flag
pxcli query -a file1.txt -a file2.txt "Compare these files"

# Entire directory (recursive)
pxcli query --attach ./docs "Summarise all documentation"
```

### Combining flags

Flags can be combined freely:

```bash
pxcli query --format plain --strip-references "What is 2+2?"
pxcli query --stream --strip-references "Explain Kubernetes"
pxcli query --format markdown --strip-references "How does DNS work?" > dns.md
```

### Scripting

```bash
# Capture output in a variable
ANSWER=$(pxcli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Parse JSON in Python
python3 << 'EOF'
import json, subprocess
result = subprocess.run(
    ["pxcli", "query", "--format", "json", "What is Python?"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
print(data["answer"])
for ref in data["references"]:
    print(f"- {ref['title']}: {ref['url']}")
EOF
```

### Exit codes and failure behaviour

- `0` means the command completed successfully.
- `1` means the command failed with a user-facing error.
- `130` means the command was interrupted by the user.

Current failure families are reported consistently where possible:

- **Authentication failures**: expired or missing credentials, or commands that require auth
- **Network failures**: connectivity and request transport problems
- **HTTP failures**: upstream non-success status codes such as `401`, `403`, or `429`
- **Configuration failures**: unreadable or invalid local config state
- **Attachment failures**: local attachment resolution or upload problems
- **Upstream schema failures**: unexpected API payload shapes after upstream changes

For scripting:

- prefer checking the process exit code first
- treat stderr as human-readable diagnostics, not a stable machine interface
- use `--format json` only for successful `query` output, not for error payloads

## Response styles

Set a persistent style prompt that is appended to every query. This lets you control the tone and format of responses without repeating instructions.

```bash
# Set a style
pxcli configure "be brief and concise"

# View the current style
pxcli view-style

# Clear the style
pxcli clear-style
```

The style is stored in `~/.config/perplexity-cli/style.json` and persists across sessions.

## Authentication

Most commands work without authentication. Only `export-threads` strictly requires a stored token. Here is a summary of authentication requirements:

### Commands requiring authentication

- `export-threads` -- Export your thread library to CSV

### Commands that work without authentication

- `query` -- Submit queries (authentication used automatically when available)
- `status` -- Show authentication status (reports unauthenticated state gracefully)
- `configure`, `view-style`, `clear-style` -- Manage response styles (local-only, no API calls)
- `set-config`, `show-config` -- Manage configuration (local-only)
- `show-skill` -- Display the Agent Skill definition
- `doctor security` -- Report local storage security details

If you have authenticated with `pxcli auth`, your token will be used automatically with `query`. If you haven't authenticated, `query` will attempt to run without a token (behaviour depends on whether the Perplexity API permits unauthenticated requests).

### Features requiring authentication within `query`

Even though the `query` command can run without authentication, some features require a token:

- **File attachments** -- The `--attach` flag requires authentication to upload files to Perplexity

For most users, we recommend authenticating to ensure the best experience. For automated scripts or testing, you can use `query` for simple questions without authentication. Any queries involving file uploads will require authentication.

## Authentication setup

The first time you use pxcli, you need to authenticate with Perplexity.ai. This is a one-time process that extracts your session token via Chrome's DevTools Protocol.

### Step 1: Install Chrome for Testing

Download a dedicated Chrome instance (keeps testing separate from your main browser):

```bash
npx @puppeteer/browsers install chrome@stable
```

This downloads Chrome to `~/.local/bin/chrome/`.

### Step 2: Create a shell alias

Add this to your shell configuration (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'
```

The `mac_arm-*` pattern matches the version directory. Adjust the path for your platform.

### Step 3: Authenticate

```bash
# Terminal 1: Start Chrome with debugging enabled
chromefortesting

# Terminal 2: Run authentication
pxcli auth
```

The process will:

1. Connect to Chrome via the remote debugging port
2. Navigate to Perplexity.ai
3. Wait for you to log in
4. Extract your session token
5. Save it encrypted to `~/.config/perplexity-cli/token.json`

Once complete, you do not need to authenticate again unless you run `pxcli logout` or the token expires.

### Custom port

If port 9222 is in use:

```bash
pxcli auth --port 9223
```

Start Chrome with the matching port in your alias.

## Thread export

Export your entire Perplexity thread history to CSV.

```bash
# Export all threads
pxcli export-threads

# Filter by date range
pxcli export-threads --from-date 2025-01-01
pxcli export-threads --from-date 2025-01-01 --to-date 2025-12-31

# Custom output file
pxcli export-threads --output my-threads.csv

# Bypass local cache
pxcli export-threads --force-refresh

# Clear cache before export
pxcli export-threads --clear-cache
```

### Output format

```csv
created_at,title,url
2025-12-23T23:06:00.525132Z,What is Python?,https://www.perplexity.ai/search/...
2025-12-22T20:54:36.349239Z,Explain AI,https://www.perplexity.ai/search/...
```

Fields: `created_at` (ISO 8601 UTC), `title`, `url`.

### Caching

Thread exports are cached locally in encrypted form at `~/.config/perplexity-cli/threads-cache.json`. The cache stores only threads within the requested date range, so subsequent exports with different date filters will fetch fresh data as needed. Use `--force-refresh` to bypass the cache or `--clear-cache` to delete it.

### Rate limiting

Thread export requests are rate-limited by default (20 requests per 60 seconds) to avoid HTTP 429 errors. See [Rate limiting](#rate-limiting) for configuration.

## Configuration

### Configuration file

pxcli stores feature toggles in `~/.config/perplexity-cli/config.json`:

```json
{
  "version": 1,
  "features": {
    "save_cookies": false,
    "debug_mode": false
  }
}
```

Manage settings with:

```bash
# View current configuration
pxcli show-config

# Enable cookie storage (saves Cloudflare cookies alongside JWT token)
pxcli set-config save_cookies true

# Enable persistent debug logging
pxcli set-config debug_mode true

# Disable
pxcli set-config save_cookies false
pxcli set-config debug_mode false
```

After changing `save_cookies`, re-authenticate for the change to take effect:

```bash
pxcli set-config save_cookies true
pxcli auth
```

### Token storage

Tokens are encrypted and stored at:

- **Linux/macOS**: `~/.config/perplexity-cli/token.json`
- **Windows**: `%APPDATA%\perplexity-cli\token.json`

Encryption uses Fernet with a key derived via PBKDF2-HMAC (100,000 iterations) from the system hostname and OS user. This is best treated as machine-bound obfuscation rather than strong secret storage: it helps prevent casual copying between machines, but it does not protect against other local processes or users that can already read the token file. File permissions are restricted to owner only (0600).

If cookie storage is enabled, browser cookies are stored in the same encrypted file and should be treated as sensitive session material.

To re-authenticate:

```bash
pxcli logout
pxcli auth
```

### URL configuration

API endpoints are configured in `~/.config/perplexity-cli/urls.json` (created automatically on first run):

```json
{
  "perplexity": {
    "base_url": "https://www.perplexity.ai",
    "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask"
  },
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 20,
    "period_seconds": 60
  }
}
```

### Rate limiting

Rate limiting applies to thread export requests. Adjust in `urls.json`:

```json
{
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 10,
    "period_seconds": 60
  }
}
```

Set `"enabled": false` to disable (not recommended).

### Environment variables

Environment variables override configuration file settings. Precedence: CLI flags > environment variables > config file > defaults.

| Variable | Description |
|---|---|
| `PERPLEXITY_BASE_URL` | API base URL |
| `PERPLEXITY_QUERY_ENDPOINT` | Query endpoint path |
| `PERPLEXITY_SAVE_COOKIES` | `true` or `false` -- override cookie storage |
| `PERPLEXITY_DEBUG_MODE` | `true` or `false` -- override debug mode |
| `PERPLEXITY_RATE_LIMITING_ENABLED` | `true` or `false` |
| `PERPLEXITY_RATE_LIMITING_RPS` | Requests per period (integer) |
| `PERPLEXITY_RATE_LIMITING_PERIOD` | Period in seconds (integer) |

## Command reference

### Global options

```
pxcli [OPTIONS] COMMAND [ARGS]...

Options:
  --version        Show version and exit
  -v, --verbose    INFO level logging
  -d, --debug      DEBUG level logging
  --log-file PATH  Log file path (default: ~/.config/perplexity-cli/perplexity-cli.log)

Command options:
  query           -f {plain,markdown,rich,json}  --strip-references
                  --stream / --no-stream  -a/--attach FILE
  auth            --port PORT
  export-threads  --from-date DATE  --to-date DATE  --output PATH
                  --force-refresh  --clear-cache
  configure       STYLE
  set-config      KEY VALUE
```

### `pxcli auth [--port PORT]`

Authenticate with Perplexity.ai via Chrome DevTools Protocol. Default port: 9222.

### `pxcli query QUERY [OPTIONS]`

Submit a query and display the answer.

| Option | Description |
|---|---|
| `--format`, `-f` | Output format: `plain`, `markdown`, `rich` (default), `json` |
| `--strip-references` | Remove citation markers and references section |
| `--stream` / `--no-stream` | Stream response incrementally (default: `--no-stream`) |
| `--attach`, `-a` | Attach file(s): single path, comma-separated, repeated flag, or directory (recursive) |

Exit codes: `0` success, `1` error, `130` interrupted.

### `pxcli status [--verify]`

Display local authentication status. Use `--verify` to perform a live API verification check.

### `pxcli logout`

Remove stored authentication token.

### `pxcli configure STYLE`

Set a persistent style prompt applied to all queries.

### `pxcli view-style`

Display the currently configured style.

### `pxcli clear-style`

Remove the configured style.

### `pxcli set-config KEY VALUE`

Set a configuration option. Keys: `save_cookies`, `debug_mode`. Values: `true`, `false`.

### `pxcli show-config`

Display current configuration and any environment variable overrides.

### `pxcli doctor security`

Display local storage backend details, token/cache permission state, and cookie-storage risk information.

### `pxcli show-skill`

Display the Agent Skill definition for integrating pxcli with AI agents.

### `pxcli export-threads [OPTIONS]`

Export thread library to CSV.

Uses the stored token and any saved browser cookies for the export request path.

| Option | Description |
|---|---|
| `--from-date DATE` | Start date filter (YYYY-MM-DD, inclusive) |
| `--to-date DATE` | End date filter (YYYY-MM-DD, inclusive) |
| `--output PATH` | Output file path (default: `threads-TIMESTAMP.csv`) |
| `--force-refresh` | Bypass local cache |
| `--clear-cache` | Delete cache before export |

## Troubleshooting

### "Not authenticated"

Run `pxcli auth` to authenticate.

### "Failed to decrypt token"

The token was encrypted on a different machine or with a different user. Run `pxcli auth` to re-authenticate.

### Chrome connection fails

Ensure Chrome is running with `--remote-debugging-port=9222` and the port matches what you specified.

### Token file has insecure permissions

Delete the file and re-authenticate:

```bash
rm ~/.config/perplexity-cli/token.json
pxcli auth
```

## Development

### Releasing

Releases are triggered by pushing a `vX.Y.Z` tag on `master`. Before tagging, run:

```bash
sh .claude/scripts/release-check.sh
```

The detailed release workflow is documented in `.claude/PUBLISHING.md`.

To prepare a release commit and local tag in one step:

```bash
sh .claude/scripts/prepare-release.sh X.Y.Z
```

## Project Governance

- Contributing guide: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`
- Licence: `LICENSE`
- Changelog source: GitHub Releases

## Compatibility Policy

- Supported Python versions are `3.12` and `3.13`.
- Python `3.14` is not declared supported until CI coverage and release verification are added for it.
- Dependency updates should continue to be validated through `uv sync --locked`, the safe default test suite, build checks, and the installed-package smoke test before release.

### Setup

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv run lefthook install
```

### Testing

```bash
uv run pytest                   # safe default test suite
uv run pytest -m security       # security tests only
uv run pytest -m "integration and real_api and real_user_config"
uv run pytest -m manual -s      # manual auth tests
```

Install Git hooks with `uv run lefthook install` and run them on demand with
`uv run lefthook run pre-commit`.

### Linting and formatting

```bash
ruff format src/ tests/         # auto-format
ruff check src/ tests/          # lint
ty check src/                   # type check
```

## Security

- Tokens encrypted at rest using Fernet
- Key derivation via PBKDF2-HMAC with 100,000 iterations (with backward-compatible SHA-256 fallback for legacy tokens)
- File permissions restricted to owner (0600)
- Encryption is machine-bound and deterministic; it is not equivalent to OS keychain-backed secret storage
- Token validity checked on each request
- Token age warnings (>30 days)
- No credentials written to logs

## Dependencies

- **click** -- CLI framework
- **curl-cffi** -- HTTP client with Chrome TLS fingerprint impersonation (query and thread export paths)
- **httpx** -- HTTP client fallback when curl_cffi is unavailable
- **rich** -- Terminal formatting
- **cryptography** -- Token encryption
- **tenacity** -- Retry logic with exponential backoff
- **pydantic** -- Data validation and serialisation
- **python-dateutil** -- Date parsing for thread exports
- **websockets** -- WebSocket support for Chrome DevTools Protocol authentication

## Updating your .profile / .zshrc / etc

Useful functions to add into your profile e.g. `$HOME/.zshrc` of choice.

```
px() {
  local q="$*"
  uvx pxcli query --strip-references --format rich "${q}."
}

pxc() {
  local q="$*"
  uvx pxcli query --strip-references --format plain "${q}. Just give me the commands to run on a Mac. Put them on a single line"
}
```

after which you can run, for example

```
pxc "how can I find what remote branches exist for this repo"
```

## Licence

MIT
