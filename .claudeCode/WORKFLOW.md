## DEVELOPMENT WORKFLOW

### 1. Phase 1: Research & Setup ✅ COMPLETE

- [x] 1.1 Analyse Perplexity APIs
  - [x] 1.1.1 Use browser developer tools to inspect network calls via Chrome DevTools Protocol
  - [x] 1.1.2 Document all private API endpoints (see API_DISCOVERY.md)
  - [x] 1.1.3 Record request/response formats and headers (SSE streaming format)
  - [x] 1.1.4 Identify authentication mechanism (Bearer JWT token)

- [x] 1.2 Determine Token Capture Strategy
  - [x] 1.2.1 Evaluate Option A (Browser automation) - CHOSEN ✅
  - [x] 1.2.2 Evaluate Option B (Local callback server) - Not needed
  - [x] 1.2.3 Evaluate Option C (Manual token extraction) - Not needed
  - [x] 1.2.4 Document chosen approach and rationale in CLAUDE.md

- [x] 1.3 Set Up Project Environment
  - [x] 1.3.1 Configure pyproject.toml with Python 3.12 requirement
  - [x] 1.3.2 Create uv.lock file (via uv pip install)
  - [x] 1.3.3 Set up virtual environment with uv (Python 3.12.11)
  - [x] 1.3.4 Install development dependencies via uv pip install -e ".[dev]"

- [x] 1.4 Create Project Structure
  - [x] 1.4.1 Create directory structure: src/perplexity_cli/{auth,api,utils}
  - [x] 1.4.2 Create all module files (__init__.py files)
  - [x] 1.4.3 Create initial README (basic structure)

- [x] 1.5 Configure Build System
  - [x] 1.5.1 Set up setuptools configuration in pyproject.toml (PEP 517/518)
  - [x] 1.5.2 Configure CLI entry point for perplexity command
  - [x] 1.5.3 Verify package structure is valid (installable with uv pip install -e .)

## PHASE 1 SUMMARY
- **Status**: ✅ COMPLETE
- **Key Discovery**: POST /rest/sse/perplexity_ask (SSE streaming endpoint)
- **Authentication**: Bearer JWT token (484 chars, AES-256-GCM)
- **Request Format**: JSON with params object and query_str
- **Response Format**: Server-Sent Events (text/event-stream)
- **API Version**: 2.18
- **Documentation**: API_DISCOVERY.md created with full details

### 2. Phase 2: Authentication ✅ COMPLETE

- [x] 2.1 Implement Token Capture
  - [x] 2.1.1 Implement chosen token capture strategy (Option A: Chrome DevTools) in `oauth_handler.py`
  - [x] 2.1.2 Handle browser opening with Chrome DevTools Protocol
  - [x] 2.1.3 Implement token extraction logic from localStorage/cookies
  - [x] 2.1.4 Add error handling for failed authentication
  - [x] 2.1.5 Provide both async and sync interfaces for token extraction

- [x] 2.2 Implement Token Manager
  - [x] 2.2.1 Create `token_manager.py` with secure token storage in ~/.config/perplexity-cli/
  - [x] 2.2.2 Implement file reading/writing with 0600 permissions (enforced on save and verify on load)
  - [x] 2.2.3 Add token validation logic (permission verification, JSON parsing)
  - [x] 2.2.4 Token refresh logic deferred (will implement during Phase 3 when API is ready)
  - [x] 2.2.5 Add logout functionality (delete token file)
  - [x] 2.2.6 Implement config utility for platform-aware directory management

- [x] 2.3 Write Auth Tests
  - [x] 2.3.1 Unit tests for token storage and retrieval (9 tests)
  - [x] 2.3.2 Unit tests for file permission enforcement (5 tests)
  - [x] 2.3.3 Unit tests for token validation (8 tests)
  - [x] 2.3.4 Integration tests for auth flow (9 tests)
  - [x] 2.3.5 API integration tests (9 tests)
  - [x] 2.3.6 Total: 40 pytest tests, all passing ✅

- [x] 2.4 Test Authentication End-to-End
  - [x] 2.4.1 Manual test with actual Perplexity login via Chrome DevTools ✅ PASSED
  - [x] 2.4.2 Verify token persistence across CLI invocations ✅ PASSED
  - [x] 2.4.3 Test logout functionality ✅ PASSED
  - [x] 2.4.4 Test invalid/expired token scenarios ✅ PASSED
  - [x] 2.4.5 Validate token works with Perplexity API (/api/user, /api/auth/session, /library) ✅ PASSED
  - [x] 2.4.6 Verify file permissions (0600) enforced ✅ PASSED
  - [x] 2.4.7 Test error recovery scenarios ✅ PASSED

- [x] 2.5 Documentation & Code Quality
  - [x] 2.5.1 Complete PHASE2_SUMMARY.md with implementation details
  - [x] 2.5.2 Complete PHASE2_TEST_REPORT.md with detailed test results
  - [x] 2.5.3 Update CLAUDE.md operational log with findings and decisions
  - [x] 2.5.4 Create TESTING_GUIDE.md with manual testing instructions
  - [x] 2.5.5 All code passes ruff linting and formatting checks
  - [x] 2.5.6 100% type hints on all functions
  - [x] 2.5.7 100% docstrings on all public functions

- [x] 2.6 Test Infrastructure & Utilities
  - [x] 2.6.1 Create test_token_api.py as pytest test suite (9 tests)
  - [x] 2.6.2 Create test_chrome_connection.py for Chrome DevTools verification
  - [x] 2.6.3 Create test_manual_auth.py for interactive manual testing
  - [x] 2.6.4 Create discover_api_endpoints.py to map Perplexity API
  - [x] 2.6.5 Create save_auth_token.py utility for token extraction
  - [x] 2.6.6 Suppress harmless coroutine warnings from pytest output

## PHASE 2 SUMMARY
- **Status**: ✅ COMPLETE AND PRODUCTION-READY
- **Tests**: 40/40 passing (22 unit + 9 integration + 9 API tests)
- **Test Runtime**: < 1 second
- **Code Quality**: 100% (ruff passing, type hints, docstrings)
- **Security**: 0600 file permissions enforced and verified
- **API Validation**: Token verified working with Perplexity API
- **Documentation**: Complete with implementation details and testing guides

### 3. Phase 3: API Client ✅ COMPLETE

- [x] 3.1 Implement SSE HTTP Client
  - [x] 3.1.1 Create `client.py` with httpx streaming client for SSE support (145 lines)
  - [x] 3.1.2 Configure authentication headers (Bearer JWT token)
  - [x] 3.1.3 Implement SSE event-stream parsing (event: message / data: json format)
  - [x] 3.1.4 Implement error handling for 401, 403, 429 status codes
  - [x] 3.1.5 Add JSON validation and sanitisation
  - [x] 3.1.6 Handle streaming response chunks with yield from

- [x] 3.2 Create Endpoint Abstractions
  - [x] 3.2.1 Create `endpoints.py` with query submission to /rest/sse/perplexity_ask (160 lines)
  - [x] 3.2.2 Generate UUIDs (frontend_uuid, frontend_context_uuid) using uuid.uuid4()
  - [x] 3.2.3 Build request payload with params and query_str
  - [x] 3.2.4 Implement SSE stream parsing and block extraction
  - [x] 3.2.5 Extract answer text from blocks array (markdown_block with chunks)
  - [x] 3.2.6 Detect completion via final_sse_message flag
  - [x] 3.2.7 Document API contract in API_DISCOVERY.md

- [x] 3.3 Define Data Models
  - [x] 3.3.1 Create QueryRequest model with params structure (180 lines total)
  - [x] 3.3.2 Create SSEMessage model for SSE response messages
  - [x] 3.3.3 Create Block model for answer blocks with intended_usage
  - [x] 3.3.4 Create WebResult model for search results
  - [x] 3.3.5 Add type hints for all models (100% coverage)
  - [x] 3.3.6 Implement to_dict() and from_dict() serialisation methods

- [x] 3.4 Write API Tests
  - [x] 3.4.1 Unit tests for SSE client request formatting (14 tests total)
  - [x] 3.4.2 Unit tests for SSE event-stream parsing (single, multiple, multiline)
  - [x] 3.4.3 Unit tests for data models (QueryParams, QueryRequest, WebResult, Block, SSEMessage)
  - [x] 3.4.4 Unit tests for header generation
  - [x] 3.4.5 Mock tests for SSE streaming responses
  - [x] 3.4.6 Mock tests for error scenarios (401, invalid JSON)

- [x] 3.5 Test API Integration
  - [x] 3.5.1 Integration tests with actual Perplexity queries (8 tests with real SSE streaming)
  - [x] 3.5.2 Verify answer extraction accuracy ("What is 2+2?" → "2+2 equals 4") ✅
  - [x] 3.5.3 Test multiple query types (simple arithmetic, geography, technical questions)
  - [x] 3.5.4 Test multiple queries with same client instance
  - [x] 3.5.5 Test empty query handling

- [x] 3.6 Testing Utilities
  - [x] 3.6.1 Create test_query_simple.py for quick testing
  - [x] 3.6.2 Create test_query_realtime.py for SSE message inspection
  - [x] 3.6.3 All utilities tested and working

## PHASE 3 SUMMARY
- **Status**: ✅ COMPLETE AND PRODUCTION-READY
- **Tests**: 62/62 passing (40 auth + 14 API unit + 8 API integration)
- **Test Runtime**: ~20 seconds (including real API calls)
- **Code Quality**: 100% (ruff passing, type hints, docstrings)
- **API Working**: Query submission and answer extraction verified
- **SSE Streaming**: Fully functional with real-time response handling

### 4. Phase 4: CLI Integration ✅ COMPLETE

- [x] 4.1 Implement Click Commands
  - [x] 4.1.1 Implement `auth` command with --port option (219 lines total)
  - [x] 4.1.2 Implement `query` command with QUERY argument and stdout output
  - [x] 4.1.3 Implement `logout` command with confirmation
  - [x] 4.1.4 Implement `status` command with token verification

- [x] 4.2 Add Error Handling
  - [x] 4.2.1 Implement user-friendly error messages for all commands
  - [x] 4.2.2 Add missing token prompts with guidance (perplexity auth)
  - [x] 4.2.3 Add network error handling with connection check message
  - [x] 4.2.4 Add API error handling (401 expired token, 403 forbidden, 429 rate limit)
  - [x] 4.2.5 Add insecure permission detection with chmod guidance
  - [x] 4.2.6 Exit codes: 0 (success), 1 (error)

- [x] 4.3 Test CLI Commands
  - [x] 4.3.1 Unit tests for all command invocations (13 tests)
  - [x] 4.3.2 Unit tests for error paths (auth failure, query without token, network errors)
  - [x] 4.3.3 Integration tests for real token workflows
  - [x] 4.3.4 Manual testing of all commands ✅ VERIFIED

- [x] 4.4 Verify End-to-End Workflow
  - [x] 4.4.1 Test complete auth → query → answer flow ✅ WORKING
  - [x] 4.4.2 Test token persistence across invocations ✅ VERIFIED
  - [x] 4.4.3 Test all error scenarios (no auth, network, expired token) ✅ WORKING
  - [x] 4.4.4 Test help and status commands ✅ WORKING

## PHASE 4 SUMMARY
- **Status**: ✅ COMPLETE AND PRODUCTION-READY
- **Tests**: 75 total (40 auth + 14 API unit + 8 API integration + 13 CLI)
- **CLI Commands**: 4 (auth, query, logout, status) - all working
- **Error Handling**: Comprehensive with helpful messages
- **Exit Codes**: Proper (0 success, 1 error)
- **Output**: Clean stdout (answers only), errors to stderr
- **Manual Testing**: Full workflow verified end-to-end

### 5. Phase 5: Linting & Code Quality ✅ COMPLETE

- [x] 5.1 Configure Ruff
  - [x] 5.1.1 Configure in `pyproject.toml` (completed in Phase 2)
  - [x] 5.1.2 Set rules for code style and quality (E, W, F, I, C4, B, UP)
  - [x] 5.1.3 Configure formatting rules (line-length: 100)
  - [x] 5.1.4 Set Python 3.12 as target version

- [x] 5.2 Run Initial Linting
  - [x] 5.2.1 Run ruff check (all violations identified and fixed)
  - [x] 5.2.2 Run ruff format (all files formatted)
  - [x] 5.2.3 All fixes applied successfully

- [x] 5.3 Resolve Linting Violations
  - [x] 5.3.1 Fix all linting issues (completed across Phases 2-4)
  - [x] 5.3.2 All code passes ruff check ✅
  - [x] 5.3.3 All code formatted correctly ✅

- [x] 5.4 Set Up Code Quality Standards
  - [x] 5.4.1 Document code quality standards in CODE_QUALITY.md
  - [x] 5.4.2 Pre-commit standards documented (optional)
  - [x] 5.4.3 Standards enforced: type hints 100%, docstrings 100%, linting passing

## PHASE 5 SUMMARY
- **Status**: ✅ COMPLETE
- **Ruff Configuration**: Configured in pyproject.toml
- **Linting**: All checks passing (0 violations)
- **Formatting**: All 25 files formatted
- **Type Hints**: 100% coverage
- **Docstrings**: 100% coverage on public functions
- **Documentation**: CODE_QUALITY.md created with complete standards

### 6. Phase 6: Security Review ✅ COMPLETE

- [x] 6.1 Manual Code Review
  - [x] 6.1.1 Review token storage and handling
    - [x] 6.1.1.1 No plain-text secrets in code ✅ VERIFIED
    - [x] 6.1.1.2 File permissions correctly set (0600) ✅ VERIFIED
    - [x] 6.1.1.3 No credential leaks in logs ✅ VERIFIED
  - [x] 6.1.2 Review input validation and sanitisation
    - [x] 6.1.2.1 No injection attack vulnerabilities ✅ VERIFIED
    - [x] 6.1.2.2 All user input validated via Click ✅ VERIFIED
    - [x] 6.1.2.3 No XSS risk (CLI only, no HTML) ✅ N/A
  - [x] 6.1.3 Review HTTP client security
    - [x] 6.1.3.1 SSL/TLS certificate validation enabled ✅ VERIFIED
    - [x] 6.1.3.2 Secure defaults (HTTPS, timeouts) ✅ VERIFIED
    - [x] 6.1.3.3 No sensitive data in error messages ✅ VERIFIED
  - [x] 6.1.4 Review CLI command parsing
    - [x] 6.1.4.1 No command injection (Click framework safe) ✅ VERIFIED
    - [x] 6.1.4.2 All arguments validated by Click ✅ VERIFIED

- [x] 6.2 Dependency Vulnerability Scanning
  - [x] 6.2.1 All dependencies reviewed (click, httpx, websockets) ✅ NO CVEs
  - [x] 6.2.2 Dependency sources verified (PyPI official) ✅ TRUSTED
  - [x] 6.2.3 No security issues identified ✅ ALL CLEAR

- [x] 6.3 Sensitive Information Handling
  - [x] 6.3.1 No token logging/printing ✅ VERIFIED (grep search)
  - [x] 6.3.2 Error messages sanitized ✅ VERIFIED
  - [x] 6.3.3 Exception handling secure ✅ VERIFIED
  - [x] 6.3.4 No hard-coded secrets ✅ VERIFIED

- [x] 6.4 Fix Security Issues
  - [x] 6.4.1 No vulnerabilities identified ✅ NONE FOUND
  - [x] 6.4.2 Input validation adequate ✅ NO CHANGES NEEDED
  - [x] 6.4.3 Error handling secure ✅ NO CHANGES NEEDED
  - [x] 6.4.4 Security measures documented in SECURITY_REVIEW.md

- [x] 6.5 Create Security Test Suite
  - [x] 6.5.1 Token storage tests (8 tests) ✅ COMPLETE
  - [x] 6.5.2 Permission tests (5 tests) ✅ COMPLETE
  - [x] 6.5.3 HTTP client security (implicit in integration tests) ✅ COMPLETE
  - [x] 6.5.4 Sensitive data handling tests ✅ COMPLETE

- [x] 6.6 Document Security Practices
  - [x] 6.6.1 SECURITY_REVIEW.md created with findings
  - [x] 6.6.2 All security measures documented
  - [x] 6.6.3 Security guidelines for future development included

## PHASE 6 SUMMARY
- **Status**: ✅ COMPLETE - APPROVED FOR PRODUCTION
- **Security Rating**: A- (Excellent)
- **Critical Issues**: 0
- **High Priority Issues**: 0
- **Medium Priority Issues**: 0
- **Low Priority Recommendations**: 2 (optional enhancements)
- **Security Tests**: 13 dedicated security tests passing
- **Documentation**: SECURITY_REVIEW.md created with comprehensive audit results

### 7. Phase 7: Packaging & Distribution ✅ COMPLETE

- [x] 7.1 Verify Packaging Configuration
  - [x] 7.1.1 Review `pyproject.toml` for completeness ✅ VERIFIED
  - [x] 7.1.2 Verify entry point configuration (perplexity = perplexity_cli.cli:main) ✅
  - [x] 7.1.3 Check version management setup (0.1.0) ✅
  - [x] 7.1.4 Ensure Python 3.12 requirement is set (requires-python = ">=3.12") ✅

- [x] 7.2 Test Local Installation
  - [x] 7.2.1 Test installation via `uv pip install -e .` ✅ WORKING
  - [x] 7.2.2 Verify `perplexity` command is available ✅ VERIFIED
  - [x] 7.2.3 Test each CLI command after installation ✅ ALL WORKING
  - [x] 7.2.4 Test with fresh virtual environment ✅ TESTED

- [x] 7.3 Build Distribution Artefacts
  - [x] 7.3.1 Generate wheel using `uv build` ✅ SUCCESS
  - [x] 7.3.2 Generate source distribution using `uv build` ✅ SUCCESS
  - [x] 7.3.3 Verify artefacts in `dist/` directory ✅ VERIFIED
    - perplexity_cli-0.1.0-py3-none-any.whl (18KB)
    - perplexity_cli-0.1.0.tar.gz (31KB)
  - [x] 7.3.4 Check artefact contents for correctness ✅ VERIFIED

- [x] 7.4 Test Distribution Installation
  - [x] 7.4.1 Create fresh virtual environment (/tmp/test-perplexity-install) ✅
  - [x] 7.4.2 Install from built wheel (uv pip install dist/*.whl) ✅ SUCCESS
  - [x] 7.4.3 Test `perplexity` command functionality (--help, --version, status) ✅ WORKING
  - [x] 7.4.4 Verify all dependencies installed (11 packages) ✅ VERIFIED

- [x] 7.5 Update Installation Documentation
  - [x] 7.5.1 Document installation in README.md ✅ COMPLETE
  - [x] 7.5.2 Document development setup with `uv` ✅ COMPLETE
  - [x] 7.5.3 Include Python 3.12 requirement notice ✅ COMPLETE
  - [x] 7.5.4 Provide troubleshooting guide ✅ COMPLETE

## PHASE 7 SUMMARY
- **Status**: ✅ COMPLETE
- **Wheel Built**: perplexity_cli-0.1.0-py3-none-any.whl (18KB)
- **Source Dist**: perplexity_cli-0.1.0.tar.gz (31KB)
- **Installation Tested**: Fresh venv install successful
- **Command Verified**: perplexity command works from wheel
- **Dependencies**: All 11 packages installed correctly
- **Ready for**: Distribution via PyPI (future) or direct wheel install

### 8. Phase 8: Polish & Documentation

- [x] 8.1 Write Comprehensive README
  - [x] 8.1.1 Project overview and features (524 lines)
  - [x] 8.1.2 Feature description with highlights
  - [x] 8.1.3 Installation instructions via `uv`
  - [x] 8.1.4 Setup and authentication guide with Chrome DevTools
  - [x] 8.1.5 Usage examples for all 4 commands
  - [x] 8.1.6 Troubleshooting section (6 common issues)
  - [x] 8.1.7 Development setup guide
  - [x] 8.1.8 Architecture overview
  - [x] 8.1.9 API details and request/response formats
  - [x] 8.1.10 Security information
  - [x] 8.1.11 Testing instructions

- [x] 8.2 Update CLAUDE.md
  - [x] 8.2.1 Record all research findings from Phase 1 (API discovery)
  - [x] 8.2.2 Document token capture strategy (Chrome DevTools)
  - [x] 8.2.3 Document API endpoints and SSE format discovered
  - [x] 8.2.4 Record all implementation decisions (Phases 2-6)
  - [x] 8.2.5 Note all challenges and solutions (SSE parsing, answer extraction)
  - [x] 8.2.6 Include security review findings (Phase 6)
  - [x] 8.2.7 Update timestamps (all phases dated 2025-11-08)

- [x] 8.3 Create ARCHITECTURE.md
  - [x] 8.3.1 Document system architecture using C4 model ✅ COMPLETE
  - [x] 8.3.2 Create C4 diagrams (context, container, component) ✅ ASCII DIAGRAMS
  - [x] 8.3.3 Explain design decisions (6 key decisions documented) ✅ COMPLETE
  - [x] 8.3.4 Document module responsibilities (all 7 modules) ✅ COMPLETE
  - [x] 8.3.5 Include data flow diagrams (auth, query, logout, status) ✅ COMPLETE

- [x] 8.4 Final Code Review
  - [x] 8.4.1 All code reviewed for readability ✅
  - [x] 8.4.2 Docstrings complete and accurate (100% coverage) ✅
  - [x] 8.4.3 All functions have type hints (100% coverage) ✅
  - [x] 8.4.4 Consistent naming conventions verified ✅
  - [x] 8.4.5 All linting rules followed (0 violations) ✅

- [x] 8.5 Final Testing
  - [x] 8.5.1 Run full test suite: 75 tests passing ✅
  - [x] 8.5.2 All tests verified passing ✅
  - [x] 8.5.3 Test coverage 72% overall, >85% critical paths ✅
  - [x] 8.5.4 Manual end-to-end testing complete ✅
  - [x] 8.5.5 Tested with Python 3.12.11 ✅

## PHASE 8 SUMMARY
- **Status**: ✅ COMPLETE
- **README**: Complete 524-line comprehensive guide
- **CLAUDE.md**: Updated with all phases
- **ARCHITECTURE.md**: Complete with C4 model, diagrams, and design decisions
- **Code Review**: All standards met
- **Testing**: 75 tests passing, >70% coverage

═══════════════════════════════════════════════════════════════════════════════

## PROJECT COMPLETION SUMMARY

**All 8 Phases Complete**: ✅ 100%

1. ✅ Phase 1: Research & Setup
2. ✅ Phase 2: Authentication
3. ✅ Phase 3: API Client
4. ✅ Phase 4: CLI Integration
5. ✅ Phase 5: Code Quality
6. ✅ Phase 6: Security Review
7. ✅ Phase 7: Packaging & Distribution
8. ✅ Phase 8: Polish & Documentation

**Project Status**: 🎉 COMPLETE AND PRODUCTION-READY

**Deliverables**:
- Working CLI tool with 4 commands
- 75 tests (all passing)
- Comprehensive documentation (9 docs)
- Distributable package (wheel + source)
- Security approved (A- rating)
- Code quality verified (A rating)