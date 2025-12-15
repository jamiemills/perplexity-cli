---
name: perplexity-cli-question-answering
description: Query Perplexity.ai directly from the terminal to find answers to research questions, current events, and detailed explanations. Returns structured JSON output for programmatic parsing. Use when you need current information, comprehensive answers with source references, or want to avoid making separate web search requests.
---

# Perplexity CLI for Question Answering

## What Is perplexity-cli?

perplexity-cli is a command-line interface for querying Perplexity.ai. It allows you to ask questions and receive comprehensive answers with source citations, directly from your terminal. The tool supports multiple output formats including structured JSON, making it ideal for programmatic use.

## When to Use This Skill

Use perplexity-cli when you need to:

- **Find current information**: Ask about recent events, news, or developments
- **Get detailed explanations**: Request comprehensive answers with source references
- **Research topics**: Explore subjects with verified sources cited in the response
- **Parse structured data**: Use JSON output format to integrate answers into workflows
- **Avoid multiple tools**: Replace separate web search requests with a single command

Compare to other approaches:
- **Web search tools**: Good for finding specific URLs, but require manual reading and verification
- **Web fetch**: Good for reading specific page content, but requires knowing the URL first
- **perplexity-cli**: Good for getting synthesised answers with automatic source discovery and citations

## Setup and Authentication

### One-Time Authentication

perplexity-cli requires a one-time authentication step:

```bash
# Install Chrome for Testing (keeps it separate from your main browser)
npx @puppeteer/browsers install chrome@stable

# Create a shell alias in your shell config (~/.bashrc, ~/.zshrc, etc.)
alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'

# Terminal 1: Start Chrome
chromefortesting

# Terminal 2: Authenticate
perplexity-cli auth
```

Once authenticated, you won't need to authenticate again unless you run `perplexity-cli logout`.

### Checking Authentication Status

```bash
perplexity-cli status
```

This verifies your token is valid and working.

## Basic Usage

### Simple Query

```bash
perplexity-cli query "What are the latest developments in quantum computing?"
```

This returns a formatted answer with source references in the terminal.

### Query with Options

```bash
# Get plain text output (good for scripts)
perplexity-cli query --format plain "What is Python?"

# Remove citation numbers and references section
perplexity-cli query --strip-references "Explain machine learning"

# Combine options
perplexity-cli query --format plain --strip-references "What is 2+2?"
```

## JSON Output Format

For programmatic use, request JSON output:

```bash
perplexity-cli query --format json "What is the capital of France?"
```

### JSON Structure

```json
{
  "format_version": "1.0",
  "answer": "The capital of France is Paris...",
  "references": [
    {
      "index": 1,
      "title": "Paris - Wikipedia",
      "url": "https://en.wikipedia.org/wiki/Paris",
      "snippet": "Paris is the capital and largest city of France..."
    }
  ]
}
```

### Parsing JSON in Scripts

**Using jq (shell):**

```bash
# Extract just the answer
perplexity-cli query --format json "Your question" | jq -r '.answer'

# Extract answer with proper newlines
perplexity-cli query --format json "Your question" | jq -r '.answer'

# Get reference URLs
perplexity-cli query --format json "Your question" | jq -r '.references[] | .url'

# Count references
perplexity-cli query --format json "Your question" | jq '.references | length'
```

**Using Python:**

```python
import json
import subprocess

result = subprocess.run(
    ["perplexity-cli", "query", "--format", "json", "Your question"],
    capture_output=True,
    text=True
)

data = json.loads(result.stdout)
answer = data["answer"]
references = data["references"]

print(f"Answer: {answer}")
for ref in references:
    print(f"  [{ref['index']}] {ref['title']}: {ref['url']}")
```

## Practical Patterns

### Pattern 1: Get Answer Without References

When you just need the answer without citation numbers:

```bash
perplexity-cli query --format plain --strip-references "Your question"
```

### Pattern 2: Research with Full Context

Get comprehensive answer with all sources:

```bash
perplexity-cli query --format json "Your question"
# Process JSON to show answer and references
```

### Pattern 3: Integrate into Workflows

Fetch answer as JSON and parse for further processing:

```bash
# Get latest information and process
answer=$(perplexity-cli query --format json "What are the latest AI developments?" | jq -r '.answer')

# Use in next step
echo "According to Perplexity: $answer"
```

### Pattern 4: Stream Response (Real-Time)

For interactive use, stream the response as it arrives:

```bash
perplexity-cli query --stream "Your question"
```

## Error Handling

### Common Errors

**"Not authenticated"**
- Run `perplexity-cli auth` to authenticate first
- Ensure Chrome DevTools authentication completed successfully

**"Token is invalid or expired"**
- Re-authenticate: `perplexity-cli auth`
- Token may have expired after extended disuse

**"Rate limit exceeded"**
- Wait before making more queries
- Perplexity.ai has rate limiting for heavy usage

**"Network error"**
- Check your internet connection
- Verify Perplexity.ai service is accessible

### Debug Information

For troubleshooting, enable debug output:

```bash
perplexity-cli --debug query "Your question"
```

This shows detailed logging including HTTP requests and responses.

## Advanced Usage

### Configure Custom Style Prompts

Apply a style prompt to all queries:

```bash
# Set a style
perplexity-cli configure "be concise and technical"

# View current style
perplexity-cli view-style

# Remove style
perplexity-cli clear-style
```

The style is appended to every query, allowing consistent response formatting.

### Custom Debug Port

If port 9222 is in use:

```bash
# Start Chrome on different port
chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app --args "--remote-debugging-port=9223" "about:blank"'

# Authenticate with custom port
perplexity-cli auth --port 9223
```

### Log Files

Logs are stored at `~/.config/perplexity-cli/perplexity-cli.log`

Enable verbose logging:

```bash
perplexity-cli --verbose query "Your question"
perplexity-cli --debug query "Your question"
```

## Complete Examples

### Example 1: Research Current Events

```bash
# Get latest news on a topic
perplexity-cli query "What are the latest updates on the James Webb Space Telescope?"
```

### Example 2: Technical Explanation

```bash
# Get detailed technical explanation
perplexity-cli query --format json "How does OAuth 2.0 authentication work?" | jq -r '.answer'
```

### Example 3: Multi-Step Research Workflow

```bash
# 1. Get initial answer as JSON
response=$(perplexity-cli query --format json "What are the main challenges in renewable energy?")

# 2. Extract answer
answer=$(echo "$response" | jq -r '.answer')

# 3. Extract reference URLs
urls=$(echo "$response" | jq -r '.references[].url')

# 4. Process results
echo "=== Answer ==="
echo "$answer"
echo ""
echo "=== References ==="
echo "$urls"
```

### Example 4: Batch Queries

```bash
# Process multiple questions
questions=("What is Python?" "What is JavaScript?" "What is Rust?")

for question in "${questions[@]}"; do
  echo "Q: $question"
  perplexity-cli query --format plain --strip-references "$question"
  echo ""
done
```

## Key Advantages

1. **Structured Output**: JSON format for easy programmatic parsing
2. **Source Citations**: Every answer includes verified source references
3. **Current Information**: Access to real-time data and recent events
4. **No API Keys**: Uses Perplexity.ai via your authenticated session
5. **Simple Integration**: Single command invocation, straightforward output
6. **Flexible Formats**: Plain text, Markdown, rich terminal, or JSON

## Security Considerations

- Token is encrypted at rest using Fernet symmetric encryption
- Encryption key derived from system identifiers (not portable between machines)
- Token stored in `~/.config/perplexity-cli/token.json` with restricted permissions (0600)
- No credentials displayed in logs
- Token validated on each request with expiration detection

## Limitations

- Requires initial authentication setup with Chrome DevTools Protocol
- Rate limited by Perplexity.ai (reasonable limits for typical usage)
- Token bound to your machine (cannot be transferred)
- Requires active internet connection

## Troubleshooting

**Display the Agent Skill definition:**

```bash
perplexity-cli show-skill
```

This outputs the full SKILL.md content, useful for sharing with other agents or tools.

## Next Steps

1. Install and authenticate: `perplexity-cli auth`
2. Check status: `perplexity-cli status`
3. Try a simple query: `perplexity-cli query "Your question"`
4. Explore JSON format for integration into your workflows

For full documentation, see the [perplexity-cli README](https://github.com/jamiemills/perplexity-cli#readme).
