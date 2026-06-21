---
name: pxcli-question-answering
description: Query Perplexity.ai from the terminal. Returns structured JSON envelopes with answers, source references, exit codes, and next-action suggestions. Use when you need current information, comprehensive answers with citations, or programmatic integration via JSON/NDJSON output.
---

# pxcli — Perplexity CLI for Question Answering

## What Is pxcli?

pxcli is a command-line interface for querying Perplexity.ai. It returns comprehensive answers with source citations directly from your terminal, with structured JSON output suitable for programmatic use and agent integration.

## When to Use This Skill

Use pxcli when you need to:

- **Find current information**: Ask about recent events, news, or developments
- **Get detailed explanations**: Request comprehensive answers with source references
- **Research topics**: Explore subjects with verified sources cited in the response
- **Parse structured data**: Use JSON envelope output to integrate answers into workflows
- **Avoid multiple tools**: Replace separate web search requests with a single command

## Setup and Authentication

### One-Time Authentication

```bash
# Install Chrome for Testing
npx @puppeteer/browsers install chrome@stable

# Create a shell alias
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'

# Terminal 1: Start Chrome
chromefortesting

# Terminal 2: Authenticate
pxcli auth login
```

Once authenticated, credentials persist until you run `pxcli auth logout`.

### Checking Authentication Status

```bash
pxcli auth status
```

Returns JSON when using `--json`:

```json
{
  "ok": true,
  "command": "pxcli auth status --json",
  "result": {
    "authenticated": true,
    "token_path": "~/.config/pxcli/token.json",
    "token_age_days": 3,
    "cookies_stored": true,
    "verified": true
  },
  "meta": { "duration_ms": 42, "version": "0.7.0", "trace_id": "..." },
  "next_actions": []
}
```

## Commands Reference

| Command | Description |
|---|---|
| `pxcli query "..."` | Ask a question |
| `pxcli auth login` | Authenticate with Perplexity.ai |
| `pxcli auth logout` | Remove stored credentials |
| `pxcli auth status` | Check authentication status |
| `pxcli config set KEY VALUE` | Set a configuration value |
| `pxcli config show` | Display current configuration |
| `pxcli style set "..."` | Set a style prompt for all queries |
| `pxcli style show` | Display current style prompt |
| `pxcli style clear` | Remove style prompt |
| `pxcli threads export` | Export conversation threads |
| `pxcli skill show` | Display this skill definition |
| `pxcli completion {bash\|zsh\|fish}` | Generate shell completion scripts |
| `pxcli schema` | Output JSON schema for envelopes |
| `pxcli doctor security` | Run security diagnostics |

## Basic Usage

### Simple Query

```bash
pxcli query "What are the latest developments in quantum computing?"
```

### Query with Options

```bash
# Plain text output
pxcli query --format plain "What is Python?"

# Remove citation numbers and references
pxcli query --strip-references "Explain machine learning"

# Stream response in real time
pxcli query --stream "Your question"

# Pipe question via stdin
echo "What is Python?" | pxcli query -

# Attach a file for context
pxcli query --attach report.pdf "Summarise this document"

# Set request timeout
pxcli query --timeout 30 "Your question"

# Suppress non-essential output
pxcli query --quiet "Your question"

# Disable coloured output
pxcli query --no-color "Your question"
```

## JSON Envelope Format

Request JSON output with `--json` (or `--format json`):

```bash
pxcli query --json "What is the capital of France?"
```

### Success Envelope

Every JSON response is wrapped in a standard envelope:

```json
{
  "ok": true,
  "command": "pxcli query --json \"What is the capital of France?\"",
  "result": {
    "answer": "The capital of France is Paris...",
    "references": [
      {
        "index": 1,
        "title": "Paris - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Paris",
        "snippet": "Paris is the capital and largest city of France..."
      }
    ]
  },
  "meta": {
    "duration_ms": 1423,
    "version": "0.7.0",
    "trace_id": "abc123"
  },
  "next_actions": [
    {
      "command": "pxcli query --json \"Tell me more about Paris\"",
      "description": "Follow-up query about Paris"
    }
  ]
}
```

### Error Envelope

When `.ok` is `false`, the envelope contains error details and a suggested fix:

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

### Error Code Strings

`authentication_required`, `permission_denied`, `rate_limited`, `network_error`, `timeout`, `upstream_schema_error`, `configuration_error`, `attachment_error`, `validation_error`, `not_found`, `internal_error`

### Checking `.ok` Before Processing

Always check `.ok` before accessing `.result`:

```bash
response=$(pxcli query --json "Your question")
if echo "$response" | jq -e '.ok' > /dev/null 2>&1; then
  echo "$response" | jq -r '.result.answer'
else
  echo "$response" | jq -r '.error.message' >&2
  echo "$response" | jq -r '.fix' >&2
fi
```

### Per-Command Result Shapes

| Command | `.result` payload |
|---|---|
| `query` | `{answer, references}` |
| `auth status` | `{authenticated, token_path, token_age_days, cookies_stored, verified}` |
| `auth login` | `{token_path, cookies_stored}` |
| `auth logout` | `{credentials_existed}` |
| `config show` | `{config_path, save_cookies, debug_mode, env_overrides}` |
| `config set` | `{key, value}` |
| `style set` | `{style}` |
| `style show` | `{style}` |
| `style clear` | `{had_style}` |
| `threads export` | `{threads, total, output_path, date_range}` |
| `models list` | `{models}` |
| `skill show` | `{skill_md}` |
| `doctor security` | `{storage_backend, token_path, token_permissions, cache_path, cache_permissions, cookies_enabled}` |

## Parsing JSON in Scripts

### Using jq (shell)

```bash
# Extract the answer
pxcli query --json "Your question" | jq -r '.result.answer'

# Get reference URLs
pxcli query --json "Your question" | jq -r '.result.references[].url'

# Count references
pxcli query --json "Your question" | jq '.result.references | length'

# Get metadata
pxcli query --json "Your question" | jq '.meta.duration_ms'

# Get suggested next actions
pxcli query --json "Your question" | jq -r '.next_actions[].command'
```

### Using Python

```python
import json
import subprocess
import sys

result = subprocess.run(
    ["pxcli", "query", "--json", "Your question"],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print(f"pxcli exited with code {result.returncode}", file=sys.stderr)
    sys.exit(result.returncode)

envelope = json.loads(result.stdout)

if not envelope["ok"]:
    print(f"Error: {envelope['error']['message']}", file=sys.stderr)
    print(f"Fix: {envelope['fix']}", file=sys.stderr)
    sys.exit(1)

answer = envelope["result"]["answer"]
references = envelope["result"]["references"]

print(f"Answer: {answer}")
for ref in references:
    print(f"  [{ref['index']}] {ref['title']}: {ref['url']}")

# Follow suggested next actions
for action in envelope.get("next_actions", []):
    print(f"Suggested: {action['command']} — {action['description']}")
```

## NDJSON Streaming

Combine `--json` and `--stream` to receive newline-delimited JSON events:

```bash
pxcli query --json --stream "Your question"
```

Each line is a separate JSON object:

```
{"type": "start", "command": "pxcli query --json --stream \"Your question\"", "ts": "2025-01-01T00:00:00Z"}
{"type": "chunk", "text": "Python is ", "ts": "2025-01-01T00:00:01Z"}
{"type": "chunk", "text": "a programming language...", "ts": "2025-01-01T00:00:02Z"}
{"type": "result", "ok": true, "command": "...", "result": {...}, "meta": {...}, "next_actions": [...], "ts": "2025-01-01T00:00:03Z"}
```

### Processing NDJSON in Python

```python
import json
import subprocess

proc = subprocess.Popen(
    ["pxcli", "query", "--json", "--stream", "Your question"],
    stdout=subprocess.PIPE,
    text=True,
)

for line in proc.stdout:
    event = json.loads(line)
    if event["type"] == "chunk":
        print(event["text"], end="", flush=True)
    elif event["type"] == "result":
        references = event["result"]["references"]
        print(f"\n\n{len(references)} references found.")

proc.wait()
```

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General failure |
| 2 | Usage error |
| 3 | Not found |
| 4 | Authentication required |
| 5 | Conflict |
| 6 | Transient error (retry may help) |
| 7 | Validation error |
| 130 | Interrupted (Ctrl+C) |

Check exit codes in shell scripts:

```bash
pxcli query --json "Your question"
rc=$?
case $rc in
  0) echo "Success" ;;
  4) echo "Run: pxcli auth login" ;;
  6) echo "Transient error — retrying..." && sleep 2 && pxcli query --json "Your question" ;;
  *) echo "Failed with exit code $rc" ;;
esac
```

## next_actions Usage

The `next_actions` array in every envelope suggests follow-up commands. Agents should use this to chain operations:

```python
envelope = json.loads(result.stdout)
for action in envelope.get("next_actions", []):
    # Optionally execute suggested follow-ups
    subprocess.run(action["command"].split(), capture_output=True, text=True)
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `NO_COLOR` | Disable coloured output (any non-empty value) |
| `XDG_CONFIG_HOME` | Override default config directory (default: `~/.config`) |
| `PERPLEXITY_BASE_URL` | Override the Perplexity.ai base URL |
| `PXCLI_SESSION_LOG` | Path to session log file |

## Style Prompts

Apply a style prompt to all queries:

```bash
# Set a style
pxcli style set "be concise and technical"

# View current style
pxcli style show

# Remove style
pxcli style clear
```

## Debug and Diagnostics

```bash
# Enable debug logging
pxcli --debug query "Your question"

# Verbose logging
pxcli --verbose query "Your question"

# Security diagnostics
pxcli doctor security
```

## Security Considerations

- Token is encrypted at rest using Fernet symmetric encryption
- Encryption key derived from system identifiers (not portable between machines)
- Token stored in `~/.config/pxcli/token.json` with restricted permissions (0600)
- No credentials displayed in logs
- Token validated on each request with expiration detection
- Run `pxcli doctor security` to verify storage permissions and configuration

## Limitations

- Requires initial authentication setup with Chrome DevTools Protocol
- Rate limited by Perplexity.ai (reasonable limits for typical usage)
- Token bound to your machine (cannot be transferred)
- Requires active internet connection

## Quick Start

1. Authenticate: `pxcli auth login`
2. Check status: `pxcli auth status`
3. Query: `pxcli query "Your question"`
4. JSON output: `pxcli query --json "Your question"`
5. Show this skill: `pxcli skill show`
