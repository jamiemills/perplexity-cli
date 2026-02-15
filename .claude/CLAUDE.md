# Perplexity CLI - AI Development Log

**Project:** perplexity-cli
**Status:** Active Development (branch: `deep-research`)
**Last Updated:** 2026-02-15 (v0.4.8: thread cache date-range fix, curl_cffi migration, Python 3.13 support)

## Project Overview

`perplexity-cli` is a command-line interface for querying Perplexity.ai with persistent authentication. It provides a robust, user-friendly interface for interacting with the Perplexity API from the terminal.

## PyPI Package

This project is published to PyPI as [`pxcli`](https://pypi.org/project/pxcli/).

### Installation Methods

**For users:**
```bash
pip install pxcli
# or
uvx pxcli
```

Note: The command can be run as either `pxcli` or `perplexity-cli`.

**For development:**
```bash
git clone https://github.com/jamiemills/perplexity-cli.git
cd perplexity-cli
uv pip install -e ".[dev]"
```

### Version Management

- **Source of truth:** `pyproject.toml` (field: `version`)
- **Current version:** 0.4.8
- **Versioning scheme:** Semantic versioning (MAJOR.MINOR.PATCH)
- **Synchronisation:** `src/perplexity_cli/__init__.py` must always match `pyproject.toml`
- **Runtime version:** Use `from importlib.metadata import version; version("pxcli")`

### Publishing Workflow

Publishing is **fully automated** via GitHub Actions:

1. Update version in `pyproject.toml`
2. Commit changes
3. Create and push git tag: `git tag -a vX.Y.Z -m "Release X.Y.Z" && git push origin vX.Y.Z`
4. GitHub Actions automatically builds and publishes to PyPI

**Workflow file:** `.github/workflows/publish-to-pypi.yml`

For detailed instructions, see [.claude/PUBLISHING.md](.claude/PUBLISHING.md).

## Architecture

### Core Components

1. **CLI Module** (`cli.py`) - Click-based command-line interface
2. **Query Module** (`query.py`) - Perplexity API interaction
3. **Authentication** (`auth.py`) - Token management and browser-based authentication
4. **Storage** (`storage.py`) - Secure local credential storage

### Key Features

- Persistent authentication with secure token storage
- Optional cookie storage for Cloudflare bypass (disabled by default)
- Deep research mode for comprehensive multi-step research queries
- Configurable debug mode via config file
- Thread-based conversation management
- Export functionality (JSON, Markdown)
- Rich terminal output
- Comprehensive error handling
- Real-time streaming support

## Development Approach

### Test-Driven Development

All features are developed using TDD:
1. Write tests first
2. Implement minimum code to pass
3. Refactor for clarity

Test coverage includes:
- Unit tests
- Integration tests
- Security tests
- Mock-based testing for external dependencies

### Code Quality

- **Linting:** ruff
- **Type checking:** mypy
- **Formatting:** ruff format
- **Test runner:** pytest

### Standards

- Python 3.12+ required
- PEP 8 compliance via ruff
- Type hints throughout codebase
- Comprehensive docstrings

## Repository Structure

```
perplexity-cli/
├── src/
│   └── perplexity_cli/
│       ├── __init__.py
│       ├── cli.py
│       ├── py.typed                # PEP 561 type hint marker
│       ├── api/
│       │   ├── __init__.py
│       │   ├── client.py           # HTTP client with dynamic timeouts
│       │   ├── endpoints.py        # API endpoint handlers
│       │   └── models.py           # Pydantic API models (QueryParams, Answer, etc.)
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── models.py           # Pydantic auth models (TokenFormat, CookieData)
│       │   ├── oauth_handler.py    # OAuth browser authentication
│       │   ├── token_manager.py    # Encrypted token storage
│       │   └── utils.py            # Shared auth utilities (load_or_prompt_token)
│       ├── config/
│       │   ├── __init__.py         # Pydantic model exports
│       │   ├── models.py           # URLConfig, RateLimitConfig, FeatureConfig
│       │   └── urls.json           # API endpoint configuration
│       ├── formatting/
│       │   ├── __init__.py
│       │   ├── base.py             # Base Formatter with strip_citations()
│       │   ├── json.py
│       │   ├── markdown.py
│       │   ├── plain.py
│       │   ├── registry.py
│       │   └── rich.py
│       ├── threads/
│       │   ├── __init__.py
│       │   ├── cache_manager.py    # Encrypted thread cache
│       │   ├── date_parser.py      # Date range parsing
│       │   ├── exporter.py         # Thread export (JSON, Markdown)
│       │   ├── models.py           # Pydantic cache models
│       │   ├── scraper.py          # Thread scraping
│       │   └── utils.py            # Cache-to-ThreadRecord conversion
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── config.py           # Configuration file management
│       │   ├── encryption.py       # PBKDF2-HMAC encryption with SHA-256 fallback
│       │   ├── file_permissions.py # Shared file permission verification
│       │   ├── http_errors.py      # Consolidated HTTP error handling
│       │   ├── logging.py          # Structured logging
│       │   ├── rate_limiter.py     # Token bucket rate limiter
│       │   ├── rate_limiter_models.py  # Pydantic rate limiter models
│       │   ├── retry.py            # Retry logic with exponential backoff
│       │   ├── style_manager.py    # User style preferences
│       │   └── version.py          # Version utilities
│       └── resources/              # Bundled resources (skill.md)
├── tests/
│   ├── conftest.py
│   ├── test_api_client.py
│   ├── test_api_integration.py
│   ├── test_auth.py
│   ├── test_auth_integration.py
│   ├── test_cli.py
│   ├── test_cli_composition.py         # CLI flag combination tests
│   ├── test_config_edge_cases.py       # Config corruption, env overrides
│   ├── test_config_improvements.py
│   ├── test_date_parser.py             # Date range parsing tests
│   ├── test_deep_research_edge_cases.py # Deep research malformed blocks, timeouts
│   ├── test_encryption.py
│   ├── test_endpoints.py
│   ├── test_formatters.py
│   ├── test_logging.py
│   ├── test_models.py
│   ├── test_pydantic_models.py
│   ├── test_rate_limiter.py            # Rate limiter state and edge cases
│   ├── test_retry.py
│   ├── test_style_manager.py
│   ├── test_thread_cache.py
│   ├── test_thread_exporter.py         # Thread export edge cases
│   └── test_version.py
├── .github/
│   └── workflows/
│       └── publish-to-pypi.yml
├── .claude/
│   ├── CLAUDE.md (this file)
│   ├── PUBLISHING.md
│   └── plans/
├── pyproject.toml
└── README.md
```

## Recent Changes

### Version 0.4.8: Thread cache date-range fix, curl_cffi migration, Python 3.13 (2026-02-15)

**Thread cache restricted to requested date range.** Previously, `save_cache()` was called before the date-range filter, so the cache accumulated all threads ever fetched regardless of the user's `--from-date` / `--to-date` arguments. The filter now runs before `save_cache()`, so only threads within the requested range are persisted. Cache metadata (`oldest_thread_date`, `newest_thread_date`) correctly reflects the narrower range, and `requires_fresh_data()` triggers a fresh fetch when a subsequent request falls outside the cached range.

**Thread scraper migrated to curl_cffi.** Both HTTP paths (query via `api/client.py` and thread export via `threads/scraper.py`) now use `curl_cffi` with Chrome TLS fingerprint impersonation, bypassing Cloudflare's fingerprint-bound bot protection.

**Python 3.13 support.** With both HTTP paths using curl_cffi, the Python version constraint has been relaxed from `>=3.12,<3.13` to `>=3.12`.

**Files modified:**
- `src/perplexity_cli/threads/scraper.py` - Date-range filter moved before `save_cache()`; curl_cffi migration
- `src/perplexity_cli/cli.py` - Removed `httpx` import from `export_threads`; simplified exception catch
- `pyproject.toml` - Version bump to 0.4.8; `requires-python` relaxed to `>=3.12`; Python 3.13 classifier
- `src/perplexity_cli/__init__.py` - Version bump to 0.4.8
- `README.md` - Updated Python version, caching description, dependency list
- `tests/test_scraper_cache_filter.py` (new) - 4 tests verifying cache receives only date-filtered threads

**Test results:** 414 passed, 8 skipped.

### Thread scraper curl_cffi migration and Python 3.13 support (2026-02-15)

Migrated the thread scraper (`threads/scraper.py`) from `httpx.AsyncClient` to `curl_cffi.requests.AsyncSession` to bypass Cloudflare's TLS fingerprint-bound bot protection on the thread export path. This is the same fix previously applied to the query path (`api/client.py`). With both HTTP paths now using curl_cffi, the Python version constraint has been relaxed from `>=3.12,<3.13` to `>=3.12`, enabling Python 3.13 support.

**Changes:**

- **`src/perplexity_cli/threads/scraper.py`:**
  - Replaced `import httpx` with `from curl_cffi.requests import AsyncSession` and `from curl_cffi.requests.exceptions import RequestException`.
  - Added imports for `PerplexityHTTPStatusError`, `SimpleRequest`, `SimpleResponse` from `utils/exceptions.py`.
  - Replaced `httpx.AsyncClient(timeout=30.0)` with `AsyncSession(impersonate="chrome", timeout=30)`.
  - Cookies now passed as a dict via the `cookies` parameter on `post()` instead of serialised into a `Cookie` header string.
  - Removed manual `User-Agent` header (curl_cffi sets this automatically from impersonation profile).
  - Replaced `response.raise_for_status()` with `response.ok` check and `_raise_http_status_error()` static method (same pattern as `api/client.py`).
  - Exception handling updated: catches `PerplexityHTTPStatusError` instead of `httpx.HTTPStatusError`, and catches `RequestException` (curl_cffi) converting to `RuntimeError`.
  - Docstrings updated: `httpx.HTTPStatusError` references changed to `PerplexityHTTPStatusError`.

- **`src/perplexity_cli/cli.py`:**
  - Removed `import httpx` from `export_threads` function.
  - Simplified exception catch from `except (PerplexityHTTPStatusError, httpx.HTTPStatusError)` to `except PerplexityHTTPStatusError`.

- **`pyproject.toml`:**
  - Changed `requires-python` from `">=3.12,<3.13"` to `">=3.12"`.
  - Added `"Programming Language :: Python :: 3.13"` classifier.

**httpx retained as dependency:** `httpx>=0.25` remains in `pyproject.toml`. It is used in `tests/test_exceptions.py` for type verification, and may be needed by other development tooling.

**Test results:** 417 passed, 1 failed (pre-existing `test_manual_auth.py` failure requiring running Chrome instance).

### Version 0.4.6: Hide deep research, curl_cffi migration (2026-02-15)

**Deep research CLI flag hidden.** The `--deep-research` flag has been removed from the CLI, README, and streaming module. The underlying API support (`search_implementation_mode` in models, endpoints, client timeout logic) remains in place but is not exposed to users. The feature was not proven to work reliably. Tests referencing the CLI flag have been removed; API model tests for `search_implementation_mode` remain.

**Files modified:**
- `src/perplexity_cli/cli.py` - Removed `--deep-research` option, docstring references, and `search_mode` passthrough
- `src/perplexity_cli/api/streaming.py` - Removed `deep_research` parameter and plan block progress display
- `README.md` - Removed deep research from features, usage examples, and command documentation
- `tests/test_cli_composition.py` - Removed deep research test classes (TestDeepResearchWithStream, TestDeepResearchWithFormatJson, related flag tests)
- `tests/test_cli.py` - Removed `search_implementation_mode="standard"` assertion (no longer passed)
- `pyproject.toml` / `__init__.py` - Version bump to 0.4.6

### curl_cffi TLS Fingerprint Bypass (2026-02-15)

Replaced httpx with curl_cffi in the SSEClient (the query path) to bypass Cloudflare's TLS fingerprint-bound bot protection. Cloudflare now binds the `cf_clearance` cookie to the TLS fingerprint of the client that solved the JavaScript challenge. Since httpx uses Python's default TLS stack (which has a distinct fingerprint from Chrome), Cloudflare rejects requests even with valid cookies. `curl_cffi` solves this by impersonating Chrome's TLS fingerprint.

**Branch:** `deep-research`
**Scope:** SSEClient only (at time of this change). The thread scraper was subsequently migrated to curl_cffi as well (see above).

**Changes:**

- **`pyproject.toml`:** Added `curl-cffi>=0.14.0` to dependencies. `httpx>=0.25` retained (used by thread scraper and for exception types).
- **`src/perplexity_cli/api/client.py`:**
  - Replaced `httpx.Client` with `curl_cffi.requests.Session(impersonate='chrome')` for Chrome TLS fingerprint impersonation.
  - Cookies now passed via the `cookies` parameter on requests (native curl_cffi handling) rather than serialised into a `Cookie` header string.
  - Removed manual `User-Agent` header (curl_cffi sets this automatically from impersonation).
  - Added `X-CSRFToken` header extraction from cookies when `csrftoken` cookie is present.
  - Added `_raise_http_status_error()` static method to convert curl_cffi error responses into `httpx.HTTPStatusError` with valid `.request` and `.response` attributes, so downstream error handlers (cli.py, http_errors.py, retry.py) require no changes.
  - Added `curl_cffi.requests.exceptions.RequestException` catch that converts to `httpx.RequestError`.
  - `_parse_sse_stream()` now handles bytes from `iter_lines()` (curl_cffi yields bytes; httpx yielded strings).
  - Removed `from perplexity_cli.utils.version import get_version` (no longer needed without manual User-Agent).
- **`tests/test_api_client.py`:**
  - Updated header tests: no `User-Agent` assertion; added `X-CSRFToken` tests.
  - SSE parsing tests now use bytes input (matching curl_cffi behaviour); added string input backward-compatibility test.
  - Streaming POST tests mock `response.ok` attribute instead of `raise_for_status()` side effects.
  - Added `test_stream_post_403_error_retries` and `test_raise_http_status_error` tests.
  - Lazy instantiation test checks for `curl_cffi.requests.Session` instead of `httpx.Client`.
  - Test count: 386 test functions (up from 375).

**Files NOT modified (at time of this change):**
- `src/perplexity_cli/api/endpoints.py` - Calls `self.client.stream_post()` (interface unchanged)
- `src/perplexity_cli/cli.py` - Catches `httpx.HTTPStatusError`/`RequestError` (still valid via conversion layer; subsequently updated)
- `src/perplexity_cli/utils/http_errors.py` - Handles `httpx.HTTPStatusError` (still valid)
- `src/perplexity_cli/utils/retry.py` - Uses httpx exception types (still valid)
- `src/perplexity_cli/threads/scraper.py` - Used `httpx.AsyncClient` independently (subsequently migrated to curl_cffi)

### Comprehensive Enhancement (2026-02-13)

A three-phase enhancement programme addressing security, code quality, DRY violations, Pydantic integration, and test coverage across the entire codebase.

**Branch:** `deep-research`
**Test count:** 375 test functions across 23 test files (up from 243)

#### Phase 1: Foundation

Security, structural, and type system improvements.

- **Security (PBKDF2 encryption):** Migrated key derivation from SHA-256 to PBKDF2-HMAC with 100,000 iterations. Backward-compatible fallback to SHA-256 for decrypting legacy tokens.
- **Security (UTF-8 encoding):** Added explicit `encoding="utf-8"` to all `open()` calls across `token_manager.py` and `cache_manager.py` (4 locations).
- **Security (MAX_STYLE_LENGTH):** Enforced 10,000 character limit in `save_style()` to prevent unbounded input.
- **Security (TimeoutError):** Added dedicated `TimeoutError` handler in the auth command with troubleshooting guidance.
- **Structure (config/__init__.py):** Created missing package init file exporting `URLConfig`, `RateLimitConfig`, `FeatureConfig`.
- **Structure (py.typed):** Created PEP 561 marker file for type checker discovery.
- **Types (missing annotations):** Added `Formatter` type to CLI formatter parameter, `Callable[[int, int], None] | None` to `progress_callback`, `dict[str, int | float]` return type to `get_stats()`.

#### Phase 2: Consolidation

DRY violation elimination, Pydantic integration, and style consistency.

- **DRY (http_errors):** Extracted `handle_http_error()` and `handle_network_error()` to `utils/http_errors.py`, consolidating ~50 lines of duplicate HTTP 401/403/429 handling from `query()` and `_stream_query_response()`.
- **DRY (auth/utils):** Extracted `load_or_prompt_token()` to `auth/utils.py`, consolidating the repeated token-load-or-prompt pattern.
- **DRY (file_permissions):** Extracted `verify_secure_permissions()` to `utils/file_permissions.py`, unifying permission validation from `TokenManager` and `ThreadCacheManager` (~30 lines eliminated).
- **DRY (strip_citations):** Added `Formatter.strip_citations()` static method to `formatting/base.py`, replacing the duplicated `r"\[\d+\]"` regex across plain, markdown, JSON, and rich formatters (5+ locations).
- **DRY (cache conversion):** Extracted `convert_cache_dicts_to_thread_records()` to `threads/utils.py` from the scraper module.
- **Pydantic integration:** Extended Pydantic model usage across configuration, rate limiter, and thread modules. Config `__init__.py` now properly exports validated models.
- **Style consistency:** British English standardisation in docstrings, removal of emoji from user-facing messages, format parameter renamed where it shadowed the built-in.

#### Phase 3: Enhancement

Test coverage expansion and CI/CD improvements.

- **New test files (6):**
  - `test_rate_limiter.py` - 14 tests for token bucket state, edge cases, and configuration
  - `test_date_parser.py` - 29 tests for date range parsing, relative dates, and error handling
  - `test_thread_exporter.py` - 13 tests for thread export edge cases and format validation
  - `test_config_edge_cases.py` - 27 tests for corrupted files, missing configs, environment variable overrides
  - `test_cli_composition.py` - 12 tests for CLI flag combinations and interaction
  - `test_deep_research_edge_cases.py` - 28 tests for malformed blocks, timeouts, and progress parsing
- **Test count:** 375 test functions (up from 243 at baseline), across 23 test files

**Files Created:**
- `src/perplexity_cli/auth/utils.py`
- `src/perplexity_cli/config/__init__.py`
- `src/perplexity_cli/py.typed`
- `src/perplexity_cli/utils/http_errors.py`
- `src/perplexity_cli/utils/file_permissions.py`
- `src/perplexity_cli/threads/utils.py`
- `tests/test_rate_limiter.py`
- `tests/test_date_parser.py`
- `tests/test_thread_exporter.py`
- `tests/test_config_edge_cases.py`
- `tests/test_cli_composition.py`
- `tests/test_deep_research_edge_cases.py`

**Files Modified:**
- `src/perplexity_cli/auth/token_manager.py` - UTF-8 encoding, permission utility
- `src/perplexity_cli/threads/cache_manager.py` - UTF-8 encoding, permission utility
- `src/perplexity_cli/utils/encryption.py` - PBKDF2-HMAC with SHA-256 fallback
- `src/perplexity_cli/utils/style_manager.py` - MAX_STYLE_LENGTH enforcement
- `src/perplexity_cli/utils/rate_limiter.py` - Type annotation improvement
- `src/perplexity_cli/threads/scraper.py` - Type annotations, cache conversion extraction
- `src/perplexity_cli/cli.py` - TimeoutError handler, type annotations, HTTP error utility, auth utility
- `src/perplexity_cli/formatting/base.py` - strip_citations() static method
- `src/perplexity_cli/formatting/markdown.py` - Use strip_citations()
- `src/perplexity_cli/formatting/plain.py` - Use strip_citations()
- `src/perplexity_cli/formatting/json.py` - Use strip_citations()
- `src/perplexity_cli/formatting/rich.py` - Use strip_citations()

### Deep Research Feature (2026-02-09)

Implemented support for Perplexity's deep research mode enabling comprehensive multi-step research queries.

**Implementation Details:**

1. **API Layer** (`api/models.py`):
   - Added `search_implementation_mode` field to `QueryParams` (SINGLE SOURCE OF TRUTH)
   - Supports "standard" (default, ~30s) and "multi_step" (deep research, 2-4 min)
   - Field validator ensures only valid modes are accepted

2. **Endpoint Handler** (`api/endpoints.py`):
   - Updated `submit_query()` to accept `search_implementation_mode` parameter
   - Updated `get_complete_answer()` to pass through search mode
   - Added `_extract_plan_block_info()` method for parsing research progress blocks

3. **HTTP Client** (`api/client.py`):
   - Dynamic timeout adjustment based on search mode
   - 60 seconds for standard queries, 360 seconds for deep research
   - Automatic timeout calculation in `stream_post()` method

4. **CLI Integration** (`cli.py`):
   - Added `--deep-research` flag to query command
   - Displays "Deep research in progress..." message with progress updates
   - Passes search mode through to API layer
   - Works with both streaming and batch modes

5. **Testing**:
   - Added 6 comprehensive tests for `QueryParams.search_implementation_mode`
   - Tests validation, serialization, and integration
   - Updated existing CLI tests to account for new parameter
   - All tests passing (243 at time of implementation)

**Files Modified:**
- `src/perplexity_cli/api/models.py` - Added search_implementation_mode field
- `src/perplexity_cli/api/endpoints.py` - Plan block parsing and parameter handling
- `src/perplexity_cli/api/client.py` - Dynamic timeout adjustment
- `src/perplexity_cli/cli.py` - CLI flag and progress display
- `tests/test_pydantic_models.py` - Validation tests for new field
- `tests/test_cli.py` - Updated test assertions
- `README.md` - Feature documentation and examples
- `.claude/CLAUDE.md` - Project documentation

**Usage Example:**
```bash
# Standard quick query (30 seconds)
pxcli query "What is Python?"

# Deep research comprehensive query (2-4 minutes)
pxcli query --deep-research "Explain machine learning algorithms"

# Combine with other options
pxcli query --deep-research --stream --format markdown "Tell me about Kubernetes"
```

### Version 0.4.3 (2026-01-08)

- Restricted to Python 3.12 only (Python 3.13 blocked by Cloudflare dependency issues)
- Version bump with Python compatibility constraint

### Version 0.4.2 (2026-01-08)

- Fixed intermittent HTTP 403 errors by retrying Cloudflare blocks with exponential backoff

### Version 0.4.1 (2026-01-07)

- Added configuration file system (`~/.config/perplexity-cli/config.json`)
- Cookie storage now configurable (disabled by default for privacy)
- Debug mode configurable via config file
- Added `set-config` and `show-config` commands
- Environment variable overrides for all config options
- Improved privacy: cookies only saved when explicitly enabled

### Version 0.4.0 (2026-01-07)

- Added cookie storage to bypass Cloudflare bot detection
- Store and send browser cookies alongside JWT token
- Includes Cloudflare cookies (cf_clearance, __cf_bm, __cflb)
- Token storage format upgraded to v2 with encrypted cookies
- Full backward compatibility with v1 tokens

### Version 0.3.0 (2026-01-06)

- Configured for PyPI publishing
- Added GitHub Actions CI/CD workflow
- Updated package metadata (author, licence, classifiers)
- Synchronised version across all files
- Added comprehensive documentation

### Previous Versions

- 0.2.0 - Thread caching and export features
- 0.1.0 - Initial release with core functionality

## Pydantic Integration (2026-01-15)

### Overview
Complete Pydantic v2 integration providing runtime type validation, automatic serialization, and clear error messages throughout the codebase.

**Branch**: Originally `feature/pydantic-integration`, now merged into `deep-research`
**Status**: Complete and integrated (375 test functions across the full suite)

### Architecture

#### Configuration Models (`config/models.py`)
```python
class URLConfig(BaseModel):
    base_url: str = "https://www.perplexity.ai"
    query_endpoint: str = "/api/pplx.generateStream"
    # Validators: non-empty strings

class RateLimitConfig(BaseModel):
    enabled: bool = True
    requests_per_period: int = 20  # >= 1
    period_seconds: float = 60.0  # > 0
    # Validators: range constraints

class FeatureConfig(BaseModel):
    save_cookies: bool = False
    debug_mode: bool = False
```

**Usage**:
- `get_urls()` → returns `URLConfig` (not dict)
- `get_rate_limit_config()` → returns `RateLimitConfig`
- `get_feature_config()` → returns `FeatureConfig`
- Access: `config.base_url` (not `config["base_url"]`)

#### API Models (`api/models.py`)
All dataclasses converted to Pydantic BaseModel:
- `QueryParams`: 40+ validated fields with defaults
- `QueryRequest`: Nested QueryParams validation
- `WebResult`: Search results with optional snippet/timestamp
- `Block`: SSE response blocks
- `SSEMessage`: Complex nested streaming messages
- `Answer`: Final answer with references list

**Benefits**:
- Automatic JSON serialization: `model.model_dump()`
- From dict: `Model.from_dict(data)` or `Model.model_validate(data)`
- Type validation at API boundaries

#### Authentication Models (`auth/models.py`)
Ready for integration (not yet used in runtime):
- `TokenFormat`: Token file structure (v1/v2 support)
- `CookieData`: Browser cookie validation
- `TokenMetadata`: Token age and encryption info

#### Cache Models (`threads/models.py`)
Ready for integration (not yet used in runtime):
- `CacheFormat`: Encrypted cache file wrapper
- `CacheMetadata`: Date coverage and sync tracking
- `CacheContent`: Decrypted content with thread validation

#### Rate Limiter Models (`utils/rate_limiter_models.py`)
Ready for integration (not yet used in runtime):
- `RateLimiterConfig`: Configuration validation
- `RateLimiterState`: Token bucket state
- `RateLimiterStats`: Statistics with computed averages

### Testing
**Test Suite**: `tests/test_pydantic_models.py`
- 34 comprehensive validation tests
- Tests for field validators, bounds, edge cases, deep research mode
- All passing

**Total Test Count**: 375 test functions across 23 test files

### Migration Notes
**What Changed**:
- Config getters now return Pydantic models
- API models use Pydantic instead of dataclasses
- Test assertions use model properties (`.field` not `["field"]`)

**Backward Compatibility**:
- All file formats unchanged (JSON structure same)
- Token v2 format compatible
- Cache format compatible
- No breaking changes to public APIs

### Future Integration Opportunities
The auth, cache, and rate limiter models are created and tested but not yet integrated into runtime code. To use them:

1. Update `TokenManager.save_token()` → `TokenFormat.model_dump_json()`
2. Update `TokenManager.load_token()` → `TokenFormat.model_validate_json()`
3. Update `CacheManager` similarly with `CacheFormat`/`CacheContent`
4. Update `RateLimiter` to use `RateLimiterState` for state management

## Dependencies

### Production Dependencies

- click>=8.0 - CLI framework
- cryptography>=41.0 - Secure token storage
- curl-cffi>=0.14.0 - HTTP client with Chrome TLS fingerprint impersonation (SSE query path)
- httpx>=0.25 - HTTP client (thread scraper, exception types)
- websockets>=12.0 - WebSocket support
- rich>=13.0 - Terminal formatting
- tenacity>=8.0 - Retry logic
- python-dateutil>=2.8.0 - Date/time handling
- pydantic>=2.0 - Data validation and serialization (added 2026-01-15)

### Development Dependencies

- pytest>=7.0 - Test framework
- pytest-mock>=3.0 - Mocking support
- pytest-cov>=7.0 - Coverage reporting
- pytest-asyncio>=1.2.0 - Async test support
- ruff>=0.1 - Linting and formatting
- mypy>=1.0 - Type checking

## Testing

Run tests locally:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=perplexity_cli
```

Run specific test types:
```bash
pytest -m integration  # Integration tests only
pytest -m security     # Security tests only
```

## CI/CD

### GitHub Actions Workflow

Triggered on pushing tags matching `v*` pattern (e.g., `v0.3.0`):

1. Checkout code
2. Set up Python 3.12
3. Install dependencies
4. Format code (ruff format)
5. Check linting (ruff check)
6. Run tests (pytest)
7. Build distributions (uv build)
8. Publish to PyPI (twine)
9. Create GitHub Release

### Prerequisites

- `PYPI_API_TOKEN` configured in GitHub Secrets
- All tests passing
- Version bumped in `pyproject.toml`

## Security

- API tokens encrypted using PBKDF2-HMAC key derivation (100,000 iterations) via `cryptography`
- Backward-compatible fallback to SHA-256 for legacy tokens
- Explicit UTF-8 encoding on all file operations
- MAX_STYLE_LENGTH enforcement prevents unbounded input
- Never commit secrets or credentials
- PyPI token stored as GitHub Secret
- Token rotation recommended annually

## Future Development

Planned features:
- Interactive mode improvements
- Additional export formats
- Plugin system
- Streaming extraction to dedicated `api/streaming.py` module (reduce `cli.py` complexity)

## Support

- Repository: https://github.com/jamiemills/perplexity-cli
- Issues: https://github.com/jamiemills/perplexity-cli/issues
- PyPI: https://pypi.org/project/perplexity-cli/

## Licence

MIT Licence - See LICENCE file for details

## Author

Jamie Mills <jamie.mills@gmail.com>
