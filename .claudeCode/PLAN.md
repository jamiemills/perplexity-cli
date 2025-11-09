# Perplexity CLI - Implementation Plan (Final with Goals, Requirements, and Decisions)

**Created**: 2025-11-08
**Last Updated**: 2025-11-08

## SECTION A: PROJECT GOALS AND REQUIREMENTS

### A.1 Primary Goal
Build a production-grade command-line interface (CLI) application that allows authenticated users to submit queries to Perplexity.ai and receive answers via the application's private APIs, with persistent authentication and minimal, clean output.

### A.2 Functional Requirements

#### A.2.1 Authentication Requirements
- Users must be able to authenticate using their Perplexity.ai Google-backed account
- Authentication flow must involve opening a browser to Perplexity.ai where the user logs in via Google OAuth/OIDC
- User should NOT be required to authenticate more than once - tokens must be stored persistently
- The CLI should detect when authentication is missing or expired and prompt for re-authentication
- Users should have a logout command to clear stored credentials

#### A.2.2 Query Execution Requirements
- CLI must support sending a single query per invocation (not interactive mode)
- Query syntax: `perplexity-cli query "What is machine learning?"`
- Output must contain ONLY the answer text from Perplexity, no website chrome or metadata
- Answer must be written to stdout for piping to other commands if needed
- Appropriate exit codes must be used for success/failure

#### A.2.3 API Integration Requirements
- Must use Perplexity.ai's private APIs (those used by the React frontend), not public APIs
- Code using private APIs must be isolated in a single abstraction layer (`endpoints.py`) to enable rapid adaptation if APIs change
- All API interactions must include proper authentication headers
- Error responses from the API must be handled gracefully with user-friendly messages

#### A.2.4 Token Management Requirements
- Tokens must be stored in plain text JSON format in `~/.config/perplexity-cli/token.json`
- Token storage must use restrictive file permissions (0600) so only the user can read the file
- No credentials or secrets should ever be embedded in the application code
- Token refresh should be implemented if Perplexity's API supports it

#### A.2.5 Packaging and Installation Requirements
- Application must be installable via `uv pip install .` (development) and `uv pip install perplexity-cli` (from PyPI)
- Installation must create a `perplexity` executable command available system-wide
- Must support Python 3.12 exclusively (no compatibility with earlier versions required)
- `pyproject.toml` must follow modern packaging standards (PEP 517/518)
- `uv.lock` file must be maintained for reproducible installs

#### A.2.6 Code Quality Requirements
- All code must pass `ruff` linting and formatting checks (no other linters)
- All code must be formatted according to ruff's formatting rules
- Target Python version must be set to 3.12 in ruff configuration
- All functions must have type hints
- All public functions must have docstrings
- Code must follow British English spelling and grammar

#### A.2.7 Security Requirements
- Comprehensive security review must be performed on all code before release
- No credentials, tokens, or sensitive data should appear in logs or error messages
- Input validation must be performed on all user-supplied data to prevent injection attacks
- HTTP client must validate SSL/TLS certificates
- File permissions on token storage must be enforced and verified
- Dependencies must be scanned for known vulnerabilities
- All authentication and token handling code must be audited for security issues

#### A.2.8 Dependency Management Requirements
- Package management MUST use `uv` exclusively - no pip
- All development and runtime dependencies must be declared in `pyproject.toml`
- `uv.lock` must be committed to version control
- No unnecessary dependencies - only include what is required

#### A.2.9 Documentation Requirements
- Comprehensive README with setup, installation, and usage examples
- `.claudeCode/CLAUDE.md` must be maintained as an operational log with all findings and decisions
- `.claudeCode/ARCHITECTURE.md` must document the system architecture using C4 model
- `.claudeCode/PLAN.md` must track progress with timestamps

#### A.2.10 Testing Requirements
- Unit tests for all core modules (auth, API client, CLI commands)
- Integration tests for complete workflows (auth flow, query submission)
- Security tests for token handling, input validation, and HTTP security
- Aim for >80% test coverage on critical paths
- All tests must pass before release

### A.3 Non-Functional Requirements

#### A.3.1 Maintainability
- Code architecture must enable rapid adaptation to future Perplexity API changes
- Private API interaction must be isolated to enable easy updates when APIs change
- Code must be self-documenting with clear module responsibilities
- Design must separate concerns: authentication, API interaction, CLI logic

#### A.3.2 Reliability
- Comprehensive error handling for network failures, invalid tokens, API errors
- User-friendly error messages that guide users on how to resolve issues
- Graceful handling of edge cases (expired tokens, missing config, invalid queries)

#### A.3.3 Security
- Tokens must never be transmitted over unencrypted connections
- No credential information in logs, error messages, or user output
- File permissions must prevent other users from accessing tokens
- SSL/TLS certificate validation must be enforced

#### A.3.4 Usability
- Simple, intuitive CLI commands
- Clear prompts and messages
- Minimal setup friction (auth once, use many times)

## SECTION B: ARCHITECTURE OVERVIEW

### B.1 Project Structure
```
perplexity-cli/
├── README.md
├── .claudeCode/
│   ├── CLAUDE.md (operational log)
│   ├── ARCHITECTURE.md (system architecture)
│   └── PLAN.md (plan tracking with dates and progress)
├── pyproject.toml
├── uv.lock
├── src/
│   ├── perplexity_cli/
│   │   ├── __init__.py
│   │   ├── cli.py (Click CLI entry point)
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── oauth_handler.py (Perplexity login flow with browser)
│   │   │   └── token_manager.py (token storage/retrieval in ~/.config/perplexity-cli/)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── client.py (HTTP client with authentication headers)
│   │   │   ├── endpoints.py (abstraction layer for private API endpoints)
│   │   │   └── models.py (request/response data structures)
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── config.py (configuration directory management)
├── tests/
│   ├── __init__.py
│   ├── test_auth.py
│   ├── test_api.py
│   └── test_cli.py
└── dist/ (generated package files)
```

### B.2 Key Design Principles
- **API Isolation**: All Perplexity private API calls confined to `src/perplexity_cli/api/endpoints.py` to enable easy adaptation to future API changes
- **Separation of Concerns**: Authentication, token management, API interaction, and CLI logic are separate modules
- **Configuration Management**: Tokens stored in platform-specific config directory (~/.config/perplexity-cli/ on Linux/macOS)
- **Minimal Output**: CLI returns only the answer text, no website chrome or metadata
- **Security First**: All code reviewed for security vulnerabilities; sensitive data handled securely
- **Python 3.12**: All code written and tested for Python 3.12 compatibility
- **uv Only**: All dependency and environment management via `uv`

## SECTION C: AUTHENTICATION IMPLEMENTATION

### C.1 Authentication Flow
1. User runs `perplexity-cli auth`
2. CLI opens browser to `https://www.perplexity.ai` (or appropriate Perplexity login page)
3. User sees Perplexity's login page with Google OAuth option
4. User clicks Google OAuth and authenticates with their Google account
5. Perplexity authenticates the user via Google and completes login
6. User is returned to Perplexity's main interface (authentication complete)
7. CLI captures the authentication token from the browser session/response
8. Token is extracted and stored in `~/.config/perplexity-cli/token.json`
9. CLI confirms successful authentication to user

### C.2 Token Capture Strategy
During Phase 1 research, determine the optimal token capture mechanism. Three approaches to evaluate:

- **Option A**: Browser automation (Selenium/Playwright)
  - Automate browser navigation to Perplexity login
  - Monitor network traffic for authentication response
  - Extract auth token from response headers or cookies
  - Store token locally

- **Option B**: Local callback server
  - CLI opens browser to Perplexity auth URL with localhost callback
  - Perplexity completes auth and redirects to localhost with token
  - CLI's local server captures token and stores it
  - (Requires Perplexity to support localhost callbacks)

- **Option C**: Manual token extraction
  - CLI opens browser to Perplexity
  - User logs in manually via Google
  - CLI provides instructions to copy auth token from browser DevTools
  - User pastes token into CLI prompt
  - (Most reliable but least automated)

The chosen approach will be documented in `.claudeCode/CLAUDE.md` during Phase 1.

### C.3 Token Management
- `TokenManager` class handles:
  - Reading token from storage (`~/.config/perplexity-cli/token.json`)
  - Checking token validity
  - Refreshing expired tokens (if Perplexity API supports it)
  - Clearing tokens (logout functionality)
  - Secure token storage (file permissions restricted to user only)
- Tokens stored as plain JSON in config directory with restrictive file permissions (0600)

### C.4 Authentication Modules
- `oauth_handler.py`: Manages Perplexity authentication flow
  - Opens browser to Perplexity login page
  - Captures auth token via chosen strategy
  - Validates token before storage
  - Handles authentication errors and user guidance
- `token_manager.py`: Handles persistent token storage and retrieval
  - Saves/loads tokens from config directory
  - Manages token lifecycle
  - Enforces secure file permissions

### C.5 API Authentication Headers
- Once token is obtained, all API requests include appropriate authentication headers
- Headers determined by inspecting Perplexity's private API (likely `Authorization: Bearer <token>` or similar)

## SECTION D: API CLIENT IMPLEMENTATION

### D.1 API Endpoint (DISCOVERED in Phase 1)

**Primary Query Endpoint**: `POST https://www.perplexity.ai/rest/sse/perplexity_ask`

**Key Characteristics**:
- Protocol: Server-Sent Events (SSE) streaming
- Authentication: Bearer JWT token
- Request Format: JSON with params object and query_str
- Response Format: text/event-stream with incremental JSON messages
- API Version: 2.18 (passed as query parameter)

**Request Structure**:
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
  "query_str": "<user query>"
}
```

**Response Structure**: SSE stream of JSON messages
- Format: `event: message\ndata: {json}\n\n`
- Multiple messages sent as answer is generated
- Final message: `final_sse_message: true`
- Answer in `blocks` array with `intended_usage` types

### D.2 API Abstraction Layer

**`client.py`: SSE streaming HTTP client**
- Uses httpx.stream() for Server-Sent Events support
- Implements SSE event-stream parser (handles "event:" and "data:" lines)
- Includes Bearer authentication headers in all requests
- Handles streaming response chunks
- Implements error handling and retry logic for stream interruptions
- Manages HTTP session lifecycle
- Input validation and sanitisation

**`endpoints.py`: Query endpoint wrapper**
- Maps to `/rest/sse/perplexity_ask` endpoint
- Generates UUIDs for request tracking (frontend_uuid, frontend_context_uuid)
- Builds request payload with params and query_str
- Streams SSE responses and yields parsed JSON messages
- Extracts answer text from blocks array
- Detects completion via final_sse_message flag
- Returns complete answer when streaming finishes

**`models.py`: Data structures for SSE requests/responses**
- QueryRequest: Request payload structure with params
- QueryResponse: SSE message structure with blocks
- Block: Answer block with intended_usage and content
- WebResult: Search result structure (name, snippet, url, timestamp)
- Type-safe models with full type hints
- SSE message deserialisation

### D.3 SSE Streaming Implementation

**SSE Format Handling**:
- Parse `event: message` lines
- Parse `data: {json}` lines
- Handle multi-line data payloads
- Detect stream completion
- Accumulate text from incremental updates

**Block Types to Handle**:
- `web_results`: Search results with sources
- `answer_tabs`: Answer mode tabs
- `pro_search_steps`: Search progress indicators
- `diff_block`: Incremental text patches
- Text blocks: Actual answer content

**Answer Extraction Strategy**:
- Collect all streaming messages until final_sse_message: true
- Extract text from blocks with answer content
- Optionally include web_results for sources
- Return complete answer text

### D.4 API Discovery (COMPLETED in Phase 1)
- ✅ Used Chrome DevTools Protocol to monitor network traffic
- ✅ Identified `/rest/sse/perplexity_ask` as primary query endpoint
- ✅ Documented request/response formats in API_DISCOVERY.md
- ✅ Tested with query: "What is the capital of France?"
- ✅ Verified SSE streaming response format
- ✅ Confirmed Bearer token authentication works

## SECTION E: CLI IMPLEMENTATION

### E.1 Click Application Structure
- `cli.py`: Main entry point with Click commands
  - `auth` command: Initiates authentication flow
  - `query` command: Sends query to Perplexity and returns answer
  - `logout` command: Clears stored token
  - `status` command: Shows current authentication status

### E.2 Command Behaviour
- `perplexity-cli query "What is machine learning?"`
- Checks for valid token; prompts auth if missing
- Sends query to Perplexity API
- Extracts answer text from response
- Outputs only answer to stdout
- Exits with appropriate status code

## SECTION F: PACKAGING & INSTALLATION

### F.1 Package Configuration
- `pyproject.toml`: Modern Python packaging with:
  - Python 3.12 requirement specified (`requires-python = ">=3.12"`)
  - Entry point configured for CLI executable (`perplexity`)
  - All dependencies declared
  - Build system configured with setuptools
- `uv.lock`: Lock file for reproducible installs with `uv`
- Package follows PEP 517/518 standards

### F.2 Installation Options
- Installable via `uv pip install -e .` for development
- Installable via `uv pip install perplexity-cli` from PyPI (future)
- Creates executable `perplexity-cli` command available system-wide after installation

### F.3 Build Process
- `uv` used for all environment management and dependency resolution
- Build artefacts (wheels, sdists) generated in `dist/` directory
- Version management via `__version__` in `src/perplexity_cli/__init__.py`

## SECTION G: PROGRESS TRACKING METHODOLOGY

### G.1 TodoWrite Tool Tracking
- Maintain a structured todo list using the `TodoWrite` tool that maps directly to the numbered plan items
- Track task states: `pending`, `in_progress`, `completed`
- Enforce exactly ONE task in `in_progress` at any time
- Update todo list immediately upon completing each numbered subtask
- Provide periodic visibility into current task and remaining work

### G.2 Plan Document Checkboxes
- Check off completed items in this plan document using `[x]` notation
- Save an updated version of the plan to `.claudeCode/PLAN.md` including:
  - Creation date
  - Last updated date
  - All checkbox states reflecting current progress
- Update timestamps whenever significant progress is made

### G.3 Progress Communication
- At completion of each phase, provide summary of work completed vs. remaining
- Flag any blockers or required plan adjustments immediately
- Update `.claudeCode/CLAUDE.md` with progress notes and findings
- Show user updated plan with progress at regular intervals

### G.4 Tracking Benefits
- Clear visibility into current work and project status
- Historical record of what was accomplished and when
- Ability to pause and resume work without losing context
- Quick identification of remaining work

## SECTION H: TESTING STRATEGY

### H.1 Unit Tests

- [ ] H.1.1 Auth Module Tests
  - [ ] H.1.1.1 Token storage and retrieval
  - [ ] H.1.1.2 File permission enforcement
  - [ ] H.1.1.3 Token validation logic
  - [ ] H.1.1.4 Token refresh scenarios
  - [ ] H.1.1.5 Invalid token handling

- [ ] H.1.2 API Client Tests
  - [ ] H.1.2.1 Request formatting with authentication headers
  - [ ] H.1.2.2 Response parsing and answer extraction
  - [ ] H.1.2.3 Error handling and retries
  - [ ] H.1.2.4 Input validation and sanitisation
  - [ ] H.1.2.5 HTTP session management

- [ ] H.1.3 Endpoint Tests
  - [ ] H.1.3.1 Query building and submission
  - [ ] H.1.3.2 Answer extraction from various response formats
  - [ ] H.1.3.3 Error response handling

- [ ] H.1.4 CLI Command Tests
  - [ ] H.1.4.1 Command argument parsing
  - [ ] H.1.4.2 Error state handling
  - [ ] H.1.4.3 Help text generation
  - [ ] H.1.4.4 Output formatting

### H.2 Integration Tests

- [ ] H.2.1 Authentication Flow
  - [ ] H.2.1.1 Full auth flow with mocked browser callback
  - [ ] H.2.1.2 Token persistence across invocations
  - [ ] H.2.1.3 Logout and re-authentication

- [ ] H.2.2 Query Submission
  - [ ] H.2.2.1 End-to-end query submission
  - [ ] H.2.2.2 Answer retrieval and extraction
  - [ ] H.2.2.3 Token refresh during query

- [ ] H.2.3 Error Handling
  - [ ] H.2.3.1 Network failure scenarios
  - [ ] H.2.3.2 Invalid token scenarios
  - [ ] H.2.3.3 API error responses
  - [ ] H.2.3.4 Missing configuration handling

### H.3 Security Tests

- [ ] H.3.1 Token Security
  - [ ] H.3.1.1 File permission enforcement tests
  - [ ] H.3.1.2 Token encryption/storage tests
  - [ ] H.3.1.3 Credential leakage prevention tests

- [ ] H.3.2 Input Validation
  - [ ] H.3.2.1 Injection attack prevention tests
  - [ ] H.3.2.2 Malformed input handling tests
  - [ ] H.3.2.3 CLI argument boundary tests

- [ ] H.3.3 HTTP Security
  - [ ] H.3.3.1 SSL/TLS validation tests
  - [ ] H.3.3.2 Secure default configuration tests
  - [ ] H.3.3.3 Certificate validation tests

- [ ] H.3.4 Sensitive Data Handling
  - [ ] H.3.4.1 Logging verification (no token leakage)
  - [ ] H.3.4.2 Error message verification (no credential exposure)
  - [ ] H.3.4.3 Exception handling verification

### H.4 Manual Testing Checklist

- [ ] H.4.1 First-time auth with Google via browser
- [ ] H.4.2 Token persists across CLI invocations
- [ ] H.4.3 Query submission with valid token
- [ ] H.4.4 Answer extraction and output formatting
- [ ] H.4.5 Query with expired token (triggers refresh if supported)
- [ ] H.4.6 Logout clears token
- [ ] H.4.7 Re-authentication after logout
- [ ] H.4.8 Network error handling
- [ ] H.4.9 Installation from built wheel
- [ ] H.4.10 `perplexity-cli` command available after installation
- [ ] H.4.11 All commands work post-installation

## SECTION I: DEPENDENCIES

### I.1 Required Runtime Packages (UPDATED based on Phase 1 findings)
- `click>=8.0` (CLI framework)
- `httpx>=0.25` (HTTP client with SSE streaming support)
- `websockets>=12.0` (Chrome DevTools Protocol communication for authentication)

**Note**: No additional browser automation library needed. Chrome DevTools Protocol via websockets is sufficient.

### I.2 Development Packages
- `pytest>=7.0` (testing framework)
- `pytest-mock>=3.0` (mocking HTTP calls and SSE streams)
- `pytest-asyncio>=1.2.0` (async test support)
- `pytest-cov>=7.0` (test coverage reporting)
- `ruff>=0.1` (linting and formatting)

### I.3 Environment
- **Python**: 3.12.11 (specified in `pyproject.toml` with `requires-python = ">=3.12"`)
- **Build system**: setuptools with PEP 517/518 compliance
- **Package manager**: `uv` (for all dependency and environment management)
- **Virtual environment**: Created with `uv venv --python=3.12`

### I.4 Standard Library Dependencies
- `uuid` (UUID generation for API request tracking)
- `json` (JSON serialisation/deserialisation)
- `os`, `stat` (file operations and permission management)
- `pathlib` (path handling)
- `urllib` (Chrome DevTools HTTP endpoint communication)
- `asyncio` (async operations for Chrome DevTools and SSE streaming)

## SECTION J: SECURITY CONSIDERATIONS

- [ ] J.1 Token storage with restricted file permissions (0600)
- [ ] J.2 No hardcoded secrets or credentials in codebase
- [ ] J.3 Input validation on all user-supplied data
- [ ] J.4 Secure HTTP client configuration (SSL/TLS certificate validation)
- [ ] J.5 No sensitive data in logs or error messages
- [ ] J.6 Dependency vulnerability scanning via `uv`
- [ ] J.7 Regular security audits of private API interaction code
- [ ] J.8 All authentication data stored locally with proper access controls

## SECTION K: IMPLEMENTATION DECISIONS AND RATIONALE

### K.1 Authentication & Token Storage

**Decision**: Use plain file storage for tokens (not encrypted file or OS keyring)
- **Rationale**: User explicitly requested this approach. Plain file storage is simple to implement and manage, while still supporting restrictive file permissions (0600) for security. More complex approaches (encrypted files, keyrings) add unnecessary complexity for this use case.
- **Trade-off**: Less secure than encrypted storage, but simpler and more portable across systems.

**Decision**: Automatic browser opening to Perplexity.ai for authentication
- **Rationale**: User explicitly requested this. It provides the best user experience by reducing friction - users see the familiar Perplexity login page and use their existing Google account directly.
- **Alternative considered**: Displaying a URL and waiting for manual entry, which is less convenient.

**Decision**: Token capture mechanism to be determined during Phase 1 research (Options A, B, or C)
- **Rationale**: The optimal approach depends on how Perplexity's authentication actually works. Three realistic options were identified, and Phase 1 research will determine which is most practical and reliable.
- **Trade-offs**:
  - Option A (browser automation) is most automated but adds dependency weight
  - Option B (callback server) is elegant but requires Perplexity cooperation
  - Option C (manual extraction) is least automated but most reliable

### K.2 API Design

**Decision**: Isolate all Perplexity private API interactions in `endpoints.py`
- **Rationale**: Perplexity's private APIs may change as they update their frontend. By isolating all API-specific code in one module, future changes can be adapted quickly without touching other parts of the codebase. This follows the principle of high cohesion and loose coupling.
- **Trade-off**: Slightly more abstraction overhead, but provides significant long-term maintainability benefits.

**Decision**: Use `httpx` library for HTTP client
- **Rationale**: `httpx` is a modern, well-documented, and stable library that supports both synchronous and asynchronous operations. It is a suitable choice for this CLI tool and provides flexibility for future enhancements.
- **Alternative considered**: `requests` (older, synchronous-only).

### K.3 CLI Design

**Decision**: Single query per invocation mode (not interactive mode)
- **Rationale**: User explicitly requested this. It aligns with Unix philosophy of simple, composable tools. Users can pipe output to other commands and integrate with shell scripts.
- **Alternative**: Interactive mode with persistent connection would be more convenient for multiple queries but adds complexity.

**Decision**: Output only the answer text to stdout
- **Rationale**: User explicitly requested this. Minimal output enables the CLI to be used in scripts and pipelines. Complex output (with metadata, formatting, etc.) can always be added later by the user.

### K.4 Code Quality & Linting

**Decision**: Use `ruff` for all linting and formatting (no other linters)
- **Rationale**: User explicitly requested this. Ruff is fast, modern, and combines the functionality of multiple tools (Black, isort, flake8, etc.). Single tool approach reduces configuration complexity.
- **Alternative**: Using multiple linters (flake8, black, isort, pylint) would be more fragmented.

**Decision**: Target Python 3.12 exclusively
- **Rationale**: User explicitly requested 3.12. No need to maintain compatibility with earlier versions. This allows use of latest language features and simplifies testing matrix.

### K.5 Dependency Management

**Decision**: Use `uv` exclusively for all dependency and environment management
- **Rationale**: User explicitly requested this. No pip usage. Uv is faster, more reliable, and provides better reproducibility through lock files.
- **Alternative**: pip would work but is slower and less reliable for lock file management.

### K.6 Security Approach

**Decision**: Comprehensive security review after implementation, not just security checklist
- **Rationale**: User explicitly requested security review. This plan dedicates an entire phase (Phase 6) to manual code review, vulnerability scanning, and security testing. This goes beyond basic security checks and ensures comprehensive coverage.

**Decision**: Enforce file permissions (0600) on token storage
- **Rationale**: Critical security measure to prevent other users on the system from reading stored tokens. Implementation must verify permissions are correctly set during both write and read operations.

**Decision**: No credential logging or display in error messages
- **Rationale**: Essential security practice. All error handling must be audited to ensure tokens and credentials never appear in logs, error messages, or user-facing output.

### K.7 Testing Strategy

**Decision**: Comprehensive test coverage including unit, integration, and security tests
- **Rationale**: Multi-layered testing approach ensures reliability and security. Unit tests verify component correctness, integration tests verify workflows, and security tests verify no credential leaks or vulnerabilities.
- **Coverage target**: >80% on critical paths (authentication, API calls, token handling)

### K.8 Documentation

**Decision**: Maintain `.claudeCode/PLAN.md` as living progress document
- **Rationale**: This plan serves both as a specification and a tracking mechanism. Keeping it updated in the repository provides historical record and enables work resumption if interrupted.

**Decision**: Use C4 model for architecture documentation
- **Rationale**: C4 model (Context, Container, Component, Code) provides clear, hierarchical view of system architecture. More effective than ad-hoc diagrams.

### K.9 Packaging

**Decision**: Use setuptools with PEP 517/518 standards
- **Rationale**: Modern, widely supported packaging approach. Enables installation via both `uv pip install` and future PyPI distribution.

**Decision**: Single CLI entry point (`perplexity`)
- **Rationale**: Simple, intuitive command name. Commands (auth, query, logout, status) are subcommands accessed via Click framework.