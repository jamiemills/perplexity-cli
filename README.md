# Perplexity CLI

A command-line interface for querying Perplexity.ai with persistent authentication and encrypted token storage.

## Features

- **Persistent authentication** - Token stored securely and reused across invocations
- **Encrypted tokens** - Tokens encrypted with system-derived keys
- **Multiple output formats** - Plain text, Markdown, or rich terminal output
- **Source references** - Web sources extracted and displayed
- **Configurable URLs** - Base URL and endpoints configurable via JSON or environment variables
- **Error handling** - Clear error messages with exit codes and automatic retry logic
- **Server-Sent Events** - Streams responses in real-time
- **Logging** - Configurable logging with verbose/debug modes and log file support
- **Streaming output** - Real-time streaming of query responses as they arrive

## Quick Start

```bash
# Install
uv pip install -e .

# Authenticate (one time)
perplexity-cli auth

# Ask questions
perplexity-cli query "What is Python?"

# Check status
perplexity-cli status

# Log out
perplexity-cli logout
```

## Installation

### Prerequisites

- Python 3.12 or higher
- uv package manager
- Google Chrome (for authentication)

### Install

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli

uv venv --python=3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

## Usage

### Authentication

Before querying, authenticate with Perplexity.ai:

```bash
# Start Chrome with remote debugging on port 9222
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# Run authentication
perplexity-cli auth
```

This connects to Chrome, navigates to Perplexity.ai, extracts your session token, and saves it encrypted to `~/.config/perplexity-cli/token.json`.

### Query Perplexity

```bash
# Default format (rich terminal output)
perplexity-cli query "What is machine learning?"

# Plain text (for scripts)
perplexity-cli query --format plain "What is Python?"

# Markdown format
perplexity-cli query --format markdown "Explain quantum computing" > answer.md

# Remove citations and references section
perplexity-cli query --strip-references "What is Python?"

# Stream response in real-time
perplexity-cli query --stream "What is Python?"

# Combine options
perplexity-cli query --format plain --strip-references "What is 2+2?"

# Use in scripts
ANSWER=$(perplexity-cli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Enable verbose logging
perplexity-cli --verbose query "What is Python?"

# Enable debug logging with custom log file
perplexity-cli --debug --log-file /tmp/perplexity.log query "What is Python?"
```

### Status and Logout

```bash
# Check authentication status
perplexity-cli status

# Remove stored token
perplexity-cli logout
```

## Commands

### `perplexity-cli auth [--port PORT]`

Authenticate with Perplexity.ai via Chrome.

**Options:**
- `--port PORT` - Chrome remote debugging port (default: 9222)

### `perplexity-cli query QUESTION [OPTIONS]`

Submit a query and get an answer with source references.

**Arguments:**
- `QUESTION` - Your question (quoted)

**Options:**
- `--format {plain,markdown,rich}` - Output format (default: rich)
  - `plain` - Plain text, suitable for scripts
  - `markdown` - GitHub-flavoured Markdown
  - `rich` - Terminal output with colours and formatting
- `--strip-references` - Remove citations and references section
- `--stream` - Stream response in real-time as it arrives (experimental)

**Global Options:**
- `--verbose, -v` - Enable verbose output (INFO level logging)
- `--debug, -d` - Enable debug output (DEBUG level logging)
- `--log-file PATH` - Write logs to file (default: ~/.config/perplexity-cli/perplexity-cli.log)

**Exit codes:**
- `0` - Success
- `1` - Error

### `perplexity-cli status`

Display authentication status and token information.

### `perplexity-cli logout`

Remove stored authentication token.

### `perplexity-cli configure STYLE`

Set a custom style prompt applied to all queries.

**Example:**
```bash
perplexity-cli configure "be concise"
```

### `perplexity-cli view-style`

Display currently configured style.

### `perplexity-cli clear-style`

Remove configured style.

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
perplexity-cli query "What is Python?"
```

## Troubleshooting

### "Not authenticated"

Run `perplexity-cli auth` to authenticate.

### "Failed to decrypt token"

Token was encrypted on a different machine or with a different user. Run `perplexity-cli auth` to re-authenticate.

### Chrome connection fails

Ensure Chrome is running with `--remote-debugging-port=9222`. Verify the port matches the one you specified.

### Token file has insecure permissions

Token file was modified or has incorrect permissions. Delete the file and re-authenticate:
```bash
rm ~/.config/perplexity-cli/token.json
perplexity-cli auth
```

## Output Formats

### Plain

Plain text output suitable for scripts and piping.

```bash
perplexity-cli query --format plain "What is Python?"
```

### Markdown

GitHub-flavoured Markdown with headers and formatting.

```bash
perplexity-cli query --format markdown "Explain AI" > answer.md
```

### Rich

Terminal output with colours, bold text, and formatted tables (default).

```bash
perplexity-cli query "What is Python?"
```

## Security

- Tokens encrypted at rest using Fernet
- Encryption key derived from system identifiers
- File permissions restricted to owner (0600)
- Tokens validated on each request
- Token expiration detection (warns if token is >30 days old)
- Audit logging for token operations
- No credentials printed to logs

## Testing

Run tests with pytest:

```bash
python -m pytest tests/
```

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
