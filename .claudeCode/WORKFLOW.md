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

### 3. Phase 3: API Client

- [ ] 3.1 Implement HTTP Client
  - [ ] 3.1.1 Create `client.py` with requests-based HTTP client
  - [ ] 3.1.2 Configure authentication headers
  - [ ] 3.1.3 Implement error handling and retry logic
  - [ ] 3.1.4 Add input validation and sanitisation

- [ ] 3.2 Create Endpoint Abstractions
  - [ ] 3.2.1 Create `endpoints.py` with query submission wrapper
  - [ ] 3.2.2 Implement response parsing
  - [ ] 3.2.3 Extract answer text from full response
  - [ ] 3.2.4 Document API contract

- [ ] 3.3 Define Data Models
  - [ ] 3.3.1 Create request/response models in `models.py`
  - [ ] 3.3.2 Add type hints for all models
  - [ ] 3.3.3 Implement serialisation/deserialisation logic

- [ ] 3.4 Write API Tests
  - [ ] 3.4.1 Unit tests for HTTP client request formatting
  - [ ] 3.4.2 Unit tests for response parsing
  - [ ] 3.4.3 Unit tests for answer extraction
  - [ ] 3.4.4 Mock tests for API interactions

- [ ] 3.5 Test API Integration
  - [ ] 3.5.1 Integration tests with actual Perplexity queries
  - [ ] 3.5.2 Verify answer extraction accuracy
  - [ ] 3.5.3 Test error handling for invalid queries
  - [ ] 3.5.4 Test token refresh scenarios

### 4. Phase 4: CLI Integration

- [ ] 4.1 Implement Click Commands
  - [ ] 4.1.1 Implement `auth` command
  - [ ] 4.1.2 Implement `query` command with argument parsing
  - [ ] 4.1.3 Implement `logout` command
  - [ ] 4.1.4 Implement `status` command

- [ ] 4.2 Add Error Handling
  - [ ] 4.2.1 Implement user-friendly error messages
  - [ ] 4.2.2 Add missing token prompts
  - [ ] 4.2.3 Add network error handling
  - [ ] 4.2.4 Add API error handling

- [ ] 4.3 Test CLI Commands
  - [ ] 4.3.1 Unit tests for command parsing
  - [ ] 4.3.2 Unit tests for error paths
  - [ ] 4.3.3 Integration tests for full workflows
  - [ ] 4.3.4 Manual testing of all commands

- [ ] 4.4 Verify End-to-End Workflow
  - [ ] 4.4.1 Test complete auth → query → answer flow
  - [ ] 4.4.2 Test token persistence across invocations
  - [ ] 4.4.3 Test all error scenarios
  - [ ] 4.4.4 Test help and status commands

### 5. Phase 5: Linting & Code Quality

- [ ] 5.1 Configure Ruff
  - [ ] 5.1.1 Create `ruff.toml` or configure in `pyproject.toml`
  - [ ] 5.1.2 Set rules for code style and quality
  - [ ] 5.1.3 Configure formatting rules
  - [ ] 5.1.4 Set Python 3.12 as target version

- [ ] 5.2 Run Initial Linting
  - [ ] 5.2.1 Run `uv run ruff check .` to identify violations
  - [ ] 5.2.2 Run `uv run ruff format .` to auto-fix formatting issues
  - [ ] 5.2.3 Document any manual fixes needed

- [ ] 5.3 Resolve Linting Violations
  - [ ] 5.3.1 Fix all remaining linting issues
  - [ ] 5.3.2 Ensure all code passes `uv run ruff check .`
  - [ ] 5.3.3 Verify formatting with `uv run ruff format --check .`

- [ ] 5.4 Set Up Code Quality Standards
  - [ ] 5.4.1 Document linting rules in `.claudeCode/CLAUDE.md`
  - [ ] 5.4.2 Create pre-commit hooks (optional) using `uv`
  - [ ] 5.4.3 Ensure all future code follows standards

### 6. Phase 6: Security Review

- [ ] 6.1 Manual Code Review
  - [ ] 6.1.1 Review token storage and handling
    - [ ] 6.1.1.1 Ensure no plain-text secrets in code
    - [ ] 6.1.1.2 Verify file permissions are correctly set
    - [ ] 6.1.1.3 Check for credential leaks in logs
  - [ ] 6.1.2 Review input validation and sanitisation
    - [ ] 6.1.2.1 Check for injection attack vulnerabilities
    - [ ] 6.1.2.2 Validate all user-supplied data
    - [ ] 6.1.2.3 Sanitise output to prevent XSS
  - [ ] 6.1.3 Review HTTP client security
    - [ ] 6.1.3.1 Verify SSL/TLS certificate validation
    - [ ] 6.1.3.2 Check for secure defaults
    - [ ] 6.1.3.3 Review error handling for sensitive data
  - [ ] 6.1.4 Review CLI command parsing
    - [ ] 6.1.4.1 Check for command injection vulnerabilities
    - [ ] 6.1.4.2 Validate all CLI arguments

- [ ] 6.2 Dependency Vulnerability Scanning
  - [ ] 6.2.1 Review all dependencies in `uv.lock` for known vulnerabilities
  - [ ] 6.2.2 Check dependency sources and licences
  - [ ] 6.2.3 Document any identified issues

- [ ] 6.3 Sensitive Information Handling
  - [ ] 6.3.1 Audit all code for logging/printing of tokens
  - [ ] 6.3.2 Ensure error messages don't leak sensitive data
  - [ ] 6.3.3 Review exception handling for information disclosure
  - [ ] 6.3.4 Check for hard-coded secrets

- [ ] 6.4 Fix Security Issues
  - [ ] 6.4.1 Address all identified vulnerabilities
  - [ ] 6.4.2 Add additional input validation if needed
  - [ ] 6.4.3 Improve error handling for sensitive operations
  - [ ] 6.4.4 Document security measures

- [ ] 6.5 Create Security Test Suite
  - [ ] 6.5.1 Write tests for token encryption/storage
  - [ ] 6.5.2 Write tests for input validation
  - [ ] 6.5.3 Write tests for HTTP client security
  - [ ] 6.5.4 Write tests for sensitive data handling

- [ ] 6.6 Document Security Practices
  - [ ] 6.6.1 Update `.claudeCode/CLAUDE.md` with security findings
  - [ ] 6.6.2 Document all security measures implemented
  - [ ] 6.6.3 Create security guidelines for future development

### 7. Phase 7: Packaging & Distribution

- [ ] 7.1 Verify Packaging Configuration
  - [ ] 7.1.1 Review `pyproject.toml` for completeness
  - [ ] 7.1.2 Verify entry point configuration
  - [ ] 7.1.3 Check version management setup
  - [ ] 7.1.4 Ensure Python 3.12 requirement is set

- [ ] 7.2 Test Local Installation
  - [ ] 7.2.1 Test installation via `uv pip install -e .`
  - [ ] 7.2.2 Verify `perplexity` command is available
  - [ ] 7.2.3 Test each CLI command after installation
  - [ ] 7.2.4 Test with fresh virtual environment

- [ ] 7.3 Build Distribution Artefacts
  - [ ] 7.3.1 Generate wheel using `uv build`
  - [ ] 7.3.2 Generate source distribution using `uv build`
  - [ ] 7.3.3 Verify artefacts in `dist/` directory
  - [ ] 7.3.4 Check artefact contents for correctness

- [ ] 7.4 Test Distribution Installation
  - [ ] 7.4.1 Create fresh virtual environment
  - [ ] 7.4.2 Install from built wheel
  - [ ] 7.4.3 Test `perplexity` command functionality
  - [ ] 7.4.4 Verify all dependencies are correctly installed

- [ ] 7.5 Update Installation Documentation
  - [ ] 7.5.1 Document installation via `uv pip install .`
  - [ ] 7.5.2 Document development setup with `uv`
  - [ ] 7.5.3 Include Python 3.12 requirement notice
  - [ ] 7.5.4 Provide troubleshooting guide

### 8. Phase 8: Polish & Documentation

- [ ] 8.1 Write Comprehensive README
  - [ ] 8.1.1 Project overview
  - [ ] 8.1.2 Feature description
  - [ ] 8.1.3 Installation instructions via `uv`
  - [ ] 8.1.4 Setup and authentication guide
  - [ ] 8.1.5 Usage examples for all commands
  - [ ] 8.1.6 Troubleshooting section

- [ ] 8.2 Update CLAUDE.md
  - [ ] 8.2.1 Record all research findings from Phase 1
  - [ ] 8.2.2 Document token capture strategy chosen and rationale
  - [ ] 8.2.3 Document API endpoints and formats discovered
  - [ ] 8.2.4 Record all implementation decisions and trade-offs
  - [ ] 8.2.5 Note any challenges encountered and solutions
  - [ ] 8.2.6 Include security review findings and fixes
  - [ ] 8.2.7 Update timestamps and change log

- [ ] 8.3 Create ARCHITECTURE.md
  - [ ] 8.3.1 Document system architecture using C4 model
  - [ ] 8.3.2 Create C4 diagrams (context, container, component)
  - [ ] 8.3.3 Explain design decisions
  - [ ] 8.3.4 Document module responsibilities
  - [ ] 8.3.5 Include data flow diagrams for auth and query flows

- [ ] 8.4 Final Code Review
  - [ ] 8.4.1 Review all code for readability
  - [ ] 8.4.2 Ensure docstrings are complete and accurate
  - [ ] 8.4.3 Verify all functions have type hints
  - [ ] 8.4.4 Check for consistent naming conventions
  - [ ] 8.4.5 Ensure all linting rules are followed

- [ ] 8.5 Final Testing
  - [ ] 8.5.1 Run full test suite via `uv run pytest`
  - [ ] 8.5.2 Verify all tests pass
  - [ ] 8.5.3 Check test coverage (aim for >80% on critical paths)
  - [ ] 8.5.4 Perform manual end-to-end testing
  - [ ] 8.5.5 Test on clean Python 3.12 installation