# Claude.md - Operational Log & Technical Decisions

**Last Updated**: 2025-11-08
**Current Phase**: Phases 1-4 COMPLETE, Ready for Phase 5
**Overall Progress**: 4/8 phases complete (Core functionality COMPLETE)

---

## Phase 1: Research & Setup - Complete Record

### Date Range
- **Started**: 2025-11-08
- **Completed**: 2025-11-08
- **Duration**: Single session

### API Discovery Findings

**Primary Query Endpoint Discovered**: `POST https://www.perplexity.ai/rest/sse/perplexity_ask`

**Key Characteristics**:
- Protocol: Server-Sent Events (SSE) streaming
- Method: POST
- Content-Type: application/json
- Response: text/event-stream (incremental updates)
- Authentication: Bearer token (JWT from Phase 2)
- API Version: 2.18

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

**Response Format**: SSE stream with incremental JSON messages
- Format: `event: message\ndata: {json}\n\n`
- Multiple messages sent as answer is generated
- Final message marked with `final_sse_message: true`
- Answer appears in `blocks` array with different `intended_usage` types

**Research Method**: Chrome DevTools Protocol network monitoring during live query submission

**Test Query**: "What is the capital of France?"
- Successfully submitted and received streaming response
- Thread created: `what-is-the-capital-of-france-L86vRtELQ6.qJj9k6CzYhQ`
- Response included web results and answer text

**Additional Endpoints Found**:
- `/rest/rate-limit/all` - Rate limit info
- `/rest/thread/mark_viewed/<uuid>` - Thread tracking
- `/rest/collections/list_user_collections` - User collections
- `/api/version` - API version info

**Documentation**: Complete API discovery documented in `.claudeCode/API_DISCOVERY.md`

---

## Phase 2: Authentication - Complete Record

### Date Range
- **Started**: 2025-11-08
- **Completed**: 2025-11-08
- **Duration**: Single session

### Key Findings from Existing Code

**`authenticate.py` Analysis**:
- ✓ Implements Option A: Browser automation (Chrome DevTools Protocol)
- ✓ Uses websockets for remote debugging communication
- ✓ Extracts tokens from both localStorage and cookies
- ✗ Stored tokens in `.perplexity-auth.json` in project root
- ✗ No file permission enforcement (0600)
- ✗ Not integrated into package structure

### Authentication Strategy Chosen: Option A (Browser Automation)

**Rationale**:
- Most reliable approach (captures live authentication)
- Works with existing Chrome infrastructure
- Enables real-time token extraction
- Proven in existing authenticate.py

**Implementation Details**:
- Chrome DevTools Protocol over WebSocket
- Connects to localhost:9222 (standard remote debugging port)
- Navigates to https://www.perplexity.ai
- Monitors localStorage for `pplx-next-auth-session` key
- Extracts encrypted JWT token (~484 characters)
- Fallback to cookies if localStorage unavailable

**Token Format**:
- Type: JWT (JSON Web Token), encrypted
- Encryption: AES-256-GCM (JWE format)
- Header: `eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0`
- Size: ~484 characters total
- Example: `eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..6YRy1ImfS...`

### Implementation Decisions

#### 1. Token Storage Location

**Decision**: `~/.config/perplexity-cli/token.json` (platform-aware)

**Rationale**:
- Standard location for user config files
- Follows XDG Base Directory specification (Linux/macOS)
- Windows equivalent: `%APPDATA%\perplexity-cli\`
- Separates user data from application code
- Cross-platform support

**Alternative Rejected**:
- `.perplexity-auth.json` in project root (not portable, clutters repo)
- Encrypted file storage (adds complexity, not required per plan)
- OS keyring (adds dependency, overcomplicated)

#### 2. File Permissions

**Decision**: Enforce 0600 (rw-------)

**Rationale**:
- Only owner can read/write
- Prevents group/other access
- Detects tampering on load
- Follows Unix security best practices
- Required by plan specification

**Implementation**:
- Set on save: `os.chmod(token_path, 0o600)`
- Verify on load: Check actual permissions match 0o600
- Error handling: RuntimeError if insecure permissions detected

**Security Implications**:
- ✓ Group members cannot read token
- ✓ Other users cannot read token
- ✓ Tampered tokens detected on load
- ✓ Clear error message guides recovery

#### 3. Token Capture Strategy

**Implementation Approach**: Async/sync wrapper pattern

```python
async def authenticate_with_browser(url, port) -> str:
    """Async function for token extraction"""

def authenticate_sync(url, port) -> str:
    """Sync wrapper using asyncio.run()"""
```

**Rationale**:
- Async allows non-blocking Chrome communication
- Sync wrapper enables CLI integration
- Clean separation of concerns

#### 4. Error Handling Strategy

**Three Error Types Defined**:

1. **OSError**: File I/O and JSON parsing failures
   - Corrupted token files
   - Failed reads/writes
   - Permission setting failures

2. **RuntimeError**: Permission violations
   - Insecure file permissions detected
   - Chrome connection failures
   - Authentication failures

3. **None**: Graceful missing token handling
   - `load_token()` returns None if file missing
   - `clear_token()` idempotent (no error if missing)

**Rationale**:
- Specific exceptions enable targeted handling
- None return avoids exception for normal case
- Clear error messages don't leak credentials

#### 5. Testing Strategy

**Three-Level Approach**:

**Unit Tests (22 tests)**:
- Test individual functions in isolation
- Mock file system and Chrome interactions
- Verify permissions, JSON handling, extraction logic
- Security-specific permission tests

**Integration Tests (9 tests)**:
- Test complete workflows (save-load-delete)
- Test token persistence across instances
- Test error recovery scenarios
- Simulate multiple CLI invocations

**Manual Tests (4 tests)**:
- 2.4.1: Actual Perplexity.ai authentication
- 2.4.2: Token persistence verification
- 2.4.3: Logout functionality
- 2.4.4: Error scenarios (corrupted, insecure, missing)

**Coverage**:
- 31 automated tests: 100% passing
- 4 manual tests: 100% passing
- Total: 35 tests, all passing ✅

### Security Review

**File Permissions**:
- ✅ Owner read: Allowed (0600)
- ✅ Owner write: Allowed (0600)
- ✅ Group read: DENIED
- ✅ Group write: DENIED
- ✅ Other read: DENIED
- ✅ Other write: DENIED

**Token Handling**:
- ✅ Never printed in debug output
- ✅ Never logged to files
- ✅ Never included in error messages
- ✅ Verified format on load
- ✅ Encrypted in transit (HTTPS to Perplexity)

**Error Messages**:
- ✅ No token content in errors
- ✅ File paths use variables
- ✅ All errors actionable
- ✅ Permission recovery guidance provided

**Code Quality**:
- ✅ Type hints: 100% coverage
- ✅ Docstrings: 100% coverage
- ✅ Ruff linting: All checks passing
- ✅ No hardcoded credentials

### Phase 2 Challenges & Solutions

**Challenge 1**: Python version compatibility
- **Issue**: Project had Python 3.13 venv
- **Solution**: Created new 3.12 venv with `uv venv --python=3.12`
- **Result**: All code tested on Python 3.12.11

**Challenge 2**: Ruff formatting conflicts
- **Issue**: Initial code had multiple style issues
- **Solution**: Auto-fixed with `ruff check --fix` and `ruff format`
- **Result**: All checks passing, code properly formatted

**Challenge 3**: Duplicate except clauses
- **Issue**: Two consecutive except OSError clauses in token_manager
- **Solution**: Merged into single except clause
- **Result**: Code properly structured

**Challenge 4**: Chrome connection testing
- **Issue**: Needed to test actual Perplexity.ai authentication
- **Solution**: Created test script using websockets to Chrome DevTools
- **Result**: Successfully extracted real token from live session

### Technology Stack

**Runtime Dependencies**:
- `websockets>=12.0`: WebSocket communication with Chrome DevTools
- `click>=8.0`: CLI framework (not used in Phase 2)
- `httpx>=0.25`: HTTP client (not used in Phase 2)

**Development Dependencies**:
- `pytest>=8.0`: Test framework
- `pytest-mock>=3.0`: Mocking utilities
- `pytest-asyncio>=1.2.0`: Async test support
- `ruff>=0.1`: Linting and formatting

**Platform Dependencies**:
- Chrome/Chromium with remote debugging enabled
- Python 3.12.x
- Unix-like OS (Linux/macOS) or Windows with %APPDATA%

### Files Created During Phase 2

**Core Implementation**:
- `src/perplexity_cli/__init__.py`
- `src/perplexity_cli/auth/__init__.py`
- `src/perplexity_cli/auth/oauth_handler.py` (245 lines)
- `src/perplexity_cli/auth/token_manager.py` (115 lines)
- `src/perplexity_cli/utils/__init__.py`
- `src/perplexity_cli/utils/config.py` (43 lines)
- `src/perplexity_cli/api/__init__.py`
- `src/perplexity_cli/cli.py` (placeholder)

**Tests**:
- `tests/__init__.py`
- `tests/test_auth.py` (280 lines, 22 tests)
- `tests/test_auth_integration.py` (200 lines, 9 tests)

**Configuration**:
- `pyproject.toml` (PEP 517/518 compliant)
- `requirements.txt` (pinned versions)

**Manual Testing**:
- `test_manual_auth.py` (350 lines)
- `test_chrome_connection.py` (100 lines)
- `save_auth_token.py` (35 lines)

**Documentation**:
- `.claudeCode/PHASE2_SUMMARY.md`
- `.claudeCode/PHASE2_TEST_REPORT.md`
- `.claudeCode/CLAUDE.md` (this file)

### Lessons Learned

1. **Chrome DevTools Protocol Effectiveness**: Proven approach for browser automation with minimal dependencies (just websockets)

2. **File Permission Enforcement**: Critical to verify permissions on both write and read to prevent tampering

3. **Error-Specific Exceptions**: Using RuntimeError vs OSError enables clear error handling in calling code

4. **Test-Driven Security**: Writing security tests alongside functional tests catches vulnerabilities early

5. **Manual Testing Necessity**: Automated tests cannot fully replace testing actual authentication flow with real services

### Known Limitations & Future Improvements

**Current Phase 2 Limitations**:
- Token refresh not implemented (deferred to Phase 3 when API integration needed)
- No token expiration warning (will add in Phase 3 with API usage)
- Requires Chrome with remote debugging (not suitable for headless environments)

**Future Considerations for Phase 3+**:
- Implement token refresh based on Perplexity API expiration
- Add HTTP client with auth headers
- Create API endpoint abstractions
- Add response parsing and answer extraction
- Implement CLI command handlers

---

## Repository State

**Branch**: master
**Last Commits**:
1. `a9d272c` - Add comprehensive Phase 2 completion summary documentation
2. `b05b560` - Phase 2.4 complete: End-to-end authentication testing (all tests passed)
3. `87c2864` - Phase 2 complete: Implement authentication with secure token storage

**Uncommitted Changes**: None

**Git Status**: Clean, all changes committed

---

## Summary

Phase 2 (Authentication) is complete and production-ready. The implementation:

- ✅ Successfully authenticates with Perplexity.ai via Google OAuth
- ✅ Securely stores tokens with 0600 file permissions
- ✅ Implements comprehensive error handling
- ✅ Includes 31 passing tests (22 unit + 9 integration)
- ✅ Passes all security verification checks
- ✅ Meets all code quality standards
- ✅ Includes 4 passing manual end-to-end tests

---

## Phase 3: API Client - Complete Record

### Date Range
- **Started**: 2025-11-08
- **Completed**: 2025-11-08
- **Duration**: Single session

### Implementation Summary

**SSE Streaming Client**: Built complete HTTP client with Server-Sent Events support
- Endpoint: `POST https://www.perplexity.ai/rest/sse/perplexity_ask`
- Protocol: SSE (text/event-stream)
- Parser: event:/data: format handler
- Authentication: Bearer JWT token

**Key Implementation Decisions**:

1. **SSE Stream Parsing**: Custom parser for `event: message\ndata: {json}` format
   - Handles multi-line data payloads
   - Validates JSON on each message
   - Detects stream completion

2. **Answer Extraction**: From markdown_block with chunks array
   - Discovered actual response structure through live testing
   - Answer in `blocks` with `intended_usage: "ask_text"`
   - Text in `markdown_block.chunks[]` array
   - Final answer only from last message (final_sse_message: true)

3. **Data Models**: Dataclass-based models for type safety
   - QueryParams with all required fields
   - QueryRequest for complete payload
   - SSEMessage for streaming responses
   - Block for answer blocks
   - WebResult for search results

4. **Error Handling**: Status-specific error messages
   - 401: "Authentication failed. Token may be invalid or expired."
   - 403: "Access forbidden. Check API permissions."
   - 429: "Rate limit exceeded. Please wait and try again."

### Challenges & Solutions

**Challenge 1**: Understanding SSE response format
- **Issue**: Initial attempts returned empty answers
- **Solution**: Created test_query_realtime.py to inspect live messages
- **Result**: Discovered markdown_block.chunks structure

**Challenge 2**: Answer duplication from streaming
- **Issue**: Early implementation collected from all messages (duplicates)
- **Solution**: Only extract from final message with intended_usage: "ask_text"
- **Result**: Clean, single answer returned

**Challenge 3**: SSE parsing with httpx
- **Issue**: httpx.stream() returns raw lines, not parsed events
- **Solution**: Built custom _parse_sse_stream() method
- **Result**: Correctly parses event:/data: format with multi-line support

### Files Created During Phase 3

**Core Implementation**:
- `src/perplexity_cli/api/models.py` (180 lines)
- `src/perplexity_cli/api/client.py` (145 lines)
- `src/perplexity_cli/api/endpoints.py` (160 lines)
- Total: 485 lines of production code

**Tests**:
- `tests/test_api_client.py` (14 tests, 270 lines)
- `tests/test_api_integration.py` (8 tests, 120 lines)
- `tests/test_query_simple.py` (quick test utility)
- `tests/test_query_realtime.py` (SSE message inspector)

### Test Results

**Total Tests**: 62 (all passing)
- Authentication: 40 tests
- API Client Unit: 14 tests
- API Integration: 8 tests

**Test Coverage**:
- Models: 100% (all to_dict/from_dict tested)
- SSE Parser: Comprehensive (single, multiple, multiline messages)
- Error Handling: 401, 403, 429, invalid JSON
- Integration: Real API queries verified

**Verified Queries**:
- "What is 2+2?" → "2+2 equals 4..."
- "What is the capital of France?" → "Paris..."
- "What is Python?" → Complete answer
- "What is 1+1?" → "1+1 equals 2..."

---

## Phase 4: CLI Integration - Complete Record

### Date Range
- **Started**: 2025-11-08
- **Completed**: 2025-11-08
- **Duration**: Single session

### Implementation Summary

**Click CLI Framework**: Built complete command-line interface with 4 commands
- Entry point: `perplexity` command
- Framework: Click (declarative CLI builder)
- Output: Answers to stdout, errors to stderr
- Exit codes: 0 (success), 1 (error)

**Commands Implemented**:

1. **`perplexity auth [--port PORT]`**
   - Authenticates with Perplexity.ai via Chrome DevTools
   - Saves JWT token to ~/.config/perplexity-cli/token.json
   - Error handling with troubleshooting steps
   - Default port: 9222

2. **`perplexity query "QUESTION"`**
   - Submits query to Perplexity API
   - Returns answer to stdout (pipeable)
   - Checks authentication before query
   - Comprehensive error handling (401, 403, 429, network)

3. **`perplexity logout`**
   - Clears stored authentication token
   - Confirms deletion to user
   - Idempotent (safe if no token)

4. **`perplexity status`**
   - Shows authentication status
   - Displays token location and length
   - Verifies token with API call to /api/user
   - Shows username and email if authenticated

### Key Implementation Decisions

**Decision 1**: Output routing (stdout vs stderr)
- **Rationale**: Answers to stdout enables piping (perplexity query "X" > file.txt)
- **Implementation**: All errors to stderr, only answers to stdout
- **Benefit**: Unix-friendly, composable with other tools

**Decision 2**: Error message strategy
- **Rationale**: Users need actionable guidance, not cryptic errors
- **Implementation**:
  - 401 → "Token may be expired. Re-authenticate with: perplexity auth"
  - Network → "Check your internet connection"
  - No auth → "Please authenticate first with: perplexity auth"
- **Benefit**: Self-service troubleshooting

**Decision 3**: Status command with token verification
- **Rationale**: Users need to know if token is valid, not just present
- **Implementation**: Makes API call to /api/user to verify token works
- **Trade-off**: Adds network call, but provides certainty

**Decision 4**: Exit codes for automation
- **Rationale**: Enable shell scripting and error detection
- **Implementation**: 0 for success, 1 for any error
- **Benefit**: Scripts can check $? for success

### Testing Results

**CLI Tests**: 13 tests (all passing)
- Command invocation tests (help, version)
- Status tests (authenticated/not authenticated)
- Logout tests (with/without token)
- Query tests (success, no auth, network error)
- Auth tests (success, failure)
- Integration tests with real components

**Manual Testing**: All workflows verified
- ✅ `perplexity --help` → Shows commands
- ✅ `perplexity status` → Shows auth status
- ✅ `perplexity query "What is 5+5?"` → "5+5 equals 10..."
- ✅ `perplexity query "meaning of life"` → Full philosophical answer
- ✅ `perplexity logout` → Removes token
- ✅ `perplexity query` (no auth) → Error with guidance
- ✅ Output piping → `perplexity query "X" > file.txt` works

**Total Project Tests**: 75 (all passing)
- 40 authentication tests
- 14 API client unit tests
- 8 API integration tests
- 13 CLI tests

### Files Created During Phase 4

**Core Implementation**:
- `src/perplexity_cli/cli.py` (219 lines) - Complete CLI implementation

**Tests**:
- `tests/test_cli.py` (13 tests, 180 lines)
- `tests/test_query_simple.py` (quick test utility)

### CLI Now Fully Functional

The `perplexity` command is installed and working:
```bash
perplexity status              # Check authentication
perplexity query "question"    # Ask Perplexity
perplexity logout              # Clear credentials
perplexity --help              # Show help
```

**Core product is complete!** Remaining phases are polish and distribution.
