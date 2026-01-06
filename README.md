# Perplexity CLI

A command-line interface for querying Perplexity.ai with persistent authentication and encrypted token storage.

[![PyPI](https://img.shields.io/pypi/v/pxcli)](https://pypi.org/project/pxcli/)

## Features

- **Persistent authentication** - Token stored securely and reused across invocations
- **Encrypted tokens** - Tokens encrypted with system-derived keys
- **Multiple output formats** - Plain text, Markdown, or rich terminal output
- **Source references** - Web sources extracted and displayed
- **Thread library export** - Export your entire Perplexity thread history to CSV with timestamps
- **Date filtering** - Filter exported threads by date range
- **Configurable URLs** - Base URL and endpoints configurable via JSON or environment variables
- **Error handling** - Clear error messages with exit codes and automatic retry logic
- **Server-Sent Events** - Streams responses in real-time
- **Logging** - Configurable logging with verbose/debug modes and log file support
- **Streaming output** - Real-time streaming of query responses as they arrive

## Installation

### Quick Install (Recommended for Users)

The easiest way to use pxcli is with `uvx`:

```bash
uvx pxcli auth
```

Or install with uv pip:

```bash
uv pip install pxcli
pxcli auth
```

Note: The command can also be run as `perplexity-cli` for convenience.

### Development Installation (For Contributors)

Clone and set up development environment:

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv --python=3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

Run tests to verify setup:

```bash
pytest
```

### Prerequisites

- Python 3.12 or higher
- Google Chrome (for authentication)

## Quick Start

### Authenticate (One Time)

```bash
pxcli auth
```

This opens your browser to authenticate with Perplexity.ai. Your token is encrypted and stored locally.

### Ask a Question

```bash
pxcli query "What is Python?"
```

### Check Status

```bash
pxcli status
```

### Output Formats

Query with JSON output:

```bash
pxcli query "Explain machine learning" --format json
```

### Verbose Mode

Get detailed logging:

```bash
pxcli query "What is AI?" --verbose
```

### Log Out

```bash
pxcli logout
```

## Configuration

### Environment Variables

Configure perplexity-cli with environment variables:

- `PERPLEXITY_BASE_URL`: Custom API base URL (default: https://www.perplexity.ai)
- `PERPLEXITY_QUERY_ENDPOINT`: Custom query endpoint
- `PERPLEXITY_LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)
- `PERPLEXITY_LOG_FILE`: Path to log file (default: ~/.config/perplexity-cli/perplexity-cli.log)
- `PERPLEXITY_RATE_LIMITING_ENABLED`: Enable/disable rate limiting (default: true)
- `PERPLEXITY_RATE_LIMITING_RPS`: Requests per period (default: 20)
- `PERPLEXITY_RATE_LIMITING_PERIOD`: Period in seconds (default: 60)

Example:

```bash
export PERPLEXITY_LOG_LEVEL=DEBUG
pxcli query "test"
```

### Output Formats

Available formats: `plain`, `markdown`, `rich`, `json`

Default is `rich` for terminal output with formatting. Use `--format` flag:

```bash
pxcli query "..." --format markdown
pxcli query "..." --format json
```

### Token Management

Your authentication token is encrypted and stored at:
- **Linux/macOS**: `~/.config/perplexity-cli/token.json`
- **Windows**: `%APPDATA%\perplexity-cli\token.json`

The token is encrypted using Fernet (AES-128-CBC) with a key derived from your system hostname and OS user. Tokens are not portable between machines.

To re-authenticate:

```bash
pxcli logout
pxcli auth
```

## Usage

### Authentication Setup

The first time you use pxcli, you need to authenticate with Perplexity.ai. This is a one-time process that extracts your session token and stores it securely on your machine.

#### Step 1: Install Chrome for Testing

Download a dedicated Chrome browser for authentication (this keeps testing separate from your main Chrome instance):

```bash
npx @puppeteer/browsers install chrome@stable
```

This downloads Chrome to `~/.local/bin/chrome/` (the path may change between Chrome versions).

#### Step 2: Create a Shell Alias

Set up an alias to easily run Chrome with remote debugging enabled:

```bash
# Add this line to your shell config (~/.bashrc, ~/.zshrc, etc.)
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'
```

**Note:** The `mac_arm-*` pattern matches the version directory. The exact path varies by Chrome version.

#### Step 3: Start Chrome and Authenticate

```bash
# Terminal 1: Start Chrome with debugging enabled
chromefortesting

# Terminal 2: Run authentication
pxcli auth
```

The authentication process will:
1. Connect to Chrome via the remote debugging port
2. Navigate to Perplexity.ai
3. Wait for you to log in (you'll see the login page in Chrome)
4. Extract your session token automatically
5. Save it encrypted to `~/.config/perplexity-cli/token.json`

Once complete, you won't need to authenticate again unless you run `pxcli logout`.

#### Custom Port (Optional)

If port 9222 is already in use, specify a different port:

```bash
pxcli auth --port 9223
```

Then start Chrome with the matching port:

```bash
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9223" "about:blank"'
```

### Query Perplexity

```bash
# Default format (rich terminal output)
pxcli query "What is machine learning?"

# Plain text (for scripts)
pxcli query --format plain "What is Python?"

# Markdown format
pxcli query --format markdown "Explain quantum computing" > answer.md

# JSON format (structured output for programmatic use)
pxcli query --format json "What is machine learning?" > answer.json

# Remove citations and references section
pxcli query --strip-references "What is Python?"

# Stream response in real-time
pxcli query --stream "What is Python?"

# Combine options
pxcli query --format plain --strip-references "What is 2+2?"

# Use in scripts
ANSWER=$(pxcli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Enable verbose logging
perplexity-cli --verbose query "What is Python?"

# Enable debug logging with custom log file
perplexity-cli --debug --log-file /tmp/perplexity.log query "What is Python?"
```

### Status and Logout

```bash
# Check authentication status
pxcli status

# Remove stored token
pxcli logout
```

## Commands

### `pxcli auth [--port PORT]`

Authenticate with Perplexity.ai via Chrome.

**Options:**
- `--port PORT` - Chrome remote debugging port (default: 9222)

### `pxcli query QUESTION [OPTIONS]`

Submit a query and get an answer with source references.

**Arguments:**
- `QUESTION` - Your question (quoted)

**Options:**
- `--format {plain,markdown,rich,json}` - Output format (default: rich)
  - `plain` - Plain text, suitable for scripts
  - `markdown` - GitHub-flavoured Markdown
  - `rich` - Terminal output with colours and formatting
  - `json` - Structured JSON with answer and references
- `--strip-references` - Remove citations and references section
- `--stream` - Stream response in real-time as it arrives (experimental)

**Global Options:**
- `--verbose, -v` - Enable verbose output (INFO level logging)
- `--debug, -d` - Enable debug output (DEBUG level logging)
- `--log-file PATH` - Write logs to file (default: ~/.config/perplexity-cli/perplexity-cli.log)

**Exit codes:**
- `0` - Success
- `1` - Error

### `pxcli status`

Display authentication status and token information.

### `pxcli logout`

Remove stored authentication token.

### `pxcli configure STYLE`

Set a custom style prompt applied to all queries.

**Example:**
```bash
pxcli configure "be concise"
```

### `pxcli view-style`

Display currently configured style.

### `pxcli clear-style`

Remove configured style.

### `pxcli export-threads [OPTIONS]`

Export your Perplexity.ai thread library to CSV format with creation timestamps.

Uses your stored authentication token - no browser required after initial auth setup!

**Options:**
- `--from-date DATE` - Start date for filtering (YYYY-MM-DD format, inclusive)
- `--to-date DATE` - End date for filtering (YYYY-MM-DD format, inclusive)
- `--output PATH` - Output CSV file path (default: threads-TIMESTAMP.csv)
- `--force-refresh` - Ignore local cache and fetch fresh data from Perplexity API
- `--clear-cache` - Delete local cache file before export

**Examples:**
```bash
# Export all threads (uses cache if available)
pxcli export-threads

# Export threads from 2025
pxcli export-threads --from-date 2025-01-01

# Export threads from a specific date range
pxcli export-threads --from-date 2025-01-01 --to-date 2025-12-31

# Export to custom file
pxcli export-threads --output my-threads.csv

# Force fresh data from API (bypass cache)
pxcli export-threads --force-refresh

# Clear cache and export fresh
pxcli export-threads --clear-cache
```

**Setup:**
Just authenticate once with `pxcli auth` - the export command reuses your stored token. No browser needed!

**Output format:**
```csv
created_at,title,url
2025-12-23T23:06:00.525132Z,What is Python?,https://www.perplexity.ai/search/...
2025-12-22T20:54:36.349239Z,Explain AI,https://www.perplexity.ai/search/...
```

The export includes:
- **created_at** - ISO 8601 timestamp with timezone (UTC)
- **title** - Thread question/title
- **url** - Full URL to the thread

**How it works:**
The command uses your stored authentication token to call the Perplexity.ai API directly. It automatically paginates through your entire library (handles thousands of threads) and exports the results to CSV.

**Caching:**
Thread exports are automatically cached locally to improve performance. On first export, all threads are fetched and cached. On subsequent exports, the cache is used unless:
- Requested date range extends beyond cached data (smart partial updates only fetch the gap)
- `--force-refresh` flag is used to bypass cache
- Cache is cleared with `--clear-cache` flag

The cache is encrypted with the same system-derived key as your auth token and stored at `~/.config/perplexity-cli/threads-cache.json`.

## Configuration

### Token Storage and Encryption

Tokens are stored encrypted at `~/.config/perplexity-cli/token.json` (Linux/macOS) or `%APPDATA%\perplexity-cli\token.json` (Windows).

**Encryption:**
- Uses Fernet symmetric encryption (AES-128-CBC)
- Key derived from system hostname and OS user
- Tokens not portable between machines
- No user passwords required

**Format:**
```json
{
  "version": 1,
  "encrypted": true,
  "token": "encrypted_token_data"
}
```

**File permissions:** 0600 (owner read/write only)

### URL Configuration

Perplexity URLs are configured in `~/.config/perplexity-cli/urls.json`.

**Default configuration:**
```json
{
  "perplexity": {
    "base_url": "https://www.perplexity.ai",
    "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask"
  },
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 20,
    "period_seconds": 60,
    "description": "Allow 20 requests per 60 seconds (~3s delay). Override via env vars or edit this file."
  }
}
```

To use alternative URLs, edit this file. Configuration is automatically created on first run.

**Environment Variables:**

You can override configuration values using environment variables:
- `PERPLEXITY_BASE_URL` - Overrides `perplexity.base_url`
- `PERPLEXITY_QUERY_ENDPOINT` - Overrides `perplexity.query_endpoint`

Example:
```bash
export PERPLEXITY_BASE_URL="https://custom.example.com"
pxcli query "What is Python?"
```

### Rate Limiting Configuration

Thread export operations are rate-limited by default to prevent overwhelming the Perplexity API and encountering 429 (Too Many Requests) errors.

**Default Rate Limit:**
- 20 requests per 60 seconds
- Approximately 3 second delay between API requests
- Safe for exporting libraries with thousands of threads

**Adjust Rate Limiting:**

Edit `~/.config/perplexity-cli/urls.json` and modify the `rate_limiting` section:

```json
{
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 20,
    "period_seconds": 60
  }
}
```

**Common Configurations:**

```json
{
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 10,
    "period_seconds": 60,
    "description": "Conservative: ~6 second delay (10 requests/60s). Use if encountering rate limits."
  }
}
```

```json
{
  "rate_limiting": {
    "enabled": true,
    "requests_per_period": 30,
    "period_seconds": 60,
    "description": "Aggressive: ~2 second delay (30 requests/60s). Use for faster exports."
  }
}
```

```json
{
  "rate_limiting": {
    "enabled": false,
    "description": "Disabled: No rate limiting (not recommended, may hit API limits)."
  }
}
```

**Environment Variable Overrides:**

You can override rate limiting settings without editing the config file:

- `PERPLEXITY_RATE_LIMITING_ENABLED` - Set to "true" or "false"
- `PERPLEXITY_RATE_LIMITING_RPS` - requests_per_period (e.g., "10")
- `PERPLEXITY_RATE_LIMITING_PERIOD` - period_seconds (e.g., "60")

Example:
```bash
# Disable rate limiting for a single export
export PERPLEXITY_RATE_LIMITING_ENABLED=false
pxcli export-threads

# Use conservative rate limiting (10 requests/minute)
export PERPLEXITY_RATE_LIMITING_RPS=10
export PERPLEXITY_RATE_LIMITING_PERIOD=60
pxcli export-threads
```

## Troubleshooting

### "Not authenticated"

Run `pxcli auth` to authenticate.

### "Failed to decrypt token"

Token was encrypted on a different machine or with a different user. Run `pxcli auth` to re-authenticate.

### Chrome connection fails

Ensure Chrome is running with `--remote-debugging-port=9222`. Verify the port matches the one you specified.

### Token file has insecure permissions

Token file was modified or has incorrect permissions. Delete the file and re-authenticate:
```bash
rm ~/.config/perplexity-cli/token.json
pxcli auth
```

## Output Formats

### Plain

Plain text output suitable for scripts and piping.

```bash
pxcli query --format plain "What is Python?"
```

### Markdown

GitHub-flavoured Markdown with headers and formatting.

```bash
pxcli query --format markdown "Explain AI" > answer.md
```

### Rich

Terminal output with colours, bold text, and formatted tables (default).

```bash
pxcli query "What is Python?"
```

### JSON

Structured JSON output suitable for programmatic processing and integration with other tools.

```bash
pxcli query --format json "What is machine learning?"
```

**Output structure:**
```json
{
  "format_version": "1.0",
  "answer": "Machine learning is a subfield of artificial intelligence...",
  "references": [
    {
      "index": 1,
      "title": "Machine learning, explained | MIT Sloan",
      "url": "https://mitsloan.mit.edu/ideas-made-to-matter/machine-learning-explained",
      "snippet": "Machine learning is a powerful form of artificial intelligence..."
    }
  ]
}
```

**Use cases:**
- Parse responses programmatically in scripts or applications
- Save structured data for later analysis
- Integrate with data pipelines
- Extract references for citation management
- Process answers through additional tools or APIs

**Examples:**

Save to file:
```bash
pxcli query --format json "What is Python?" > python.json
```

Extract and display answer as readable text:
```bash
# Use jq -r to render newlines as actual line breaks
pxcli query --format json "What is Python?" | jq -r '.answer'
```

Extract just the reference URLs:
```bash
pxcli query --format json "What is Python?" | jq -r '.references[] | .url'
```

Remove references from JSON output:
```bash
pxcli query --format json --strip-references "What is Python?"
```

Count the number of references:
```bash
pxcli query --format json "What is Python?" | jq '.references | length'
```

Parse JSON in a script:
```bash
python3 << 'EOF'
import json
import subprocess

result = subprocess.run(
    ["perplexity-cli", "query", "--format", "json", "What is Python?"],
    capture_output=True,
    text=True
)
data = json.loads(result.stdout)
print(data["answer"])
for ref in data["references"]:
    print(f"- {ref['title']}: {ref['url']}")
EOF
```

**Note:** When viewing JSON output, use `jq -r` (raw output) to properly display newlines in the answer text. Without `-r`, you'll see escape sequences like `\n` instead of actual line breaks.

## Development

### Setup Development Environment

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv --python=3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Linting, Formatting, and Type Checking

Format code (auto-fix):

```bash
ruff format src/
```

Check for linting issues:

```bash
ruff check src/
```

Type checking:

```bash
mypy src/
```

For more details on development practices, see `.claude/TESTING_GUIDE.md`.

## Security

- Tokens encrypted at rest using Fernet
- Encryption key derived from system identifiers
- File permissions restricted to owner (0600)
- Tokens validated on each request
- Token expiration detection (warns if token is >30 days old)
- Audit logging for token operations
- No credentials printed to logs

## Contributing

Contributions are welcome. Please ensure:
- Code follows PEP 8 standards
- All tests pass
- New features include tests

## License

MIT

## Dependencies

- click - CLI framework
- httpx - HTTP client
- websockets - WebSocket support
- rich - Terminal formatting
- cryptography - Token encryption
- tenacity - Retry logic with exponential backoff
- python-dateutil - Date parsing for thread exports
