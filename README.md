# Perplexity CLI

Query Perplexity.ai from your terminal. Get answers with source citations, structured JSON output, real-time streaming, file attachments, and thread export -- all from a single command.

[![PyPI](https://img.shields.io/pypi/v/pxcli)](https://pypi.org/project/pxcli/)

## Try it now

No install required. Run directly with `uvx`:

```bash
uvx pxcli query "What happened in AI this week?"
```

That's it. You get an answer with source references, directly in your terminal.

## Install

For regular use, install the package so `pxcli` is always available:

```bash
uv pip install pxcli
```

Both `pxcli` and `perplexity-cli` work as command names after installation.

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest  # verify setup
```
</details>

## Quick start

### 1. Ask a question (no setup needed)

```bash
pxcli query "What is machine learning?"
```

### 2. Authenticate for full features (one-time, optional)

```bash
pxcli auth login
```

This connects to Chrome, waits for you to sign in to Perplexity.ai, and saves your session token encrypted locally. See [Authentication setup](#authentication-setup) for the full walkthrough.

### 3. Use everything

```bash
pxcli query --attach report.pdf "Summarise this document"
pxcli query --model claude46sonnet "Explain Docker"
pxcli query --json "What is Python?" | jq -r '.result.answer'
pxcli threads export
```

## Shell shortcuts

Add these to your `~/.zshrc` (or `~/.bashrc`) for quick access:

```bash
# Quick question (rich terminal output, no citation markers)
px() { uvx pxcli query --strip-references --format rich "$*"; }

# Get just the commands to run (plain text)
pxc() { uvx pxcli query --strip-references --format plain "$*. Just give me the commands to run on a Mac. Put them on a single line"; }

# JSON answer only
pxj() { uvx pxcli query --json "$*" | jq -r '.result.answer'; }
```

Then:

```bash
px "what is the latest version of Python?"
pxc "how can I find what remote branches exist for this repo"
pxj "what is the capital of France?"
```

## MCP server

`pxcli` can also run as an MCP server for coding agents. It exposes two tools:

- `perplexity_quick_info`: Fast lookups, short explanations, fact checks, and recent info.
- `perplexity_deep_info`: Multi-step research, comparisons, timelines, and broader synthesis.

Both tools support `output_format` values `json`, `markdown`, and `plain`.

### What the tools are for

- Use `perplexity_quick_info` for current facts, short summaries, and quick validation.
- Use `perplexity_deep_info` for broader research, comparisons, timelines, and synthesis across sources.
- Use `output_format=json` when another agent step needs structured fields.
- Use `output_format=markdown` for readable summaries.
- Use `output_format=plain` for compact text and terminal-oriented follow-up work.

### Run the server

Run the MCP server over stdio:

```bash
uv run pxcli-mcp
```

Run it from a local checkout without activating the environment:

```bash
uv run --directory /path/to/perplexity-cli pxcli-mcp
```

Run it directly from GitHub without cloning:

```bash
uvx --from git+https://github.com/jamiemills/perplexity-cli.git pxcli-mcp
```

Run it from PyPI:

```bash
uvx --from pxcli pxcli-mcp
```

Or after installing `pxcli` locally:

```bash
pxcli-mcp
```

Run it over Streamable HTTP:

```bash
uv run pxcli-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

This serves the MCP endpoint at `http://127.0.0.1:8000/mcp` by default.

### Claude Code

Project-local config for the current repo only:

```bash
claude mcp add --transport stdio --scope local perplexity-cli -- \
  uv run --directory /path/to/perplexity-cli pxcli-mcp
```

User-level config for all projects:

```bash
claude mcp add --transport stdio --scope user perplexity-cli -- \
  uv run --directory /path/to/perplexity-cli pxcli-mcp
```

Project-local HTTP config:

```bash
claude mcp add --transport http --scope local perplexity-cli \
  http://127.0.0.1:8000/mcp
```

User-level HTTP config:

```bash
claude mcp add --transport http --scope user perplexity-cli \
  http://127.0.0.1:8000/mcp
```

### Codex

Project-local config in `.codex/config.toml`:

```toml
[mcp_servers.perplexity_cli]
command = "uv"
args = ["run", "--directory", "/path/to/perplexity-cli", "pxcli-mcp"]
```

User-level config in `~/.codex/config.toml`:

```toml
[mcp_servers.perplexity_cli]
command = "uv"
args = ["run", "--directory", "/path/to/perplexity-cli", "pxcli-mcp"]
```

If you prefer the Codex CLI, add the server first and then move the resulting config to the scope you want:

```bash
codex mcp add perplexity-cli -- uv run --directory /path/to/perplexity-cli pxcli-mcp
```

Project-local HTTP config in `.codex/config.toml`:

```toml
[mcp_servers.perplexity_cli]
url = "http://127.0.0.1:8000/mcp"
```

User-level HTTP config in `~/.codex/config.toml`:

```toml
[mcp_servers.perplexity_cli]
url = "http://127.0.0.1:8000/mcp"
```

### OpenCode

Project-local config in `opencode.json` or `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "perplexity_cli": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/path/to/perplexity-cli", "pxcli-mcp"],
      "enabled": true
    }
  }
}
```

User-level config in `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "perplexity_cli": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/path/to/perplexity-cli", "pxcli-mcp"],
      "enabled": true
    }
  }
}
```

Project-local HTTP config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "perplexity_cli": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp",
      "enabled": true
    }
  }
}
```

User-level HTTP config in `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "perplexity_cli": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp",
      "enabled": true
    }
  }
}
```

### Summary

- Use stdio when the MCP server should be launched by the client on demand.
- Use Streamable HTTP when you want to run one long-lived server and let multiple clients connect to it.
- Use project-local config when the MCP server should only be available in this repo.
- Use user-level config when you want the same Perplexity MCP server available in all your projects.

## Querying

### Basic usage

```bash
# Rich terminal output (default when interactive)
pxcli query "What is machine learning?"

# Stream the response as it arrives
pxcli query --stream "What is machine learning?"

# Remove citation markers [1], [2] and the references section
pxcli query --strip-references "What is machine learning?"

# Read query from stdin
echo "What is Python?" | pxcli query -

# Set a timeout (seconds)
pxcli query --timeout 120 "Complex research question"
```

### Output formats

The default is `rich` when stdout is a terminal, or `plain` when piped.

```bash
# Plain text (good for scripts, piping, saving to .txt)
pxcli query --format plain "What is Python?"

# GitHub-flavoured Markdown
pxcli query --format markdown "Explain Docker" > docker.md

# Structured JSON envelope (see JSON output section below)
pxcli query --json "What is Python?"
```

### File attachments

Attach files to provide context for your query. Requires [authentication](#authentication-setup).

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

### Model selection

Choose a specific model for your query:

```bash
pxcli query --model gpt54 "What is Python?"
pxcli query -m claude46sonnet "Explain Docker"

# List available models for your subscription tier
pxcli models list
pxcli models list --json | jq '.result.models[].model_id'
```

### Combining flags

All flags compose freely:

```bash
pxcli query -f plain -S "What is 2+2?"
pxcli query --stream --strip-references "Explain Kubernetes"
pxcli query --format markdown -S "How does DNS work?" > dns.md
pxcli query --json --timeout 60 "Complex analysis question"
pxcli query --json --stream "What is Python?"
```

### Query options reference

| Option | Short | Description |
|---|---|---|
| `--format` | `-f` | `plain`, `markdown`, `rich` (default), `json` |
| `--json` | | Structured JSON envelope output |
| `--stream` / `--no-stream` | `-s` | Stream response incrementally |
| `--strip-references` | `-S` | Remove citation markers and references section |
| `--attach` | `-a` | Attach file(s) or directory |
| `--model` | `-m` | Model identifier (see `pxcli models list`) |
| `--timeout` | `-t` | Request timeout in seconds (default: 60) |
| `--schema` | | Embed JSON Schema in envelope (with `--json`) |
| `--request-param` | | Inject extra key=value into API request (experimental) |

## JSON output

Every command that accepts `--json` produces a structured envelope on stdout. This makes `pxcli` straightforward to integrate into scripts, pipelines, and agent workflows.

### Success envelope

```json
{
  "ok": true,
  "command": "pxcli query",
  "result": {
    "answer": "Python is a high-level programming language...",
    "references": [
      {
        "index": 1,
        "title": "Python.org",
        "url": "https://www.python.org",
        "snippet": "Python is a programming language..."
      }
    ]
  },
  "meta": {
    "duration_ms": 1423,
    "version": "0.7.1",
    "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "truncated": false
  },
  "next_actions": [
    {
      "command": "pxcli query",
      "description": "Ask a follow-up question"
    }
  ]
}
```

### Error envelope

When `ok` is `false`, the envelope contains error details and a suggested fix:

```json
{
  "ok": false,
  "command": "pxcli query",
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

Error codes: `authentication_required`, `permission_denied`, `rate_limited`, `network_error`, `timeout`, `upstream_schema_error`, `configuration_error`, `attachment_error`, `validation_error`, `not_found`, `internal_error`.

### Result shapes by command

| Command | `.result` fields |
|---|---|
| `query` | `{answer, references}` |
| `auth login` | `{token_path, cookies_stored}` |
| `auth logout` | `{credentials_existed}` |
| `auth status` | `{authenticated, token_path, token_age_days, cookies_stored, verified}` |
| `config set` | `{key, value}` |
| `config show` | `{config_path, save_cookies, debug_mode, env_overrides}` |
| `style set` | `{style}` |
| `style show` | `{style}` |
| `style clear` | `{had_style}` |
| `threads export` | `{threads, total, output_path, date_range}` |
| `models list` | `{models}` |
| `doctor security` | `{storage_backend, token_path, token_permissions, cache_path, cache_permissions, cookies_enabled}` |
| `skill show` | `{content}` |

### Working with jq

```bash
# Extract the answer text (use -r so newlines render properly)
pxcli query --json "What is Python?" | jq -r '.result.answer'

# Get reference URLs
pxcli query --json "What is Python?" | jq -r '.result.references[].url'

# Count references
pxcli query --json "What is Python?" | jq '.result.references | length'

# Get timing metadata
pxcli query --json "What is Python?" | jq '.meta.duration_ms'

# Check success
pxcli query --json "What is Python?" | jq '.ok'

# Get suggested next actions
pxcli query --json "What is Python?" | jq -r '.next_actions[].command'
```

### NDJSON streaming

Use `--json --stream` together for structured streaming. Each line is a valid JSON object:

```bash
pxcli query --json --stream "What is Python?"
```

```
{"type": "start", "command": "pxcli query --json --stream", "ts": "2025-05-09T10:00:00+00:00"}
{"type": "chunk", "text": "Python is a", "ts": "2025-05-09T10:00:01+00:00"}
{"type": "chunk", "text": " high-level programming language...", "ts": "2025-05-09T10:00:02+00:00"}
{"type": "result", "ok": true, "command": "...", "result": {...}, "meta": {...}, "next_actions": [...], "ts": "2025-05-09T10:00:03+00:00"}
```

Event types: `start` (first line), `chunk` (incremental content), `result` (final line with full envelope).

Without `--json`, `--stream` produces raw text as it arrives.

### JSON Schema

Retrieve the full Pydantic-generated schema for all envelope types:

```bash
pxcli schema                                    # full schema
pxcli schema | jq '.success_envelope'           # success envelope only
pxcli schema | jq '.commands'                   # per-command result definitions
pxcli schema | jq '.commands["query"]'          # query result schema
```

Or embed the schema inline with any `--json` response:

```bash
pxcli query --json --schema "What is Python?"   # adds $schema key to envelope
```

### Scripting examples

**Shell:**

```bash
# Capture answer in a variable
ANSWER=$(pxcli query --format plain "What is 2+2?")
echo "The answer is: $ANSWER"

# Error handling with exit codes
pxcli query --json "Your question"
rc=$?
case $rc in
  0) echo "Success" ;;
  4) echo "Auth needed -- run: pxcli auth login" ;;
  6) echo "Transient error -- retrying..." && sleep 2 && pxcli query --json "Your question" ;;
  *) echo "Failed with exit code $rc" ;;
esac

# Check .ok before processing JSON
response=$(pxcli query --json "Your question")
if echo "$response" | jq -e '.ok' > /dev/null 2>&1; then
  echo "$response" | jq -r '.result.answer'
else
  echo "$response" | jq -r '.error.message' >&2
  echo "$response" | jq -r '.fix' >&2
fi
```

**Python:**

```python
import json
import subprocess
import sys

result = subprocess.run(
    ["pxcli", "query", "--json", "What is Python?"],
    capture_output=True, text=True,
)

if result.returncode != 0:
    print(f"pxcli exited with code {result.returncode}", file=sys.stderr)
    sys.exit(result.returncode)

envelope = json.loads(result.stdout)

if not envelope["ok"]:
    print(f"Error: {envelope['error']['message']}", file=sys.stderr)
    print(f"Fix: {envelope['fix']}", file=sys.stderr)
    sys.exit(1)

print(envelope["result"]["answer"])
for ref in envelope["result"]["references"]:
    print(f"  [{ref['index']}] {ref['title']}: {ref['url']}")
```

**Python (NDJSON streaming):**

```python
import json
import subprocess

proc = subprocess.Popen(
    ["pxcli", "query", "--json", "--stream", "What is Python?"],
    stdout=subprocess.PIPE, text=True,
)

for line in proc.stdout:
    event = json.loads(line)
    if event["type"] == "chunk":
        print(event["text"], end="", flush=True)
    elif event["type"] == "result":
        refs = event["result"]["references"]
        print(f"\n\n{len(refs)} references found.")

proc.wait()
```

## Authentication setup

Authentication is optional for basic queries but required for file attachments (`--attach`), thread export, and model listing.

### Step 1: Install Chrome for Testing

Download a dedicated Chrome instance (keeps testing separate from your main browser):

```bash
npx @puppeteer/browsers install chrome@stable
```

### Step 2: Create a shell alias

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'
```

Adjust the path for your platform. The `mac_arm-*` pattern matches the version directory.

### Step 3: Authenticate

```bash
# Terminal 1: Start Chrome with debugging enabled
chromefortesting

# Terminal 2: Run authentication
pxcli auth login
```

The process connects to Chrome, navigates to Perplexity.ai, waits for you to sign in, extracts your session token, and saves it encrypted to `~/.config/perplexity-cli/token.json`.

Once complete, you do not need to authenticate again unless the token expires or you run `pxcli auth logout`.

### Custom port

If port 9222 is in use, start Chrome with a different port and match it:

```bash
pxcli auth login --port 9223
```

### Auth status

```bash
pxcli auth status                # local check
pxcli auth status --verify       # live API verification
pxcli auth status --json         # JSON envelope output
```

### Logout

```bash
pxcli auth logout
```

### What requires authentication?

| Feature | Auth required? |
|---|---|
| `query` (basic) | No |
| `query --attach` (file attachments) | Yes |
| `models list` | Yes |
| `threads export` | Yes |
| `auth status` | No (reports unauthenticated state) |
| `style set/show/clear` | No (local only) |
| `config set/show` | No (local only) |
| `doctor security` | No (local only) |
| `schema` | No |
| `completion` | No |
| `skill show` | No |

## Response styles

Set a persistent style prompt that is appended to every query. This controls the tone and format of responses without repeating instructions.

```bash
# Set a style
pxcli style set "be brief and concise"

# View the current style
pxcli style show

# Clear the style
pxcli style clear
```

The style is stored in `~/.config/perplexity-cli/style.json` and persists across sessions. All three commands accept `--json` for structured output.

## Thread export

Export your Perplexity conversation history to CSV. Requires authentication.

```bash
# Export all threads
pxcli threads export

# Filter by date range
pxcli threads export --from-date 2025-01-01
pxcli threads export --from-date 2025-01-01 --to-date 2025-12-31

# Custom output file
pxcli threads export --output my-threads.csv

# Bypass local cache
pxcli threads export --force-refresh

# Clear cache before export
pxcli threads export --clear-cache

# JSON envelope output
pxcli threads export --json
pxcli threads export --json | jq '.result.threads[] | .title'
```

### CSV format

```csv
title,created_at,url
"How does quantum computing work?",2025-05-08T14:30:00+00:00,https://www.perplexity.ai/search/...
"Best Python testing frameworks",2025-05-07T09:15:00+00:00,https://www.perplexity.ai/search/...
```

Fields: `title`, `created_at` (ISO 8601 with timezone), `url`.

### Caching

Thread exports are cached locally in encrypted form at `~/.config/perplexity-cli/threads-cache.json`. The cache is updated incrementally on each export. Use `--force-refresh` to bypass the cache or `--clear-cache` to delete it.

### Thread export options

| Option | Short | Description |
|---|---|---|
| `--from-date` | | Start date filter, inclusive (YYYY-MM-DD) |
| `--to-date` | | End date filter, inclusive (YYYY-MM-DD) |
| `--output` | `-o` | Output CSV path (default: `threads-TIMESTAMP.csv`) |
| `--force-refresh` | | Bypass local cache |
| `--clear-cache` | | Delete cache before export |
| `--json` | | JSON envelope output instead of CSV |
| `--schema` | | Embed JSON Schema in envelope (with `--json`) |

## Configuration

### Feature toggles

Configuration is stored in `~/.config/perplexity-cli/config.json`:

```json
{
  "version": 1,
  "features": {
    "save_cookies": false,
    "debug_mode": false
  }
}
```

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

All endpoint fields are full URLs. If Perplexity changes an endpoint, update the relevant field without modifying any code.

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
| `PERPLEXITY_SAVE_COOKIES` | `true` / `false` -- override cookie storage |
| `PERPLEXITY_DEBUG_MODE` | `true` / `false` -- override debug mode |
| `PERPLEXITY_RATE_LIMITING_ENABLED` | `true` / `false` |
| `PERPLEXITY_RATE_LIMITING_RPS` | Requests per period (integer) |
| `PERPLEXITY_RATE_LIMITING_PERIOD` | Period in seconds (integer) |
| `XDG_CONFIG_HOME` | XDG base directory for config (default: `~/.config`) |
| `NO_COLOR` | Disable coloured output (any value) |
| `PXCLI_SESSION_LOG` | Set to `true` to enable NDJSON session logging |

## Shell completion

Generate tab-completion scripts for commands, subcommands, and options:

```bash
# Bash -- add to ~/.bashrc
eval "$(pxcli completion bash)"

# Zsh -- add to ~/.zshrc
eval "$(pxcli completion zsh)"

# Fish
pxcli completion fish | source
```

## Diagnostics

### Security report

```bash
pxcli doctor security
pxcli doctor security --json
```

Reports storage backend, token file path and permissions, cache file path and permissions, and whether cookie storage is enabled. Useful for verifying that credentials are stored with appropriate restrictions (e.g. 0600).

### Live token verification

```bash
pxcli auth status --verify
```

Performs a live API check to confirm the stored token is valid, beyond simply checking local file state.

### Logging

```bash
pxcli --verbose query "question"     # INFO level logging to stderr
pxcli --debug query "question"       # DEBUG level logging (HTTP details, timing)
pxcli --log-file /tmp/debug.log query "question"   # Log to file
```

Debug mode can also be enabled persistently:

```bash
pxcli config set debug_mode true
```

## Agent integration

`pxcli` includes a built-in skill definition for AI agents and LLM-based toolchains:

```bash
pxcli skill show          # display the skill definition
pxcli skill show --json   # JSON envelope with skill content
```

The skill describes how agents can use `pxcli` as a web search and research tool, including JSON parsing patterns, NDJSON streaming integration, error handling, and workflow examples. The `next_actions` array in every JSON envelope suggests follow-up commands that agents can chain automatically.

## Global options

These options apply to all commands:

| Option | Short | Description |
|---|---|---|
| `--version` | | Show version and exit |
| `--verbose` | `-v` | INFO level logging |
| `--debug` | `-d` | DEBUG level logging (overrides `--verbose`) |
| `--log-file PATH` | | Log file path (default: `~/.config/perplexity-cli/perplexity-cli.log`) |
| `--quiet` | `-q` | Suppress non-essential output |
| `--no-color` | | Disable coloured output |

## Command reference

### Command tree

```
pxcli
|-- query QUERY [OPTIONS]          Submit a query
|-- schema                         Output JSON schema for envelopes
|-- auth
|   |-- login [--port PORT]        Authenticate via Chrome DevTools
|   |-- logout                     Remove stored credentials
|   +-- status [--verify]          Check authentication state
|-- config
|   |-- set KEY VALUE              Set a configuration option
|   +-- show                       Display current configuration
|-- models
|   +-- list                       List available models
|-- style
|   |-- set STYLE                  Set a persistent style prompt
|   |-- show                       View current style
|   +-- clear                      Remove style
|-- threads
|   +-- export [OPTIONS]           Export thread library to CSV
|-- skill
|   +-- show                       Display agent skill definition
|-- doctor
|   +-- security                   Report credential storage state
+-- completion
    |-- bash                       Generate Bash completion script
    |-- zsh                        Generate Zsh completion script
    +-- fish                       Generate Fish completion script
```

All subcommands under `auth`, `config`, `models`, `style`, `threads`, `skill`, `doctor`, and `completion` accept `--json` and `--schema` for structured output (where applicable).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure |
| `2` | Usage error (bad arguments, missing input) |
| `3` | Not found |
| `4` | Authentication required |
| `5` | Conflict |
| `6` | Transient error (timeout, rate limit -- retry may help) |
| `7` | Validation error |
| `130` | Interrupted (Ctrl+C) |

For scripting, prefer checking the exit code first. In `--json` mode, both success and error responses are valid JSON envelopes on stdout -- check the `.ok` field.

## Security

- Tokens encrypted at rest using Fernet symmetric encryption
- Key derived via PBKDF2-HMAC with 100,000 iterations from the system hostname and OS user
- File permissions restricted to owner only (0600)
- Token validity checked on each request, with age warnings after 30 days
- No credentials written to logs
- Cookie storage is opt-in and uses the same encrypted file

This is machine-bound obfuscation rather than OS keychain-backed secret storage. It prevents casual copying between machines but does not protect against other local processes that can already read the token file. If cookie storage is enabled, browser cookies are stored alongside the token and should be treated as sensitive session material.

### Token storage locations

| Platform | Path |
|---|---|
| Linux / macOS | `~/.config/perplexity-cli/token.json` |
| Windows | `%APPDATA%\perplexity-cli\token.json` |

## Troubleshooting

| Problem | Solution |
|---|---|
| "Not authenticated" | Run `pxcli auth login` |
| "Failed to decrypt token" | Token was encrypted on a different machine or user. Run `pxcli auth login` to re-authenticate. |
| Chrome connection fails | Ensure Chrome is running with `--remote-debugging-port=9222` and the port matches. |
| Token file has insecure permissions | Delete the file and re-authenticate: `rm ~/.config/perplexity-cli/token.json && pxcli auth login` |

## Prerequisites

- Python 3.12 or later
- Google Chrome (for initial authentication only)

## Development

### Setup

```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uv run lefthook install
```

### Testing

```bash
uv run pytest                   # safe default test suite (1369 tests)
uv run pytest -m security       # security tests only
uv run pytest -m fuzz           # fuzz tests (17 atheris harnesses)
```

### Makefile

The `Makefile` is the single source of truth for all lint, test, and build commands.
Both CI (GitHub Actions) and local git hooks (`lefthook`) delegate to it.

```bash
make ci                         # run the full CI pipeline locally
make lint                       # ruff + bandit + vulture + semgrep
make test                       # pytest with coverage
make build                      # build wheel and sdist
```

### Releasing

Use the `release` target to bump the version, run CI, commit, tag, and push:

```bash
make release V=0.8.0
```

This runs `uv lock`, the full CI pipeline, commits the version bump, creates a
`v0.8.0` tag, and pushes both to `origin`. The `publish-to-pypi` workflow then
publishes to PyPI via OIDC trusted publishing.

The detailed release workflow is documented in `.claude/PUBLISHING.md`.

### Compatibility

Supported Python versions: 3.12+.  CI tests against 3.12.

## Project governance

- Contributing guide: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`
- Licence: `LICENSE`
- Changelog: GitHub Releases

## Licence

MIT
