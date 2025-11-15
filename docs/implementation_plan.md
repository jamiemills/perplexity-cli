# Implementation Plan: Library/Threads Functionality

## Overview

Based on comprehensive research using Chrome DevTools Protocol and API endpoint discovery, this plan outlines the implementation of library/threads functionality for the Perplexity CLI.

**Status Tracking**: This plan uses checkboxes `[ ]` to track progress. Checkboxes will be updated as work is completed.

## Progress Summary

**Total Steps**: 66 steps across 4 priorities

### Priority 1: Core Functionality (22 steps)
- Phase 1.1: Data Models (4 steps)
- Phase 1.2: Library API Methods (5 steps)
- Phase 1.3: Query Methods (3 steps)
- Phase 2.1: Threads List Command (5 steps)
- Phase 2.3: Follow-up Command (5 steps)

**Status**: 18/22 completed (82%)

### Priority 2: Enhanced Features (12 steps)
- Phase 3.1: Thread Context Storage (5 steps)
- Phase 3.2: Auto-save Context (3 steps)
- Phase 2.2: Thread Show Command (4 steps)

**Status**: 0/12 completed

### Priority 3: Advanced Features (14 steps)
- Phase 2.4: Interactive Continue (2 steps)
- Phase 4.1: Enhanced Search (2 steps)
- Phase 4.2: Thread Export (6 steps)
- Phase 4.3: Thread Delete (4 steps)

**Status**: 0/14 completed

### Priority 4: Testing & Documentation (18 steps)
- Phase 5.1: Unit Tests (5 steps)
- Phase 5.2: Integration Tests (5 steps)
- Phase 5.3: Documentation (8 steps)

**Status**: 0/18 completed

**Overall Progress**: 0/66 steps completed (0%)

## Research Summary

### Discovered API Endpoints

1. **List Threads**
   - Endpoint: `POST /rest/thread/list_ask_threads?version=2.18&source=default`
   - Request: `{"limit":20,"ascending":false,"offset":0,"search_term":""}`
   - Response: Array of thread objects

2. **List Collections**
   - Endpoint: `GET /rest/collections/list_user_collections?limit=30&offset=0&version=2.18&source=default`
   - Response: Array of collection objects

### Thread Context Fields

- `slug` - Unique thread identifier (e.g., "what-is-python-HDn1I22.QKCoDctO58P2UA")
- `frontend_context_uuid` - Links queries in same conversation (reuse for follow-ups)
- `context_uuid` - Backend context UUID
- `read_write_token` - Token for thread operations
- `title` - Thread title (first query)
- `first_answer` - JSON string with answer preview
- `query_count` - Number of queries in thread
- `last_query_datetime` - Last query timestamp

### Follow-up Query Pattern

- Set `is_related_query=True` in QueryParams
- Reuse `frontend_context_uuid` from previous query
- Generate new `frontend_uuid` for each query
- Thread slug changes per query, but context UUID persists

## Implementation Phases

### Phase 1: Data Models and Core Infrastructure

#### 1.1 Create Thread Data Models
**File**: `src/perplexity_cli/api/models.py`

Add new dataclasses:
- `Thread` - Represents a thread from list_ask_threads response
- `ThreadContext` - Represents thread context for follow-ups
- `Collection` - Represents a collection (optional, for future use)

**Fields for Thread:**
```python
@dataclass
class Thread:
    slug: str
    title: str
    context_uuid: str
    frontend_context_uuid: str
    read_write_token: str
    first_answer: str  # JSON string
    last_query_datetime: str
    query_count: int
    total_threads: int
    has_next_page: bool
    # ... other fields from API response
```

#### 1.2 Update API Client for Library Endpoints
**File**: `src/perplexity_cli/api/endpoints.py`

Add methods to `PerplexityAPI`:
- `list_threads(limit=20, offset=0, ascending=False, search_term="") -> list[Thread]`
- `list_collections(limit=30, offset=0) -> list[Collection]` (optional)

**Implementation notes:**
- Use discovered endpoint: `POST /rest/thread/list_ask_threads`
- Use existing `self.client.get_headers()` for authentication (Bearer token)
- Add library-specific headers: `x-app-apiversion: 2.18`, `x-app-apiclient: default`
- Handle pagination with `has_next_page` flag
- Parse response array into Thread objects
- Use `httpx.Client` for non-streaming requests (library endpoints don't use SSE)

#### 1.3 Update Query Methods to Return Thread Context
**File**: `src/perplexity_cli/api/endpoints.py`

Modify `submit_query()` to optionally return thread context:
- Add `return_thread_context: bool = False` parameter
- Return `(messages, thread_context)` tuple when enabled
- Extract thread context from final SSE message

Create new method:
- `submit_followup_query(query: str, thread_context: ThreadContext, ...) -> Iterator[SSEMessage]`
  - Sets `is_related_query=True`
  - Reuses `frontend_context_uuid` from thread_context
  - Generates new `frontend_uuid`

### Phase 2: CLI Commands

#### 2.1 List Threads Command
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.option("--limit", default=20, help="Number of threads to show")
@click.option("--offset", default=0, help="Offset for pagination")
@click.option("--search", default="", help="Search term")
@click.option("--format", type=click.Choice(["table", "json"]), default="table")
def threads(limit, offset, search, format):
    """List your Perplexity threads/conversations."""
```

**Features:**
- Display threads in a table (slug, title, query_count, last_query_datetime)
- Support pagination with `--offset` and `--limit`
- Support search with `--search`
- JSON output option for scripting
- Show total thread count

#### 2.2 Show Thread Command
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.argument("thread_slug")
@click.option("--format", type=click.Choice(["plain", "markdown", "rich"]), default="rich")
def thread(thread_slug, format):
    """Show details of a specific thread."""
```

**Features:**
- Display thread metadata (title, query_count, dates)
- Show first answer preview
- Display thread URL (https://www.perplexity.ai/thread/{slug})
- Format options for answer display

**Note**: May need to discover endpoint for getting full thread details, or use existing query endpoint with thread context.

#### 2.3 Follow-up Query Command
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.argument("thread_slug")
@click.argument("query_text", metavar="QUERY")
@click.option("--format", type=click.Choice(["plain", "markdown", "rich"]), default="rich")
@click.option("--stream", is_flag=True, help="Stream response in real-time")
def followup(thread_slug, query_text, format, stream):
    """Send a follow-up query to an existing thread."""
```

**Features:**
- Look up thread by slug to get `frontend_context_uuid`
- Use `submit_followup_query()` with thread context
- Support streaming output
- Display answer with formatting options

#### 2.4 Continue Thread Command (Alternative)
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.argument("thread_slug")
def continue_thread(thread_slug):
    """Continue a thread with interactive queries."""
```

**Features:**
- Interactive mode for multiple follow-ups
- Maintain thread context across queries
- Exit with Ctrl+C or "exit"

### Phase 3: Thread Context Management

#### 3.1 Thread Context Storage
**File**: `src/perplexity_cli/utils/thread_context.py` (new)

Create utility for managing thread context:
- `save_thread_context(thread_slug, context)` - Save to local cache
- `load_thread_context(thread_slug)` - Load from cache
- `clear_thread_context()` - Clear cache

**Storage location**: `~/.config/perplexity-cli/threads.json`

**Structure**:
```json
{
  "threads": {
    "thread-slug-1": {
      "frontend_context_uuid": "...",
      "context_uuid": "...",
      "read_write_token": "...",
      "last_accessed": "2025-11-09T..."
    }
  }
}
```

#### 3.2 Thread Context from Query Responses
**File**: `src/perplexity_cli/api/endpoints.py`

Enhance query methods to automatically save thread context:
- After `submit_query()`, extract and save thread context
- After `submit_followup_query()`, update thread context
- Use thread context cache for follow-up commands

### Phase 4: Enhanced Features

#### 4.1 Thread Search
Enhance `threads` command with better search:
- Search by title, query text, or answer content
- Highlight matching terms in output
- Support regex patterns (optional)

#### 4.2 Thread Export
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.argument("thread_slug")
@click.option("--format", type=click.Choice(["json", "markdown", "txt"]), default="markdown")
@click.option("--output", type=click.Path(), help="Output file path")
def export(thread_slug, format, output):
    """Export a thread to a file."""
```

**Features:**
- Export thread with all queries and answers
- Support multiple formats (JSON, Markdown, plain text)
- Include metadata (dates, model, sources)

#### 4.3 Thread Delete (If Endpoint Exists)
**File**: `src/perplexity_cli/cli.py`

Add command:
```python
@main.command()
@click.argument("thread_slug")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
def delete_thread(thread_slug, confirm):
    """Delete a thread from your library."""
```

**Note**: Requires discovering delete endpoint or may not be available via API.

### Phase 5: Testing and Documentation

#### 5.1 Unit Tests
**Files**: `tests/test_threads.py`, `tests/test_followup.py`

Test cases:
- `test_list_threads()` - Test listing threads
- `test_thread_context_extraction()` - Test extracting context from responses
- `test_followup_query()` - Test follow-up query pattern
- `test_thread_context_storage()` - Test saving/loading context
- Mock API responses for all endpoints

#### 5.2 Integration Tests
**File**: `tests/test_threads_integration.py`

Test cases:
- `test_list_threads_integration()` - Real API call (requires auth)
- `test_followup_query_integration()` - Real follow-up query
- `test_thread_workflow()` - Complete workflow (query -> follow-up -> list)

#### 5.3 Documentation Updates
**File**: `README.md`

Add sections:
- Library/Threads commands usage
- Examples for each command
- Thread context explanation
- Follow-up query examples

## Implementation Order - Tracked Steps

### Priority 1: Core Functionality

#### Phase 1.1: Create Thread Data Models
- [x] **Step 1.1.1**: Create `Thread` dataclass in `src/perplexity_cli/api/models.py`
  - Fields: slug, title, context_uuid, frontend_context_uuid, read_write_token, first_answer, last_query_datetime, query_count, total_threads, has_next_page, and all other fields from API response
- [x] **Step 1.1.2**: Create `ThreadContext` dataclass for follow-up queries
  - Fields: thread_url_slug, frontend_context_uuid, context_uuid, read_write_token
- [x] **Step 1.1.3**: Create `Collection` dataclass (optional, for future use)
- [x] **Step 1.1.4**: Add `from_dict()` class methods to parse API responses

#### Phase 1.2: Implement Library API Methods
- [x] **Step 1.2.1**: Add `list_threads()` method to `PerplexityAPI` class in `src/perplexity_cli/api/endpoints.py`
  - Parameters: limit=20, offset=0, ascending=False, search_term=""
  - Return type: list[Thread]
- [x] **Step 1.2.2**: Implement HTTP POST request to `/rest/thread/list_ask_threads?version=2.18&source=default`
  - Use `httpx.Client` (not SSE client) for regular HTTP request
  - Use existing `self.client.get_headers()` for authentication
  - Add library headers: `x-app-apiversion: 2.18`, `x-app-apiclient: default`
- [x] **Step 1.2.3**: Parse response array into Thread objects using `Thread.from_dict()`
- [x] **Step 1.2.4**: Handle pagination with `has_next_page` flag (return metadata if needed)
- [x] **Step 1.2.5**: Add error handling (401, 404, 429, network errors)

#### Phase 1.3: Update Query Methods for Thread Context
- [x] **Step 1.3.1**: Modify `submit_query()` to optionally return thread context
  - Added `extract_thread_context()` helper method instead
  - Can extract context from messages after query completes
- [x] **Step 1.3.2**: Extract thread context from final SSE message
  - Capture: thread_url_slug, frontend_context_uuid, context_uuid, read_write_token
  - Implemented in `extract_thread_context()` method
- [x] **Step 1.3.3**: Create `submit_followup_query()` method
  - Parameters: query, thread_context: ThreadContext, language, timezone
  - Set `is_related_query=True` in QueryParams
  - Reuse `frontend_context_uuid` from thread_context
  - Generate new `frontend_uuid` for each query
  - Return: `Iterator[SSEMessage]`

#### Phase 2.1: Implement Threads List Command
- [x] **Step 2.1.1**: Add `threads` command to `src/perplexity_cli/cli.py`
  - Options: `--limit` (default 20), `--offset` (default 0), `--search` (default ""), `--format` (table/json, default table)
- [x] **Step 2.1.2**: Call `api.list_threads()` with provided parameters
- [x] **Step 2.1.3**: Display threads in table format (using rich library)
  - Columns: slug, title, query_count, last_query_datetime
  - Show total thread count
- [x] **Step 2.1.4**: Add JSON output option (use `--format json`)
- [x] **Step 2.1.5**: Handle empty results and errors gracefully

#### Phase 2.3: Implement Follow-up Query Command
- [x] **Step 2.3.1**: Add `followup` command to `src/perplexity_cli/cli.py`
  - Arguments: `thread_slug`, `query_text`
  - Options: `--format` (plain/markdown/rich), `--stream` (flag)
- [x] **Step 2.3.2**: Look up thread by slug using `list_threads()` and filter
  - Extract `frontend_context_uuid` from found thread
  - Create `ThreadContext` object using `to_thread_context()` method
- [x] **Step 2.3.3**: Call `api.submit_followup_query()` with thread context
- [x] **Step 2.3.4**: Support streaming output (reuse existing `_stream_query_response()` logic)
- [x] **Step 2.3.5**: Display answer with formatting options (reuse existing formatters)

### Priority 2: Enhanced Features

#### Phase 3.1: Thread Context Storage
- [ ] **Step 3.1.1**: Create `src/perplexity_cli/utils/thread_context.py` module
- [ ] **Step 3.1.2**: Implement `save_thread_context(thread_slug, context: ThreadContext)`
  - Save to `~/.config/perplexity-cli/threads.json`
  - Include timestamp for cache management
- [ ] **Step 3.1.3**: Implement `load_thread_context(thread_slug) -> ThreadContext | None`
  - Load from cache, return None if not found
- [ ] **Step 3.1.4**: Implement `clear_thread_context()` and `clear_thread_context(thread_slug)`
- [ ] **Step 3.1.5**: Add TTL check (e.g., 30 days) for cached contexts

#### Phase 3.2: Auto-save Thread Context
- [ ] **Step 3.2.1**: Modify `submit_query()` to auto-save thread context after completion
  - Extract context from final message
  - Save using `save_thread_context()`
- [ ] **Step 3.2.2**: Modify `submit_followup_query()` to update thread context
  - Update cache with new thread slug and context
- [ ] **Step 3.2.3**: Update `followup` command to use cached context if available
  - Try cache first, fall back to API lookup

#### Phase 2.2: Implement Thread Show Command
- [x] **Step 2.2.1**: Add `thread` command to `src/perplexity_cli/cli.py`
  - Argument: `thread_slug`
  - Option: `--format` (plain/markdown/rich, default rich)
- [x] **Step 2.2.2**: Look up thread by slug using `list_threads()`
- [x] **Step 2.2.3**: Display thread metadata
  - Title, query_count, last_query_datetime, status, mode
  - Thread URL: `https://www.perplexity.ai/thread/{slug}`
- [x] **Step 2.2.4**: Parse and display `first_answer` JSON
  - Extract answer text from JSON string
  - Format using existing formatters

### Priority 3: Advanced Features

#### Phase 2.4: Interactive Continue Thread Command
- [ ] **Step 2.4.1**: Add `continue` command to `src/perplexity_cli/cli.py`
  - Argument: `thread_slug`
- [ ] **Step 2.4.2**: Implement interactive loop
  - Load thread context once
  - Prompt for queries repeatedly
  - Send follow-up queries maintaining context
  - Exit on Ctrl+C or "exit" command

#### Phase 4.1: Enhanced Search
- [ ] **Step 4.1.1**: Enhance `threads` command search functionality
  - Search in title, query text, and answer content
  - Highlight matching terms in output
- [ ] **Step 4.1.2**: Add regex pattern support (optional)

#### Phase 4.2: Thread Export
- [ ] **Step 4.2.1**: Add `export` command to `src/perplexity_cli/cli.py`
  - Argument: `thread_slug`
  - Options: `--format` (json/markdown/txt), `--output` (file path)
- [ ] **Step 4.2.2**: Fetch thread data and all related queries/answers
- [ ] **Step 4.2.3**: Implement JSON export format
- [ ] **Step 4.2.4**: Implement Markdown export format
- [ ] **Step 4.2.5**: Implement plain text export format
- [ ] **Step 4.2.6**: Include metadata (dates, model, sources) in exports

#### Phase 4.3: Thread Delete (If Endpoint Available)
- [ ] **Step 4.3.1**: Discover delete thread endpoint (if exists)
- [ ] **Step 4.3.2**: Add `delete` command to `src/perplexity_cli/cli.py`
  - Argument: `thread_slug`
  - Option: `--confirm` (skip confirmation)
- [ ] **Step 4.3.3**: Implement delete API call
- [ ] **Step 4.3.4**: Clear thread context from cache after deletion

### Priority 4: Testing & Documentation

#### Phase 5.1: Unit Tests
- [ ] **Step 5.1.1**: Create `tests/test_threads.py`
  - Test `Thread.from_dict()` with sample API response
  - Test `ThreadContext` creation and serialization
- [ ] **Step 5.1.2**: Create `tests/test_followup.py`
  - Test `submit_followup_query()` with mocked API
  - Test `is_related_query` flag is set correctly
  - Test `frontend_context_uuid` is reused
- [ ] **Step 5.1.3**: Test thread context extraction from SSE messages
- [ ] **Step 5.1.4**: Test thread context storage (save/load/clear)
- [ ] **Step 5.1.5**: Mock API responses for all endpoints

#### Phase 5.2: Integration Tests
- [ ] **Step 5.2.1**: Create `tests/test_threads_integration.py`
- [ ] **Step 5.2.2**: Test `list_threads()` with real API (requires auth)
- [ ] **Step 5.2.3**: Test `submit_followup_query()` with real API
- [ ] **Step 5.2.4**: Test complete workflow: query -> follow-up -> list threads
- [ ] **Step 5.2.5**: Test thread context persistence across commands

#### Phase 5.3: Documentation
- [ ] **Step 5.3.1**: Update `README.md` with "Library/Threads Commands" section
- [ ] **Step 5.3.2**: Add usage examples for `threads` command
- [ ] **Step 5.3.3**: Add usage examples for `thread` command
- [ ] **Step 5.3.4**: Add usage examples for `followup` command
- [ ] **Step 5.3.5**: Add usage examples for `continue` command
- [ ] **Step 5.3.6**: Add usage examples for `export` command
- [ ] **Step 5.3.7**: Document thread context explanation
- [ ] **Step 5.3.8**: Add troubleshooting section for common issues

## Technical Details

### API Request Headers

All library endpoints require:
```
x-app-apiversion: 2.18
x-app-apiclient: default
Content-Type: application/json
```

**Authentication:**
- ✅ Already verified: Library endpoints work with existing Bearer token authentication
- Use existing `SSEClient.get_headers()` method which includes `Authorization: Bearer {token}`
- No changes needed to authentication approach - it works for both query and library endpoints

### Error Handling

- Handle 401 (unauthorized) - prompt for re-authentication
- Handle 404 (thread not found) - clear error message
- Handle rate limiting (429) - use retry logic
- Handle network errors - use existing retry utilities

### Pagination

- `list_threads()` supports `offset` and `limit` parameters
- Check `has_next_page` flag in response
- CLI command should support `--next` flag to load more

### Thread Context Lifecycle

1. **Initial Query**: Generate new `frontend_context_uuid`, save to cache
2. **Follow-up Query**: Load `frontend_context_uuid` from cache, reuse it
3. **List Threads**: Can retrieve `frontend_context_uuid` from API response
4. **Cache Management**: TTL for cached contexts (e.g., 30 days)

## Files to Create/Modify

### New Files
- `src/perplexity_cli/utils/thread_context.py` - Thread context management
- `tests/test_threads.py` - Thread unit tests
- `tests/test_followup.py` - Follow-up query tests
- `tests/test_threads_integration.py` - Integration tests

### Modified Files
- `src/perplexity_cli/api/models.py` - Add Thread, ThreadContext, Collection models
- `src/perplexity_cli/api/endpoints.py` - Add list_threads(), submit_followup_query()
- `src/perplexity_cli/cli.py` - Add threads, thread, followup commands
- `README.md` - Add documentation for new commands
- `pyproject.toml` - No changes needed (dependencies already present)

## Success Criteria

- [ ] Can list threads with `perplexity-cli threads`
- [ ] Can view thread details with `perplexity-cli thread <slug>`
- [ ] Can send follow-up queries with `perplexity-cli followup <slug> <query>`
- [ ] Thread context is properly maintained across follow-ups
- [ ] All commands support formatting options (plain, markdown, rich)
- [ ] Unit tests pass with >80% coverage
- [ ] Integration tests pass with real API
- [ ] Documentation is complete and accurate

## Notes

- ✅ Authentication already works - verified with test script, Bearer token works for all endpoints
- Some endpoints may require additional discovery (e.g., get thread details, delete thread)
- Thread slugs are URL-safe identifiers generated by Perplexity
- Collections functionality is optional and can be deferred
- The API version (2.18) may change - should be configurable or auto-detected
- Library endpoints use regular HTTP (not SSE), so use `httpx.Client` instead of `SSEClient.stream_post()`

## Potential Issues & Solutions

### Issue 1: Authentication Method
**Status**: ✅ RESOLVED - Already verified that Bearer token works for library endpoints
**Solution**: Use existing `SSEClient.get_headers()` method - no changes needed

### Issue 2: Missing Endpoints
**Problem**: Some features may require endpoints we haven't discovered yet
**Solution**:
- Get thread details: May need to use list_threads and filter, or discover endpoint
- Delete thread: May not be available via API, or needs discovery
- Export: Can use existing data from list_threads response

### Issue 3: Thread Context Lookup
**Problem**: Need to find thread by slug to get context UUID for follow-ups
**Solution**:
- Use `list_threads()` and search for matching slug
- Cache thread context locally after queries
- Store context UUID in thread context storage

## Verification Checklist

Before starting implementation:
- [x] ✅ Verify library endpoint authentication works with current token (DONE - test script confirmed)
- [x] ✅ Test `list_threads()` endpoint with real API call (DONE - got 200 response)
- [ ] Confirm thread response structure matches our models
- [x] ✅ Verify follow-up query pattern works end-to-end (DONE - tested successfully)
- [ ] Check if additional endpoints needed for thread details

After each phase:
- [ ] Test with real API (not just mocks)
- [ ] Verify error handling works correctly
- [ ] Check that authentication persists across requests
- [ ] Ensure thread context is properly maintained

