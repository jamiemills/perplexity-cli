# Perplexity CLI

A command-line interface for querying Perplexity.ai with persistent authentication and encrypted token storage.

[![PyPI](https://img.shields.io/pypi/v/pxcli)](https://pypi.org/project/pxcli/)

## Features

- **Query Perplexity.ai from the terminal** with a single command
- **Persistent authentication** with encrypted token storage (PBKDF2-HMAC key derivation)
- **Structured JSON output** -- envelope format with `ok`, `result`, `meta`, and `next_actions` fields
- **Multiple output formats** -- plain text, Markdown, rich terminal, or structured JSON
- **Real-time streaming** -- optional incremental output as the response arrives
- **NDJSON streaming** -- structured streaming with `--json --stream` for agent integration
- **File attachments** -- attach files or entire directories to queries for context-aware answers
- **Stdin support** -- pipe queries from stdin with `echo "question" | pxcli query -`
- **Source references** -- web sources extracted and displayed with inline citations
- **Citation stripping** -- remove citation markers and references section from output
- **Response style presets** -- configure a persistent style prompt applied to all queries
- **Thread library export** -- export your entire Perplexity thread history to CSV
- **Date filtering** -- filter exported threads by date range
- **Automatic retry** -- exponential backoff on transient errors and rate limits
- **Cloudflare bypass** -- Chrome TLS fingerprint impersonation via curl_cffi
- **Shell completion** -- generated completion scripts for Bash, Zsh, and Fish
- **JSON schema** -- machine-readable schema for all envelope types
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
pxcli auth login
```

This opens Chrome via the DevTools Protocol, waits for you to log in to Perplexity.ai, extracts your session token, and saves it encrypted locally. See [Authentication setup](#authentication-setup) for full instructions.

### 3. Use authenticated features

After authentication, you can:

```bash
# Attach files to queries (requires auth)
pxcli query --attach README.md "What is this project?"

# Export your thread library to CSV
pxcli threads export

# Check your authentication status
pxcli auth status

# Configure a response style to apply to all queries
pxcli style set "be concise and technical"
```

## Querying

### Basic usage

```bash
# Default: rich terminal output, batch mode (waits for complete response)
pxcli query "What is machine learning?"

# Stream the response as it arrives
pxcli query --stream "What is machine learning?"
pxcli query -s "What is machine learning?"

# Remove citation markers [1], [2] and the references section
pxcli query --strip-references "What is machine learning?"
pxcli query -S "What is machine learning?"

# Set a timeout (seconds)
pxcli query --timeout 30 "Complex question"
pxcli query -t 30 "Complex question"

# Read query from stdin
echo "What is Python?" | pxcli query -
```

### Output formats

Use `--format` (or `-f`) to choose the output format. The default is `rich` when stdout is a TTY, or `plain` when piped.

```bash
# Rich terminal output with colours and formatted tables (default for TTY)
pxcli query "What is Python?"

# Plain text with underlined headers (default when piped, good for scripts)
pxcli query --format plain "What is Python?"

# GitHub-flavoured Markdown
pxcli query --format markdown "What is Python?" > answer.md

# Structured JSON envelope
pxcli query --json "What is Python?" > answer.json
pxcli query --format json "What is Python?" > answer.json  # equivalent
```

#### JSON format

The `--json` flag (or `--format json`) produces a structured envelope:

```json
{
  "ok": true,
  "command": "pxcli query --json \"What is Python?\"",
  "result": {
    "answer": "Python is a high-level programming language...",
    "references": [
      {
        "name": "Python.org",
        "url": "https://www.python.org",
        "snippet": "Python is a programming language..."
      }
    ]
  },
  "meta": {
    "duration_ms": 1423,
    "version": "0.7.0",
    "trace_id": "a1b2c3d4-..."
  },
  "next_actions": []
}
```

Error responses use the same envelope structure with `"ok": false`:

```json
{
  "ok": false,
  "command": "pxcli query --json \"...\"",
  "error": {
    "code": "authentication_required",
    "message": "File attachments require authentication.",
    "input": {}
  },
  "fix": "Run `pxcli auth login` to authenticate.",
  "next_actions": [
    { "command": "pxcli auth login", "description": "Authenticate with Perplexity.ai" }
  ]
}
```

Useful with `jq`:

```bash
# Check success
pxcli query --json "What is Python?" | jq '.ok'

# Extract just the answer text (use -r so newlines render properly)
pxcli query --json "What is Python?" | jq -r '.result.answer'

# Extract reference URLs
pxcli query --json "What is Python?" | jq -r '.result.references[].url'

# Get timing metadata
pxcli query --json "What is Python?" | jq '.meta.duration_ms'

# Strip references from JSON output
pxcli query --json --strip-references "What is Python?"
```

#### NDJSON streaming

Use `--json --stream` together for structured streaming output. Each line is a valid JSON object:

```bash
pxcli query --json --stream "What is Python?"
```

Line types:
- `{"type": "start", "command": "...", "ts": "..."}` -- first line
- `{"type": "chunk", "text": "...", "ts": "..."}` -- incremental content
- `{"type": "result", ...full envelope..., "ts": "..."}` -- final line

Without `--json`, `--stream` produces raw text (the existing behaviour).

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
pxcli query -f plain -S "What is 2+2?"
pxcli query --stream --strip-references "Explain Kubernetes"
pxcli query --format markdown --strip-references "How does DNS work?" > dns.md
pxcli query --json --timeout 60 "Complex analysis question"
```

### Scripting

```bash
# Capture output in a variable
ANSWER=$(pxcli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Parse JSON envelope in Python
python3 << 'EOF'
import json, subprocess
result = subprocess.run(
    ["pxcli", "query", "--json", "What is Python?"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
if data["ok"]:
    print(data["result"]["answer"])
    for ref in data["result"]["references"]:
        print(f"- {ref['name']}: {ref['url']}")
else:
    print(f"Error: {data['error']['message']}")
EOF
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure |
| `2` | Usage error (bad arguments, missing input) |
| `3` | Not found |
| `4` | Authentication required |
| `5` | Conflict |
| `6` | Transient error (timeout, rate limit, server error -- retry may help) |
| `7` | Validation error |
| `130` | Interrupted (Ctrl+C) |

For scripting:

- Prefer checking the process exit code first.
- In `--json` mode, both success and error responses are valid JSON envelopes on stdout. Check the `.ok` field.
- Without `--json`, stderr contains human-readable diagnostics (not a stable machine interface).

## Response styles

Set a persistent style prompt that is appended to every query. This lets you control the tone and format of responses without repeating instructions.

```bash
# Set a style
pxcli style set "be brief and concise"

# View the current style
pxcli style show

# Clear the style
pxcli style clear
```

The style is stored in `~/.config/perplexity-cli/style.json` and persists across sessions.

## Authentication

Most commands work without authentication. Only `threads export` strictly requires a stored token. Here is a summary of authentication requirements:

### Commands requiring authentication

- `threads export` -- Export your thread library to CSV

### Commands that work without authentication

- `query` -- Submit queries (authentication used automatically when available)
- `auth status` -- Show authentication status (reports unauthenticated state gracefully)
- `style set`, `style show`, `style clear` -- Manage response styles (local-only, no API calls)
- `config set`, `config show` -- Manage configuration (local-only)
- `skill show` -- Display the Agent Skill definition
- `doctor security` -- Report local storage security details
- `completion {bash|zsh|fish}` -- Generate shell completion scripts
- `schema` -- Output JSON schema for envelopes

If you have authenticated with `pxcli auth login`, your token will be used automatically with `query`. If you haven't authenticated, `query` will attempt to run without a token (behaviour depends on whether the Perplexity API permits unauthenticated requests).

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
pxcli auth login
```

The process will:

1. Connect to Chrome via the remote debugging port
2. Navigate to Perplexity.ai
3. Wait for you to log in
4. Extract your session token
5. Save it encrypted to `~/.config/perplexity-cli/token.json`

Once complete, you do not need to authenticate again unless you run `pxcli auth logout` or the token expires.

### Custom port

If port 9222 is in use:

```bash
pxcli auth login --port 9223
pxcli auth login -p 9223
```

Start Chrome with the matching port in your alias.

## Thread export

Export your entire Perplexity thread history to CSV.

```bash
# Export all threads
pxcli threads export

# Filter by date range
pxcli threads export --from-date 2025-01-01
pxcli threads export --from-date 2025-01-01 --to-date 2025-12-31

# Custom output file
pxcli threads export --output my-threads.csv
pxcli threads export -o my-threads.csv

# Bypass local cache
pxcli threads export --force-refresh

# Clear cache before export
pxcli threads export --clear-cache
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

## Shell completion

Generate shell completion scripts for tab-completion of commands and options:

```bash
# Bash -- add to ~/.bashrc
eval "$(pxcli completion bash)"

# Zsh -- add to ~/.zshrc
eval "$(pxcli completion zsh)"

# Fish
pxcli completion fish | source
```

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
pxcli config show

# Enable cookie storage (saves Cloudflare cookies alongside JWT token)
pxcli config set save_cookies true

# Enable persistent debug logging
pxcli config set debug_mode true

# Disable
pxcli config set save_cookies false
pxcli config set debug_mode false
```

After changing `save_cookies`, re-authenticate for the change to take effect:

```bash
pxcli config set save_cookies true
pxcli auth login
```

### Token storage

Tokens are encrypted and stored at:

- **Linux/macOS**: `~/.config/perplexity-cli/token.json`
- **Windows**: `%APPDATA%\perplexity-cli\token.json`

Encryption uses Fernet with a key derived via PBKDF2-HMAC (100,000 iterations) from the system hostname and OS user. This is best treated as machine-bound obfuscation rather than strong secret storage: it helps prevent casual copying between machines, but it does not protect against other local processes or users that can already read the token file. File permissions are restricted to owner only (0600).

If cookie storage is enabled, browser cookies are stored in the same encrypted file and should be treated as sensitive session material.

To re-authenticate:

```bash
pxcli auth logout
pxcli auth login
```

### URL configuration

API endpoints are configured in `~/.config/perplexity-cli/urls.json` (created automatically on first run):

```json
{
  "perplexity": {
    "base_url": "https://www.perplexity.ai",
    "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask",
    "thread_list_endpoint": "https://www.perplexity.ai/rest/thread/list_ask_threads",
    "upload_url_endpoint": "https://www.perplexity.ai/rest/uploads/batch_create_upload_urls",
    "s3_bucket_url": "https://ppl-ai-file-upload.s3.amazonaws.com/"
  },
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 20,
    "period_seconds": 60
  }
}
```

All endpoint fields are full URLs. If Perplexity changes an endpoint, update the relevant field in `urls.json` without modifying any code.

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
| `PERPLEXITY_CONFIG_DIR` | Override config directory location |
| `PERPLEXITY_SAVE_COOKIES` | `true` or `false` -- override cookie storage |
| `PERPLEXITY_DEBUG_MODE` | `true` or `false` -- override debug mode |
| `PERPLEXITY_RATE_LIMITING_ENABLED` | `true` or `false` |
| `PERPLEXITY_RATE_LIMITING_RPS` | Requests per period (integer) |
| `PERPLEXITY_RATE_LIMITING_PERIOD` | Period in seconds (integer) |
| `XDG_CONFIG_HOME` | XDG base directory for config (default: `~/.config`) |
| `NO_COLOR` | Disable coloured output (any value) |
| `PXCLI_SESSION_LOG` | Set to `true` to enable NDJSON session logging |

## Command reference

### Global options

```
pxcli [OPTIONS] COMMAND [ARGS]...

Options:
  --version        Show version and exit
  -v, --verbose    INFO level logging
  -d, --debug      DEBUG level logging
  --log-file PATH  Log file path (default: ~/.config/perplexity-cli/perplexity-cli.log)
  -q, --quiet      Suppress non-essential output
  --no-color       Disable coloured output

Command groups:
  auth             Authentication management (login, logout, status)
  config           Configuration management (set, show)
  style            Style prompt management (set, show, clear)
  threads          Thread management (export)
  skill            Agent skill management (show)
  doctor           Diagnostics (security)
  completion       Shell completion scripts (bash, zsh, fish)

Root commands:
  query            Submit a query to Perplexity.ai
  schema           Output JSON schema for command envelopes
```

### `pxcli query QUERY [OPTIONS]`

Submit a query and display the answer.

| Option | Short | Description |
|---|---|---|
| `--format` | `-f` | Output format: `plain`, `markdown`, `rich` (default), `json` |
| `--json` | | Structured JSON envelope output |
| `--strip-references` | `-S` | Remove citation markers and references section |
| `--stream` / `--no-stream` | `-s` | Stream response incrementally (default: `--no-stream`) |
| `--attach` | `-a` | Attach file(s): single path, comma-separated, repeated flag, or directory (recursive) |
| `--timeout` | `-t` | Request timeout in seconds |

### `pxcli auth login [--port PORT]`

Authenticate with Perplexity.ai via Chrome DevTools Protocol. Default port: 9222.

### `pxcli auth status [--verify]`

Display local authentication status. Use `--verify` to perform a live API verification check.

### `pxcli auth logout`

Remove stored authentication token.

### `pxcli config set KEY VALUE`

Set a configuration option. Keys: `save_cookies`, `debug_mode`. Values: `true`, `false`.

### `pxcli config show`

Display current configuration and any environment variable overrides.

### `pxcli style set STYLE`

Set a persistent style prompt applied to all queries.

### `pxcli style show`

Display the currently configured style.

### `pxcli style clear`

Remove the configured style.

### `pxcli threads export [OPTIONS]`

Export thread library to CSV. Uses the stored token and any saved browser cookies for the export request path.

| Option | Short | Description |
|---|---|---|
| `--from-date` | | Start date filter (YYYY-MM-DD, inclusive) |
| `--to-date` | | End date filter (YYYY-MM-DD, inclusive) |
| `--output` | `-o` | Output file path (default: `threads-TIMESTAMP.csv`) |
| `--force-refresh` | | Bypass local cache |
| `--clear-cache` | | Delete cache before export |

### `pxcli doctor security`

Display local storage backend details, token/cache permission state, and cookie-storage risk information.

### `pxcli skill show`

Display the Agent Skill definition for integrating pxcli with AI agents.

### `pxcli completion {bash|zsh|fish}`

Generate shell completion scripts for the specified shell.

### `pxcli schema`

Output JSON schema for success and error envelopes, plus per-command result schemas.

## Troubleshooting

### "Not authenticated"

Run `pxcli auth login` to authenticate.

### "Failed to decrypt token"

The token was encrypted on a different machine or with a different user. Run `pxcli auth login` to re-authenticate.

### Chrome connection fails

Ensure Chrome is running with `--remote-debugging-port=9222` and the port matches what you specified.

### Token file has insecure permissions

Delete the file and re-authenticate:

```bash
rm ~/.config/perplexity-cli/token.json
pxcli auth login
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
uv run pytest                   # safe default test suite (1276 tests)
uv run pytest -m security       # security tests only
uv run pytest -m fuzz           # fuzz tests (17 atheris harnesses)
uv run pytest -m "integration and real_api and real_user_config"
uv run pytest -m manual -s      # manual auth tests
```

Install Git hooks with `uv run lefthook install` and run them on demand with
`uv run lefthook run pre-commit`.

### Code analysis

Every change passes through three layers of automated analysis: git hooks on commit and push, real-time checks during AI-assisted editing, and manual tool invocations. The tools and their roles are summarised below, followed by details on each layer.

#### Tools

| Tool | Purpose | Scope |
|---|---|---|
| **ruff** | Linting (PEP 8, imports, docstrings, debug statements) and auto-formatting | All Python files |
| **ty** | Fast type checking (Astral, Rust-based) | `src/` |
| **pyright** | Full type checking (Microsoft) | `src/` |
| **bandit** | Static security analysis (eval, shell injection, hardcoded secrets) | `src/` |
| **radon** | Cyclomatic complexity (CC) and maintainability index (MI) | `src/` |
| **vulture** | Dead code detection | `src/` + `vulture_whitelist.py` |
| **semgrep** | Clean Code rules (15 custom + community rulesets) | All Python files |
| **safety** | Supply-chain vulnerability scanning (known CVEs in dependencies) | `pyproject.toml` |
| **atheris** | Coverage-guided fuzz testing (17 harnesses) | Parser and validation code |
| **pytest** | Unit, integration, and security tests (1276 tests, 94% coverage) | `tests/` |

Complexity thresholds: every function must be A-grade (CC <= 5), every module must be A-grade (MI). These are enforced by radon in both the pre-commit hook and the real-time plugin.

#### Layer 1: Git hooks (lefthook)

Git hooks are managed by [lefthook](https://github.com/evilmartians/lefthook). Install them once after cloning:

```bash
uv run lefthook install
```

**Pre-commit** runs a three-stage pipeline. Each stage must pass before the next begins:

```
Stage 1 — Lint and validate (~4s, parallel)
  pyright, ty, bandit, vulture, radon cc, radon mi, semgrep,
  check-yaml, check-json, check-toml, check-merge-conflict,
  check-case-conflict, check-added-large-files,
  check-docstring-first, name-tests-test

Stage 2 — Auto-fix (~0.7s, sequential)
  ruff format, ruff check --fix,
  trailing-whitespace-fixer, end-of-file-fixer

Stage 3 — Tests (~21s)
  pytest (safe default suite, no coverage, fail-fast)
```

Stage 1 runs all validators in parallel for the fastest possible feedback. If any validator fails (e.g. a bandit security finding or a pyright type error), the commit is rejected immediately without running fixers or tests.

Stage 2 runs auto-fixers sequentially to avoid file races. Modified files are re-staged automatically (`stage_fixed: true`).

Stage 3 runs the full safe test suite without coverage reporting. Coverage is deferred to pre-push.

**Pre-push** runs three expensive checks in parallel:

```
pytest with coverage (--cov-fail-under=85, per-module 85% floor)
safety scan (supply-chain vulnerability check)
fuzz tests (17 atheris harnesses, 5000 iterations each)
```

Coverage enforcement uses two gates: pytest-cov's global `--cov-fail-under=85` and a custom `scripts/check_module_coverage.py` that verifies every individual module meets the 85% floor. The current project-wide coverage is 94%.

Run hooks manually at any time:

```bash
uv run lefthook run pre-commit   # run the full pre-commit pipeline
uv run lefthook run pre-push     # run pre-push checks
```

#### Layer 2: Real-time plugin (OpenCode)

When developing with [OpenCode](https://opencode.ai), the plugin at `.opencode/plugins/pxcli-quality.ts` provides continuous quality feedback without waiting for a commit.

**System prompt injection.** The plugin injects 20 coding conventions into every conversation via the `experimental.chat.system.transform` hook. These cover complexity limits, docstring requirements, logging style, security rules, naming conventions, and dependency practices. The AI assistant sees these conventions as part of its instructions and applies them when writing or modifying code.

**Per-edit checks (~500ms).** After every Python file write or edit, four tools run in parallel:

```
ruff    — lint violations (unused imports, style, docstrings)
radon   — cyclomatic complexity (flags anything above A-grade)
bandit  — security issues (eval, exec, shell=True, hardcoded secrets)
ty      — type errors
```

Findings are appended directly to the tool output, so the AI sees them immediately and can fix issues in the same turn. Test files, conftest, and fuzz harnesses are excluded.

**Dependency security.** When `pyproject.toml` or `requirements.txt` is edited, a `safety scan` runs automatically and reports any known vulnerabilities in the dependency tree.

**Session idle analysis.** When the editing session goes idle, two heavier tools run on all files modified during the session:

```
semgrep  — 15 custom Clean Code rules + community rulesets
pyright  — full type checking
```

These are too slow for per-edit feedback but provide a thorough sweep before the next interactive round.

**Tool availability.** Each tool is checked on first invocation. If a tool is missing from the environment, a warning is logged once and the tool is skipped for the remainder of the session. The plugin never blocks editing if a tool is unavailable.

#### Layer 3: Manual invocation

Run any tool directly for targeted analysis:

```bash
# Linting and formatting
uv run ruff check src/ tests/                   # lint
uv run ruff format src/ tests/                   # auto-format

# Type checking
uv run ty check src                              # fast type check
uv run pyright src/                              # full type check

# Security
uvx --from bandit bandit -c pyproject.toml -r src/ -ll -ii  # static security
uvx safety scan --target .                       # supply-chain vulnerabilities

# Complexity
uv run radon cc src/ -s -n B                     # cyclomatic complexity (B+ = violation)
uv run radon mi src/ -s -n B                     # maintainability index (B+ = violation)

# Dead code
uv run vulture src/ vulture_whitelist.py --min-confidence 80

# Clean Code rules
semgrep --config .semgrep.yml --config p/python --config p/comment \
        --config p/r2c-best-practices --severity ERROR --severity WARNING .

# Fuzz testing
uv run pytest -m fuzz                            # all 17 harnesses

# Coverage
uv run pytest --cov --cov-report=term-missing --cov-fail-under=85
uv run python scripts/check_module_coverage.py --min-coverage 85
```

#### Semgrep rules

The project includes 15 custom Clean Code rules in `.semgrep.yml`:

- `bare-except` -- no bare `except:` or `except Exception: pass`
- `raise-from` -- require `raise X from Y` in except blocks
- `no-eval-exec` -- forbid `eval()` and `exec()`
- `no-shell-true` -- forbid `subprocess` with `shell=True`
- `no-hardcoded-secrets` -- detect hardcoded passwords, tokens, API keys
- `no-random-for-security` -- require `secrets` module for security-sensitive randomness
- `lazy-logger-formatting` -- require `%s`-style formatting in logger calls
- `no-print-statements` -- use `logger`, not `print()`
- `no-wildcard-imports` -- forbid `from x import *`
- `identity-none-check` -- use `is None` / `is not None`
- `no-single-letter-vars` -- forbid single-letter variables (except `e`, `f`, `i`, `j`, `k`, `v`, `x`, `y`, `n`)
- `too-many-parameters` -- flag functions with more than 4 parameters
- `no-commented-out-code` -- detect commented-out code blocks
- `type-annotations-required` -- require type annotations on function signatures
- `no-credential-logging` -- forbid logging tokens, cookies, or credentials

These run alongside the `p/python`, `p/comment`, and `p/r2c-best-practices` community rulesets (254 rules total).

#### Inline suppressions

When a tool finding is a deliberate false positive, suppress it inline with a justification comment:

```python
# Bandit: B310 is safe here -- URL is hardcoded to localhost
url = urllib.request.urlopen(f"http://localhost:{port}")  # nosec B310

# Semgrep: function is a Click command; parameters are CLI options
# nosemgrep: too-many-parameters
def export_threads(output, from_date, to_date, force_refresh, clear_cache):
    ...
```

Global skips are not used. All suppressions are inline with explanatory comments.

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

pxj() {
  local q="$*"
  uvx pxcli query --json "${q}" | jq -r '.result.answer'
}
```

after which you can run, for example

```
pxc "how can I find what remote branches exist for this repo"
pxj "what is the latest version of Python?"
```

## Licence

MIT
