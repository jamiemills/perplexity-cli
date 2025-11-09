# Perplexity CLI

A production-grade command-line interface for querying Perplexity.ai with persistent authentication.

## Features

- **Authenticate once, query many times** - Token persists across CLI invocations
- **Three output formats** - Plain text, GitHub-flavoured Markdown, or rich terminal with colours and tables
- **Source references** - Automatic extraction and display of web sources
- **Beautiful terminal output** - Styled headers, coloured text, formatted tables (default)
- **Clean output** - Answers to stdout, errors to stderr (pipeable!)
- **Secure storage** - Tokens stored with 0600 permissions in `~/.config/perplexity-cli/`
- **Real-time streaming** - Receives answers via Server-Sent Events
- **Error handling** - Clear, actionable error messages
- **Well tested** - 100+ tests passing with >70% code coverage

## Quick Start

```bash
# Install
uv pip install -e .

# Authenticate (one time)
perplexity-cli auth

# Ask questions
perplexity-cli query "What is Python?"
perplexity-cli query "What is the capital of France?"

# Check status
perplexity-cli status

# Log out
perplexity-cli logout
```

## Installation

### Prerequisites

- **Python 3.12 or higher**
- **uv** package manager
- **Google Chrome** (for authentication)

### Install with uv

```bash
# Clone the repository
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli

# Create virtual environment and install
uv venv --python=3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

The `perplexity-cli` command will be available in your virtual environment.

## Usage

### Authentication

Before using the CLI, you need to authenticate with Perplexity.ai:

```bash
# Start Chrome with remote debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# Authenticate (extracts token from Chrome session)
perplexity-cli auth
```

This will:
1. Connect to Chrome via DevTools Protocol
2. Navigate to Perplexity.ai
3. Extract your authentication token
4. Save it securely to `~/.config/perplexity-cli/token.json`

The token persists, so you only need to authenticate once.

### Querying Perplexity

```bash
# Simple query (uses rich format by default)
perplexity-cli query "What is machine learning?"

# Plain text format (for scripts and piping)
perplexity-cli query --format plain "What is Python?"

# Markdown format (for documentation)
perplexity-cli query --format markdown "Explain quantum computing" > answer.md

# Rich format (colourful terminal output) - default
perplexity-cli query --format rich "What is AI?"

# Save to file
perplexity-cli query --format markdown "Explain AI" > answer.md

# Use in scripts
ANSWER=$(perplexity-cli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"
```

### Check Authentication Status

```bash
perplexity-cli status
```

Shows:
- Authentication status
- Token location
- Username and email (if authenticated)
- Token validity

### Log Out

```bash
perplexity-cli logout
```

Removes stored credentials. You'll need to re-authenticate before making queries.

## Commands

### `perplexity-cli auth [--port PORT]`

Authenticate with Perplexity.ai.

**Options:**
- `--port PORT` - Chrome remote debugging port (default: 9222)

**Example:**
```bash
perplexity-cli auth
perplexity-cli auth --port 9222
```

### `perplexity-cli query "QUESTION" [OPTIONS]`

Submit a query and get an answer with source references.

**Arguments:**
- `QUESTION` - Your question (quoted)

**Options:**
- `--format`, `-f` - Output format (default: `rich`)
  - `plain` - Plain text with underlined headers (good for scripts and piping)
  - `markdown` - GitHub-flavoured Markdown (good for documentation)
  - `rich` - Colourful terminal output with tables and styling
- `--strip-references` - Remove all citations and the references section

**Output:**
- Answer text to stdout
- Source references (if available) displayed after answer
- Errors to stderr

**Exit codes:**
- `0` - Success
- `1` - Error (authentication, network, etc.)

**Examples:**
```bash
# Simple query (rich format with colours and tables)
perplexity-cli query "What is Python?"

# Plain text format (good for scripts)
perplexity-cli query --format plain "What is Python?"

# Markdown format (good for documentation)
perplexity-cli query --format markdown "Explain AI" > answer.md

# Remove all citations and references
perplexity-cli query --strip-references "What is Python?"

# Combine format and strip-references
perplexity-cli query --format plain --strip-references "What is 2+2?"

# Use in scripts
ANSWER=$(perplexity-cli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Extract answer-only text without citations
ANSWER=$(perplexity-cli query --format plain --strip-references "What is Python?")
```

### `perplexity-cli status`

Show authentication status and token information.

**Example:**
```bash
perplexity-cli status
```

**Output:**
```
Perplexity CLI Status
========================================
Status: ✓ Authenticated
Token file: /Users/user/.config/perplexity-cli/token.json
Token length: 484 characters
User: username
Email: user@example.com

✓ Token is valid and working
```

### `perplexity-cli logout`

Remove stored credentials.

**Example:**
```bash
perplexity-cli logout
```

### `perplexity-cli configure "STYLE"`

Configure a custom style prompt to apply to all queries.

Sets a style/prompt that will be automatically appended to all subsequent
queries, allowing you to standardise response formatting without repeating
instructions.

**Arguments:**
- `STYLE` - The custom style prompt (quoted string)

**Example:**
```bash
perplexity-cli configure "be concise and factual"
perplexity-cli configure "provide super brief answers in minimal words"
```

### `perplexity-cli view-style`

Display the currently configured style.

Shows the style prompt that is being applied to queries, or a message if
no style is configured.

**Example:**
```bash
perplexity-cli view-style
```

### `perplexity-cli clear-style`

Remove the configured style.

Clears the style configuration. Queries will no longer have any style prompt
appended.

**Example:**
```bash
perplexity-cli clear-style
```

## Output Formatting

The CLI supports three output formats to suit different use cases.

### Rich Format (Default)

Beautiful terminal output with colours, bold headers, and formatted tables.

**Features:**
- Bold bright cyan title
- Styled headers with colours
- Reference table with columns for #, Source, and URL
- Text wrapping (no truncation)
- Syntax highlighting for code blocks

**Usage:**
```bash
perplexity-cli query "What is Python?"
# or explicitly:
perplexity-cli query --format rich "What is Python?"
```

### Plain Text Format

Clean, simple text with underlined headers. No markdown syntax or colours.

**Features:**
- Headers underlined with `=` characters
- No markdown syntax (`##`, `**`, `*`)
- Horizontal ruler before references
- Perfect for scripts and piping

**Usage:**
```bash
perplexity-cli query --format plain "What is Python?"
```

**Example output:**
```
Summary
=======
Here are the key points...


Details
=======
Content here...

──────────────────────────────────────────────────
References
==========
[1] https://example.com
[2] https://example2.com
```

### Markdown Format

GitHub-flavoured Markdown with proper structure.

**Features:**
- Markdown-formatted answer text with headers preserved
- References as numbered Markdown links with snippets
- Suitable for piping to pandoc or Markdown processors
- Clean output without extra metadata

**Usage:**
```bash
perplexity-cli query --format markdown "What is Python?" > answer.md
```

**Example output:**
```markdown
### Summary
Python is a high-level, general-purpose programming language...

### Details
- Created by Guido van Rossum
- First released in 1991
- Known for readable syntax

## References
1. [Python.org](https://python.org) - "Official Python website"
2. [Wikipedia](https://wikipedia.org) - "Python programming language"
```

### Environment Variable

Set a default format:
```bash
export PERPLEXITY_FORMAT=plain
perplexity-cli query "What is Python?"  # Uses plain format
```

The `--format` flag overrides the environment variable.

### Stripping References

Use `--strip-references` to remove all citations (`[1]`, `[2]`, etc.) and the references section from the output. This is useful when you only want the answer text without sources.

**Usage:**
```bash
# Remove citations and references (keeps all formatting)
perplexity-cli query --strip-references "What is Paris?"

# Combine with plain format for clean answer-only text
perplexity-cli query --format plain --strip-references "What is Paris?"

# Useful in scripts where you only need the answer
ANSWER=$(perplexity-cli query --format plain --strip-references "What is 2+2?")
echo "$ANSWER"
```

**Behaviour:**
- Removes all `[digit]` citation numbers from the answer text
- Removes the entire references section (no heading, no URLs, no snippets)
- Works with all three output formats (plain, markdown, rich)
- The rest of the formatting remains unchanged

**Example with citations removed:**
```
Before (with --strip-references):
The capital of France is Paris[1][2]. Paris is located on the Seine[3].

After (--strip-references applied):
The capital of France is Paris. Paris is located on the Seine.
```

### Style Configuration

Configure a custom style/prompt to apply to all queries automatically. This allows you to standardise response formatting without repeating the same instructions.

**Setting a style:**
```bash
perplexity-cli configure "be concise and factual"
```

**View current style:**
```bash
perplexity-cli view-style
```

**Clear style:**
```bash
perplexity-cli clear-style
```

**How it works:**
- Once configured, the style is automatically appended to every query
- The style is stored in `~/.config/perplexity-cli/style.json`
- The configuration persists across CLI sessions
- Style works with all three output formats (plain, markdown, rich)

**Examples:**
```bash
# Configure a concise style
perplexity-cli configure "answer in one sentence only"

# All subsequent queries will have this style applied
perplexity-cli query "What is Python?"
# Sends: "What is Python?\n\nanswer in one sentence only"

# View what style is configured
perplexity-cli view-style

# Use plain format with configured style (answer-only output)
perplexity-cli query --format plain "What is machine learning?"

# Remove style when you no longer want it
perplexity-cli clear-style
```

**Use cases:**
- Standardise response format: "provide answers in 2-3 sentences"
- Control response length: "answer in under 50 words"
- Specify content type: "provide example code for your explanation"
- Set tone: "be technical but explain for beginners"
- Combine with scripts: Use plain format + style for predictable output

## Configuration

### URL Configuration

The Perplexity base URL and API endpoints are configurable via a JSON configuration file. This is useful for alternative deployments or testing against different environments.

**Configuration file location:**
- **Linux/macOS**: `~/.config/perplexity-cli/urls.json`
- **Windows**: `%APPDATA%\perplexity-cli\urls.json`

**Default configuration** (automatically created on first run):
```json
{
  "perplexity": {
    "base_url": "https://www.perplexity.ai",
    "query_endpoint": "https://www.perplexity.ai/rest/sse/perplexity_ask"
  }
}
```

**Customising URLs:**

Edit the `urls.json` file to use alternative Perplexity instances or deployment URLs. For example:

```json
{
  "perplexity": {
    "base_url": "https://alternative-instance.example.com",
    "query_endpoint": "https://alternative-instance.example.com/rest/sse/perplexity_ask"
  }
}
```

The configuration is automatically created on first run with the default values. Modifications will be picked up immediately on the next CLI invocation.

### Token Storage and Encryption

Tokens are encrypted and stored in:
- **Linux/macOS**: `~/.config/perplexity-cli/token.json`
- **Windows**: `%APPDATA%\perplexity-cli\token.json`

**Encryption**: Tokens are encrypted using Fernet (symmetric encryption) with a key derived from the system machine hostname and OS user. This ensures:
- Tokens are unreadable on disk without access to the system
- Tokens cannot be transferred between machines
- No user passwords to manage (automatic and transparent)

**File format** (encrypted):
```json
{
  "version": 1,
  "encrypted": true,
  "token": "encrypted_token_data_here"
}
```

**File permissions**: `0600` (owner read/write only)

### Token Security

- Tokens encrypted at rest using Fernet (AES-128-CBC)
- Encryption key derived from system identifiers (hostname + OS user)
- Stored with restrictive file permissions (0600)
- Never printed to screen or logs
- Validated on each API request

### Token Portability

Tokens encrypted with this approach are **not portable** between machines or users:
- Encrypting a token on Machine A will not decrypt on Machine B
- If you need to use the CLI on a different machine, you must re-authenticate
- This is intentional for security — it prevents stolen tokens from being usable elsewhere

If you move to a new machine or switch OS users, simply re-authenticate:
```bash
perplexity-cli auth
```

## Troubleshooting

### "Not authenticated"

**Problem**: No stored token found.

**Solution**:
```bash
perplexity-cli auth
```

### "Authentication failed. Token may be expired."

**Problem**: Token is no longer valid.

**Solution**:
```bash
perplexity-cli auth  # Re-authenticate
```

### "Failed to connect to Chrome"

**Problem**: Chrome is not running with remote debugging.

**Solution**:
```bash
# Start Chrome with remote debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# Then authenticate
perplexity-cli auth
```

### "Token file has insecure permissions"

**Problem**: Token file permissions are not 0600.

**Solution**:
```bash
chmod 0600 ~/.config/perplexity-cli/token.json
```

### "Network error"

**Problem**: Cannot connect to Perplexity.ai.

**Solution**:
- Check your internet connection
- Verify Perplexity.ai is accessible
- Check firewall settings

### "Rate limit exceeded"

**Problem**: Too many requests in a short time.

**Solution**:
- Wait a few minutes
- Reduce query frequency

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli

# Create virtual environment
uv venv --python=3.12
source .venv/bin/activate

# Install with dev dependencies
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_cli.py -v

# Run with coverage
pytest tests/ --cov=src/perplexity_cli --cov-report=term-missing

# Run only integration tests
pytest tests/ -m integration
```

### Code Quality

```bash
# Lint code
ruff check src/ tests/

# Format code
ruff format src/ tests/

# Check formatting
ruff format --check src/ tests/
```

### Manual Testing

```bash
# Test authentication and token extraction
python tests/save_auth_token.py

# Test simple query
python tests/test_query_simple.py

# Test API endpoints
python tests/discover_api_endpoints.py

# See live SSE streaming
python tests/test_query_realtime.py
```

## Architecture

### Project Structure

```
perplexity-cli/
├── src/perplexity_cli/
│   ├── __init__.py
│   ├── cli.py              # Click CLI commands
│   ├── auth/               # Authentication module
│   │   ├── oauth_handler.py    # Chrome DevTools auth
│   │   └── token_manager.py    # Secure token storage
│   ├── api/                # API client module
│   │   ├── client.py           # SSE HTTP client
│   │   ├── endpoints.py        # API abstractions
│   │   └── models.py           # Data models
│   ├── formatting/         # Output formatting module
│   │   ├── base.py             # Abstract formatter interface
│   │   ├── plain.py            # Plain text formatter
│   │   ├── markdown.py         # Markdown formatter
│   │   ├── rich.py             # Rich terminal formatter
│   │   └── registry.py         # Formatter registry
│   └── utils/              # Utilities
│       └── config.py           # Config management
├── tests/                  # Test suite
├── .claudeCode/            # Documentation
└── pyproject.toml          # Package configuration
```

### How It Works

1. **Authentication** (`auth/`)
   - Uses Chrome DevTools Protocol to extract session token
   - Stores JWT token with 0600 permissions
   - Token persists across CLI invocations

2. **API Client** (`api/`)
   - Submits queries to `POST /rest/sse/perplexity_ask`
   - Handles Server-Sent Events (SSE) streaming
   - Parses responses and extracts answer text

3. **CLI** (`cli.py`)
   - Click framework for command-line interface
   - Connects authentication and API client
   - Provides user-friendly error messages

4. **Formatting** (`formatting/`)
   - Pluggable formatter system for multiple output styles
   - Plain text with underlined headers
   - GitHub-flavoured Markdown with links
   - Rich terminal with colours, tables, and syntax highlighting

## API Details

### Endpoint

```
POST https://www.perplexity.ai/rest/sse/perplexity_ask
```

### Authentication

```
Authorization: Bearer <jwt_token>
```

### Request Format

```json
{
  "params": {
    "language": "en-US",
    "timezone": "Europe/London",
    "search_focus": "internet",
    "mode": "copilot",
    "frontend_uuid": "<uuid>",
    "frontend_context_uuid": "<uuid>",
    "version": "2.18"
  },
  "query_str": "Your question"
}
```

### Response Format

Server-Sent Events (SSE) stream:
```
event: message
data: {"status": "PENDING", "blocks": [...], ...}

event: message
data: {"status": "COMPLETE", "blocks": [...], "final_sse_message": true}
```

Answer extracted from `blocks` with `intended_usage: "ask_text"`.

Web sources automatically extracted from `blocks` with `intended_usage: "web_results"` and displayed as numbered references.

## Testing

### Test Suite

- **90+ tests** total (all passing)
- **22 unit tests** (auth module)
- **14 unit tests** (API client)
- **11 unit tests** (data models)
- **10 integration tests** (API endpoints)
- **15 unit tests** (CLI)
- **9 integration tests** (token API)
- **9 integration tests** (auth flow)

### Test Coverage

- Overall: 72%
- Critical modules: >85%
- Models: 100%

### Security Tests

- 13 dedicated security tests
- File permission enforcement
- Token handling
- Error message sanitization

## Security

### Token Security

- ✅ Tokens stored with 0600 permissions (owner only)
- ✅ JWT encrypted with AES-256-GCM
- ✅ Never printed or logged
- ✅ Validated before each request

### Code Security

- ✅ No hardcoded secrets
- ✅ No credential leakage
- ✅ SSL/TLS validation enabled
- ✅ No command injection vulnerabilities
- ✅ Secure dependencies (no known CVEs)

**Security Rating**: A- (Excellent)
**Production Approved**: ✅ Yes

See [SECURITY_REVIEW.md](.claudeCode/SECURITY_REVIEW.md) for detailed audit.

## Dependencies

### Runtime

- `click>=8.0` - CLI framework
- `httpx>=0.25` - HTTP client with SSE support
- `websockets>=12.0` - Chrome DevTools Protocol
- `rich>=13.0` - Terminal formatting and styling

### Development

- `pytest>=7.0` - Testing framework
- `pytest-mock>=3.0` - Mocking
- `pytest-asyncio>=1.2.0` - Async testing
- `pytest-cov>=7.0` - Coverage reporting
- `ruff>=0.1` - Linting and formatting

All dependencies are well-maintained with permissive open-source licences (MIT/BSD).

## Documentation

- [PLAN.md](.claudeCode/PLAN.md) - Complete implementation plan
- [WORKFLOW.md](.claudeCode/WORKFLOW.md) - Phase-by-phase workflow
- [CLAUDE.md](.claudeCode/CLAUDE.md) - Operational log and decisions
- [API_DISCOVERY.md](.claudeCode/API_DISCOVERY.md) - API endpoint documentation
- [CODE_QUALITY.md](.claudeCode/CODE_QUALITY.md) - Code quality standards
- [SECURITY_REVIEW.md](.claudeCode/SECURITY_REVIEW.md) - Security audit
- [TESTING_GUIDE.md](.claudeCode/TESTING_GUIDE.md) - Testing instructions

## Contributing

### Code Standards

- Python 3.12+
- Type hints required on all functions
- Docstrings required on all public functions
- Ruff linting must pass
- All tests must pass
- Follow existing code structure

### Testing Requirements

- Unit tests for new functionality
- Integration tests for workflows
- Security tests for sensitive operations
- Maintain >70% code coverage

## Acknowledgements

Built with:
- [Click](https://click.palletsprojects.com/) - CLI framework
- [httpx](https://www.python-httpx.org/) - HTTP client
- [websockets](https://websockets.readthedocs.io/) - WebSocket library
- [Rich](https://github.com/Textualize/rich) - Terminal formatting and styling
- [pytest](https://pytest.org/) - Testing framework
- [ruff](https://github.com/astral-sh/ruff) - Linting and formatting

Powered by [Perplexity.ai](https://www.perplexity.ai/)
