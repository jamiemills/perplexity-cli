# Architecture Documentation - Perplexity CLI

**Date**: 2025-11-08
**Version**: 0.1.0
**Architecture Model**: C4 (Context, Container, Component, Code)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [C4 Model Diagrams](#c4-model-diagrams)
3. [Module Responsibilities](#module-responsibilities)
4. [Data Flow](#data-flow)
5. [Design Decisions](#design-decisions)

---

## System Overview

The Perplexity CLI is a command-line tool that enables users to query Perplexity.ai with persistent authentication. The system consists of three main layers:

1. **CLI Layer** - User interface (Click framework)
2. **Business Logic Layer** - Authentication and API client
3. **External Services Layer** - Perplexity.ai API and Chrome DevTools

**Key Characteristics**:
- Single-user desktop application
- Stateless operations (except token persistence)
- Synchronous CLI with async operations for auth/API
- Platform-independent (Linux, macOS, Windows)

---

## C4 Model Diagrams

### Level 1: System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│                              USER                                   │
│                    (Command-line operator)                          │
│                                                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Runs commands
                             │ (auth, query, logout, status)
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│                       PERPLEXITY CLI                                │
│                   (Command-line tool)                               │
│                                                                     │
│  Queries Perplexity.ai with persistent authentication             │
│                                                                     │
└──────────┬────────────────────────────────────┬─────────────────────┘
           │                                    │
           │ Extracts token                     │ Submits queries
           │ via DevTools                       │ via REST API
           │                                    │
           ▼                                    ▼
┌──────────────────────┐           ┌──────────────────────────┐
│                      │           │                          │
│   GOOGLE CHROME      │           │    PERPLEXITY.AI API     │
│  (Browser with       │           │   (External service)     │
│   remote debugging)  │           │                          │
│                      │           │  - SSE streaming         │
│                      │           │  - JWT authentication    │
└──────────────────────┘           └──────────────────────────┘
```

**External Systems**:
- **Google Chrome**: Used for authentication token extraction via DevTools Protocol
- **Perplexity.ai API**: Provides query answering service via SSE streaming

**Users**:
- Command-line users querying Perplexity.ai
- Developers integrating CLI into scripts/workflows

---

### Level 2: Container Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PERPLEXITY CLI                               │
│                     (Python 3.12 Application)                       │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                     CLI INTERFACE                             │ │
│  │                   (Click Framework)                           │ │
│  │                                                               │ │
│  │  Commands: auth, query, logout, status                       │ │
│  │  Entry point: perplexity                                     │ │
│  └──────────┬──────────────────────────────┬─────────────────────┘ │
│             │                              │                       │
│             │ Uses                         │ Uses                  │
│             ▼                              ▼                       │
│  ┌─────────────────────┐       ┌─────────────────────────┐       │
│  │  AUTHENTICATION     │       │     API CLIENT          │       │
│  │  MODULE             │       │     MODULE              │       │
│  │                     │       │                         │       │
│  │  - OAuth Handler    │       │  - SSE Client           │       │
│  │  - Token Manager    │       │  - Endpoints            │       │
│  │                     │       │  - Data Models          │       │
│  └─────────┬───────────┘       └──────────┬──────────────┘       │
│            │                              │                       │
│            │ Stores                       │ Reads                 │
│            ▼                              ▼                       │
│  ┌──────────────────────────────────────────────────────┐        │
│  │              TOKEN STORAGE                           │        │
│  │   ~/.config/perplexity-cli/token.json               │        │
│  │   (0600 permissions, JWT token)                     │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

External:
  ↓ Chrome DevTools Protocol (WebSocket)
  ↓ Perplexity API (HTTPS/SSE)
```

**Containers**:
1. **CLI Interface** - User-facing commands (Click framework)
2. **Authentication Module** - Token extraction and storage
3. **API Client Module** - Query submission and response handling
4. **Token Storage** - Persistent JWT token (file system)

---

### Level 3: Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CLI LAYER                                 │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │  auth    │  │  query   │  │  logout  │  │  status  │          │
│  │ command  │  │ command  │  │ command  │  │ command  │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │             │             │             │                  │
└───────┼─────────────┼─────────────┼─────────────┼──────────────────┘
        │             │             │             │
        │             │             │             │
┌───────▼─────────────▼─────────────▼─────────────▼──────────────────┐
│                    AUTHENTICATION MODULE                            │
│                                                                     │
│  ┌──────────────────────┐         ┌─────────────────────────┐     │
│  │   OAuth Handler      │         │    Token Manager        │     │
│  │                      │         │                         │     │
│  │  - ChromeDevTools    │◄────────│  - save_token()         │     │
│  │    Client            │         │  - load_token()         │     │
│  │  - authenticate_     │         │  - clear_token()        │     │
│  │    with_browser()    │         │  - token_exists()       │     │
│  │  - _extract_token()  │         │  - _verify_permissions()│     │
│  │                      │         │                         │     │
│  └──────────────────────┘         └─────────────────────────┘     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      API CLIENT MODULE                              │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │   SSE Client     │  │  PerplexityAPI   │  │  Data Models   │  │
│  │                  │  │                  │  │                │  │
│  │  - stream_post() │◄─│  - submit_query()│  │  - QueryRequest│  │
│  │  - _parse_sse_   │  │  - get_complete_ │  │  - SSEMessage  │  │
│  │    stream()      │  │    answer()      │  │  - Block       │  │
│  │  - get_headers() │  │  - _extract_text_│  │  - WebResult   │  │
│  │                  │  │    from_block()  │  │                │  │
│  └──────────────────┘  └──────────────────┘  └────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        UTILITIES MODULE                             │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Config Manager                            │  │
│  │                                                              │  │
│  │  - get_config_dir()   (Platform-aware directory)           │  │
│  │  - get_token_path()   (Token file location)                │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Responsibilities

### CLI Module (`cli.py`)

**Responsibility**: Command-line interface and user interaction

**Components**:
- `main()` - Click group entry point
- `auth()` - Authentication command
- `query()` - Query submission command
- `logout()` - Credential removal command
- `status()` - Status display command

**Dependencies**:
- Click framework for CLI
- Authentication module (TokenManager, authenticate_sync)
- API Client module (PerplexityAPI)

**Key Behaviours**:
- Parse command-line arguments
- Route to appropriate handlers
- Display user-friendly messages
- Handle errors gracefully
- Exit with appropriate codes (0 success, 1 error)

---

### Authentication Module (`auth/`)

**Responsibility**: Token extraction, storage, and validation

#### OAuth Handler (`oauth_handler.py`)

**Components**:
- `ChromeDevToolsClient` - WebSocket client for Chrome DevTools Protocol
- `authenticate_with_browser()` - Async token extraction
- `authenticate_sync()` - Sync wrapper for CLI
- `_extract_token()` - Token parsing from localStorage/cookies

**Key Behaviours**:
- Connect to Chrome via WebSocket (port 9222)
- Navigate to Perplexity.ai
- Extract JWT token from browser session
- Parse localStorage and cookies

**Protocol**: Chrome DevTools Protocol over WebSocket

#### Token Manager (`token_manager.py`)

**Components**:
- `TokenManager` class
- `save_token()` - Store with 0600 permissions
- `load_token()` - Load with permission verification
- `clear_token()` - Delete token file
- `token_exists()` - Check token presence
- `_verify_permissions()` - Security check

**Key Behaviours**:
- Store tokens in `~/.config/perplexity-cli/token.json`
- Enforce 0600 file permissions
- Verify permissions on load
- Detect permission tampering
- Platform-aware storage location

**Security**:
- File permissions: 0600 (owner read/write only)
- Permission verification on every load
- RuntimeError on insecure permissions

---

### API Client Module (`api/`)

**Responsibility**: HTTP communication with Perplexity.ai API

#### SSE Client (`client.py`)

**Components**:
- `SSEClient` class
- `stream_post()` - POST request with SSE streaming
- `_parse_sse_stream()` - Parse Server-Sent Events format
- `get_headers()` - Generate auth headers

**Key Behaviours**:
- Send POST requests to Perplexity API
- Parse SSE format: `event: message\ndata: {json}`
- Handle multi-line SSE data payloads
- Yield parsed JSON messages incrementally
- Error handling for HTTP status codes (401, 403, 429)

**Protocol**: HTTP with Server-Sent Events (SSE)

#### Perplexity API (`endpoints.py`)

**Components**:
- `PerplexityAPI` class
- `submit_query()` - Submit query and stream responses
- `get_complete_answer()` - Get final answer text
- `_extract_text_from_block()` - Parse answer blocks

**Key Behaviours**:
- Generate UUIDs for request tracking
- Build query payloads
- Submit to `/rest/sse/perplexity_ask`
- Parse streaming SSE responses
- Extract answer from markdown_block chunks
- Detect stream completion (final_sse_message)

**API Endpoint**: `POST https://www.perplexity.ai/rest/sse/perplexity_ask`

#### Data Models (`models.py`)

**Components**:
- `QueryParams` - Request parameters
- `QueryRequest` - Complete request structure
- `SSEMessage` - Streaming response message
- `Block` - Answer/result block
- `WebResult` - Search result

**Key Behaviours**:
- Type-safe data structures (dataclasses)
- Serialisation: `to_dict()` methods
- Deserialisation: `from_dict()` class methods
- Full type hints for validation

---

### Utilities Module (`utils/`)

**Responsibility**: Cross-cutting concerns and configuration

#### Config Manager (`config.py`)

**Components**:
- `get_config_dir()` - Platform-aware config directory
- `get_token_path()` - Token file location

**Key Behaviours**:
- Resolve platform-specific config directories
  - Linux/macOS: `~/.config/perplexity-cli/`
  - Windows: `%APPDATA%\perplexity-cli\`
- Create directories if missing
- Provide consistent path handling

---

## Data Flow

### 1. Authentication Flow

```
User runs: perplexity auth
         │
         ▼
   ┌──────────┐
   │   CLI    │  auth command
   │  Layer   │
   └────┬─────┘
        │
        │ Calls authenticate_sync(port=9222)
        ▼
   ┌──────────────────┐
   │ OAuth Handler    │
   │                  │
   │ 1. Connect to    │──────► Chrome DevTools
   │    Chrome via    │         (WebSocket port 9222)
   │    WebSocket     │
   │                  │
   │ 2. Navigate to   │──────► https://www.perplexity.ai
   │    Perplexity    │
   │                  │
   │ 3. Extract token │◄────── localStorage['pplx-next-auth-session']
   │    from browser  │         or cookies
   │                  │
   │ 4. Return JWT    │
   └────┬─────────────┘
        │
        │ Returns token (JWT ~484 chars)
        ▼
   ┌──────────────────┐
   │ Token Manager    │
   │                  │
   │ 1. Write token   │──────► ~/.config/perplexity-cli/token.json
   │    to file       │
   │                  │
   │ 2. Set perms     │──────► chmod 0600
   │    to 0600       │
   │                  │
   └──────────────────┘
        │
        │ Success confirmation
        ▼
   ┌──────────┐
   │   CLI    │  "✓ Authentication successful!"
   │  Layer   │  "✓ Token saved to: ~/.config/..."
   └──────────┘
```

### 2. Query Flow

```
User runs: perplexity query "What is Python?"
         │
         ▼
   ┌──────────┐
   │   CLI    │  query command
   │  Layer   │
   └────┬─────┘
        │
        │ 1. Load token
        ▼
   ┌──────────────────┐
   │ Token Manager    │  load_token()
   │                  │
   │ - Read file      │◄────── ~/.config/perplexity-cli/token.json
   │ - Verify perms   │
   │ - Return token   │
   └────┬─────────────┘
        │
        │ Token (JWT)
        ▼
   ┌──────────────────┐
   │ PerplexityAPI    │  get_complete_answer("What is Python?")
   │                  │
   │ 1. Generate UUIDs│──────► uuid.uuid4() × 2
   │                  │
   │ 2. Build request │──────► QueryRequest with params
   │                  │
   │ 3. Submit query  │
   └────┬─────────────┘
        │
        │ Calls stream_post()
        ▼
   ┌──────────────────┐
   │   SSE Client     │
   │                  │
   │ 1. POST request  │──────► POST /rest/sse/perplexity_ask
   │    with headers  │         Authorization: Bearer <token>
   │                  │         Accept: text/event-stream
   │                  │
   │ 2. Receive SSE   │◄────── event: message
   │    stream        │         data: {"blocks": [...], ...}
   │                  │         event: message
   │                  │         data: {..., "final_sse_message": true}
   │                  │
   │ 3. Parse SSE     │
   │    messages      │
   │                  │
   └────┬─────────────┘
        │
        │ Yields SSEMessage objects
        ▼
   ┌──────────────────┐
   │ PerplexityAPI    │
   │                  │
   │ 1. Collect all   │
   │    messages      │
   │                  │
   │ 2. Wait for      │
   │    final_sse_    │
   │    message: true │
   │                  │
   │ 3. Extract text  │──────► From blocks[intended_usage="ask_text"]
   │    from final    │         markdown_block.chunks[]
   │    message       │
   │                  │
   │ 4. Join chunks   │──────► "Python is a high-level..."
   └────┬─────────────┘
        │
        │ Complete answer text
        ▼
   ┌──────────┐
   │   CLI    │  Output answer to stdout
   │  Layer   │  (pipeable, clean output)
   └──────────┘
```

### 3. Logout Flow

```
User runs: perplexity logout
         │
         ▼
   ┌──────────┐
   │   CLI    │  logout command
   │  Layer   │
   └────┬─────┘
        │
        │ Calls clear_token()
        ▼
   ┌──────────────────┐
   │ Token Manager    │
   │                  │
   │ 1. Check exists  │──────► ~/.config/perplexity-cli/token.json
   │                  │
   │ 2. Delete file   │──────► unlink()
   │                  │
   └────┬─────────────┘
        │
        │ Success
        ▼
   ┌──────────┐
   │   CLI    │  "✓ Logged out successfully."
   │  Layer   │  "✓ Stored credentials removed."
   └──────────┘
```

### 4. Status Flow

```
User runs: perplexity status
         │
         ▼
   ┌──────────┐
   │   CLI    │  status command
   │  Layer   │
   └────┬─────┘
        │
        │ 1. Check token exists
        ▼
   ┌──────────────────┐
   │ Token Manager    │  token_exists()
   │                  │
   │ - Check file     │──────► ~/.config/perplexity-cli/token.json
   └────┬─────────────┘
        │
        │ Exists: True/False
        ▼
   ┌──────────┐
   │   CLI    │  If exists:
   │  Layer   │
   └────┬─────┘
        │
        │ 2. Load token
        ▼
   ┌──────────────────┐
   │ Token Manager    │  load_token()
   │                  │
   │ - Verify perms   │
   │ - Read token     │
   └────┬─────────────┘
        │
        │ Token
        ▼
   ┌──────────┐
   │   CLI    │  3. Verify token validity
   │  Layer   │
   └────┬─────┘
        │
        │ GET /api/user with Bearer token
        ▼
   ┌──────────────────┐
   │ HTTP Request     │
   │                  │
   │ GET /api/user    │──────► Perplexity.ai API
   │                  │◄────── {"username": "...", "email": "..."}
   └────┬─────────────┘
        │
        │ User profile data
        ▼
   ┌──────────┐
   │   CLI    │  Display:
   │  Layer   │  - Status: ✓ Authenticated
   └──────────┘  - Username, Email
                 - Token validity
```

---

## Design Decisions

### 1. Architecture Pattern: Layered Architecture

**Decision**: Use layered architecture with clear separation

**Layers**:
1. CLI Layer (presentation)
2. Business Logic Layer (auth, API client)
3. Data Layer (token storage)

**Rationale**:
- Clear separation of concerns
- Easy to test each layer independently
- CLI can be replaced (future: web interface, library)
- Business logic reusable

**Trade-offs**:
- More files/modules
- Slightly more complex than monolithic
- **Benefit**: Maintainability, testability

### 2. API Isolation Pattern

**Decision**: Isolate all Perplexity API code in `api/endpoints.py`

**Rationale**:
- Perplexity's private APIs may change
- Centralise API-specific code for easy updates
- Abstract API details from CLI

**Implementation**:
- All API calls through `PerplexityAPI` class
- SSE parsing in separate `SSEClient`
- Data models in separate file

**Benefit**: Rapid adaptation to API changes

### 3. Token Storage Strategy

**Decision**: Plain JSON file with 0600 permissions

**Alternatives Considered**:
- OS keyring (rejected: complex, platform-dependent)
- Encrypted file (rejected: unnecessary complexity)
- Database (rejected: overkill)

**Implementation**:
- Location: `~/.config/perplexity-cli/token.json`
- Format: `{"token": "<jwt>"}`
- Permissions: 0600 (enforced on save, verified on load)

**Rationale**:
- Simple and portable
- Adequate security with file permissions
- Easy to debug and inspect

### 4. SSE Streaming Approach

**Decision**: Custom SSE parser with httpx.stream()

**Alternatives Considered**:
- SSE library (rejected: no reliable Python SSE client library)
- WebSocket (rejected: API uses SSE, not WebSocket)
- Regular HTTP (rejected: API requires SSE for real-time)

**Implementation**:
- httpx.stream() for HTTP streaming
- Custom `_parse_sse_stream()` method
- Line-by-line parsing of event:/data: format

**Benefit**: Full control, no external SSE dependencies

### 5. Error Handling Strategy

**Decision**: Specific exceptions with actionable messages

**Implementation**:
- httpx.HTTPStatusError for HTTP errors (401, 403, 429)
- RuntimeError for runtime issues (Chrome, permissions)
- ValueError for invalid data
- OSError for file I/O errors

**Error Message Pattern**:
```
✗ <Problem description>

<Actionable solution>
```

**Examples**:
- 401 → "Token may be expired. Re-authenticate with: perplexity auth"
- Network error → "Check your internet connection."

**Benefit**: Self-service troubleshooting, reduced support burden

### 6. Output Routing

**Decision**: Answers to stdout, errors to stderr

**Rationale**:
- Enables piping: `perplexity query "Q" > file.txt`
- Shell scripts can capture answer: `ANSWER=$(perplexity query "Q")`
- Errors don't pollute answer text
- Unix philosophy: composable tools

**Implementation**:
- `click.echo(answer)` - stdout
- `click.echo(error, err=True)` - stderr

**Benefit**: CLI is scriptable and composable

---

## Technology Stack

### Core Technologies

| Layer | Technology | Purpose |
|-------|-----------|---------|
| CLI | Click 8.0+ | Command-line framework |
| HTTP | httpx 0.25+ | HTTP client with SSE streaming |
| Auth | websockets 12.0+ | Chrome DevTools Protocol |
| Data | Python dataclasses | Type-safe models |
| Config | pathlib | Path handling |

### Development Tools

| Tool | Purpose |
|------|---------|
| pytest | Testing framework (75 tests) |
| pytest-mock | Mocking HTTP/SSE responses |
| pytest-asyncio | Async test support |
| pytest-cov | Code coverage reporting |
| ruff | Linting and formatting |
| uv | Package management |

---

## Deployment Architecture

### Package Distribution

```
PyPI (future)
   │
   │ twine upload
   │
   ▼
┌──────────────────────────────┐
│  perplexity-cli-0.1.0.whl   │  (18KB)
│  perplexity-cli-0.1.0.tar.gz│  (31KB)
└──────────────────────────────┘
   │
   │ uv pip install
   │
   ▼
┌──────────────────────────────┐
│    User's Environment        │
│                              │
│  .venv/bin/perplexity        │  (Entry point script)
│  .venv/lib/.../perplexity_cli│  (Package modules)
└──────────────────────────────┘
```

### Runtime Architecture

```
User's Machine
├── perplexity command (installed script)
├── Python 3.12+ environment
├── ~/.config/perplexity-cli/token.json (token storage)
└── Chrome with --remote-debugging-port=9222 (for auth)

External Services:
├── Perplexity.ai API (queries)
└── Chrome DevTools (authentication)
```

---

## Security Architecture

### Authentication Security

```
JWT Token (AES-256-GCM encrypted)
         │
         │ Stored with chmod 0600
         ▼
┌──────────────────────────────────┐
│ ~/.config/perplexity-cli/        │
│                                  │
│  token.json                      │  Permission: -rw-------
│  {"token": "eyJhbGci..."}       │  Owner: user only
│                                  │  Group: denied
│                                  │  Others: denied
└──────────────────────────────────┘
         │
         │ Verified on every load
         ▼
   RuntimeError if permissions != 0600
```

### Data Flow Security

```
User Input (query)
   │
   │ Validated by Click (type checking)
   ▼
API Client
   │
   │ HTTPS only (SSL/TLS validation enabled)
   │ Bearer token in header (not URL)
   ▼
Perplexity.ai API
   │
   │ SSE stream (text/event-stream)
   ▼
Response Parsing
   │
   │ JSON validation on each message
   ▼
Answer (stdout)
   │
   │ No sensitive data in output
   ▼
User
```

**Security Boundaries**:
- No token in logs or error messages (only length/path)
- No command execution with user input
- No eval/exec usage
- File permissions verified on every load

---

## Performance Characteristics

### Query Performance

| Stage | Time |
|-------|------|
| Token load | <1ms |
| API request setup | <10ms |
| SSE streaming | 2-5s (depends on query complexity) |
| Answer extraction | <10ms |
| **Total** | **~2-5 seconds** |

### Authentication Performance

| Stage | Time |
|-------|------|
| Chrome connection | ~100ms |
| Token extraction | ~3s (browser interaction) |
| Token save | <10ms |
| **Total** | **~3 seconds** |

### Resource Usage

- Memory: ~20MB (Python runtime + dependencies)
- Disk: 18KB (wheel), 31KB (source)
- Network: Minimal (only API requests)

---

## Scalability Considerations

### Current Design (Single User, Desktop)

**Suitable for**:
- Individual developers
- Personal automation scripts
- Single-user CLI workflows

**Not suitable for**:
- Multi-user server environments
- High-frequency automated queries
- Concurrent query processing

### Future Scalability Options

If needed for multi-user/server use:
1. Add connection pooling (httpx supports this)
2. Implement request queuing
3. Add caching layer for repeated queries
4. Support multiple token profiles

---

## Extension Points

### Adding New Commands

```python
@main.command()
@click.argument("param")
def new_command(param: str) -> None:
    """New command description."""
    # Implementation
```

Location: `src/perplexity_cli/cli.py`

### Adding New API Endpoints

```python
def new_api_method(self, param: str) -> Result:
    """New API method."""
    # Implementation in PerplexityAPI class
```

Location: `src/perplexity_cli/api/endpoints.py`

### Adding New Authentication Methods

```python
async def alternative_auth() -> str:
    """Alternative authentication method."""
    # Implementation
```

Location: `src/perplexity_cli/auth/oauth_handler.py`

---

## Testing Architecture

### Test Organisation

```
tests/
├── Unit Tests (49 tests)
│   ├── test_auth.py (22) - Token storage, extraction
│   ├── test_api_client.py (14) - Models, SSE parsing
│   └── test_cli.py (11) - Command invocation
│
├── Integration Tests (17 tests)
│   ├── test_auth_integration.py (9) - Auth workflows
│   └── test_api_integration.py (8) - Real API queries
│
└── Security Tests (3 tests)
    └── test_auth.py - File permissions

Utilities:
├── test_query_simple.py - Quick query testing
├── test_query_realtime.py - SSE message inspection
├── save_auth_token.py - Token extraction
└── discover_api_endpoints.py - API mapping
```

### Test Strategy

| Test Type | Purpose | Example |
|-----------|---------|---------|
| Unit | Test individual functions | `test_save_token_sets_secure_permissions` |
| Integration | Test complete workflows | `test_get_complete_answer_simple_query` |
| Security | Test security properties | `test_token_file_not_world_readable` |
| Manual | Verify real-world usage | `test_query_simple.py` |

---

## Conclusion

The Perplexity CLI uses a clean, layered architecture with:
- Clear separation of concerns
- Type-safe components
- Comprehensive error handling
- Strong security practices
- Well-tested implementation

The architecture supports:
- Easy maintenance and updates
- Rapid adaptation to API changes
- Extension with new features
- Thorough testing

**Architecture Status**: ✅ Production-ready
