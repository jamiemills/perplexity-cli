# Perplexity Threads/Library API Research

## Overview

This document summarizes research findings for implementing library/threads functionality in the Perplexity CLI. The research was conducted through code analysis, API endpoint discovery, and response structure examination.

## Current Implementation Status

### Thread Information in Responses

The `SSEMessage` model already captures thread-related fields from API responses:

```python
@dataclass
class SSEMessage:
    thread_url_slug: str | None      # Thread identifier/slug
    context_uuid: str                 # Backend context UUID
    frontend_context_uuid: str       # Frontend context UUID (used for follow-ups)
    backend_uuid: str                # Backend UUID
    uuid: str                        # Request UUID
    cursor: str | None               # Pagination cursor (optional)
    read_write_token: str | None     # Token for thread operations (optional)
```

**Key Findings:**
- `thread_url_slug`: Unique identifier for the thread/conversation
- `frontend_context_uuid`: Should be reused for follow-up queries in the same thread
- `cursor`: May be used for pagination or continuation
- `read_write_token`: May be required for certain thread operations

### Query Parameters

The `QueryParams` model includes an `is_related_query` flag:

```python
@dataclass
class QueryParams:
    is_related_query: bool = False  # Indicates this is a follow-up query
    frontend_context_uuid: str = ""  # Context UUID for thread continuity
    # ... other parameters
```

## API Endpoints to Test

### Potential Library/Threads Endpoints

Based on common API patterns, the following endpoints should be tested:

1. **Library Listing:**
   - `GET /api/library`
   - `GET /rest/library`
   - `GET /api/user/library`
   - `GET /rest/user/library`

2. **Thread Retrieval:**
   - `GET /api/threads`
   - `GET /rest/threads`
   - `GET /api/threads/{thread_slug}`
   - `GET /rest/threads/{thread_slug}`

3. **Conversations:**
   - `GET /api/conversations`
   - `GET /rest/conversations`

### Query Endpoint (Known)

- **Endpoint:** `POST /rest/sse/perplexity_ask`
- **Method:** POST with Server-Sent Events (SSE) streaming
- **Request Format:**
  ```json
  {
    "query_str": "user query text",
    "params": {
      "language": "en-US",
      "timezone": "Europe/London",
      "frontend_uuid": "uuid-here",
      "frontend_context_uuid": "context-uuid-here",
      "is_related_query": false,
      "version": "api-version",
      // ... other parameters
    }
  }
  ```

## Follow-up Query Pattern

### Hypothesis

To send a follow-up query to an existing thread:

1. **Capture thread context from initial query:**
   - Extract `thread_url_slug` from the final `SSEMessage`
   - Extract `frontend_context_uuid` from the response
   - Optionally capture `read_write_token` if present

2. **Send follow-up query:**
   - Set `is_related_query: true` in `QueryParams`
   - Reuse the `frontend_context_uuid` from the previous query
   - Possibly include `thread_url_slug` in request parameters (needs testing)
   - Generate a new `frontend_uuid` for the new query

### Example Follow-up Request Structure

```python
# Initial query
params = QueryParams(
    frontend_uuid=str(uuid.uuid4()),
    frontend_context_uuid=str(uuid.uuid4()),
    is_related_query=False
)

# Follow-up query (hypothetical)
params = QueryParams(
    frontend_uuid=str(uuid.uuid4()),  # New UUID for this query
    frontend_context_uuid=previous_context_uuid,  # Reuse from previous
    is_related_query=True,  # Mark as follow-up
    # Possibly: thread_url_slug=previous_thread_slug
)
```

## Research Scripts Created

### 1. `scripts/discover_threads_api.py`
Tests potential library/threads endpoints and documents responses.

**Usage:**
```bash
python scripts/discover_threads_api.py
```

**Output:**
- Tests 8 potential endpoints
- Documents status codes (200, 401, 404, etc.)
- Saves results to `docs/api_discovery_results.json`

### 2. `scripts/analyze_thread_response.py`
Analyzes a real query response to extract thread information.

**Usage:**
```bash
python scripts/analyze_thread_response.py
```

**Output:**
- Submits a test query
- Extracts thread-related fields from SSE messages
- Saves analysis to `docs/thread_response_analysis.json`

### 3. `src/perplexity_cli/api/discovery.py`
Utility functions for API discovery:
- `discover_library_endpoints(token)`: Tests endpoints
- `inspect_thread_from_response(message_data)`: Extracts thread info
- `test_followup_query(token, thread_slug, context_uuid)`: Tests follow-up pattern

## Implementation Recommendations

### Phase 1: Thread Context Capture

1. **Modify `PerplexityAPI.submit_query()`:**
   - Return thread context information along with messages
   - Or create a new method `submit_query_with_context()` that returns `(messages, thread_context)`

2. **Create `ThreadContext` dataclass:**
   ```python
   @dataclass
   class ThreadContext:
       thread_url_slug: str | None
       frontend_context_uuid: str
       cursor: str | None = None
       read_write_token: str | None = None
   ```

### Phase 2: Follow-up Queries

1. **Add `submit_followup_query()` method:**
   ```python
   def submit_followup_query(
       self,
       query: str,
       thread_context: ThreadContext,
       language: str = "en-US",
       timezone: str = "Europe/London",
   ) -> Iterator[SSEMessage]:
   ```

2. **Update `QueryParams` to support thread context:**
   - Add optional `thread_url_slug` parameter
   - Ensure `is_related_query` is set correctly

### Phase 3: Library Management (If Endpoints Exist)

1. **List threads:**
   - `list_threads()` → Returns list of thread summaries
   - Requires discovery of correct endpoint

2. **Retrieve thread:**
   - `get_thread(thread_slug)` → Returns full thread with messages
   - Requires discovery of correct endpoint

3. **Delete thread:**
   - `delete_thread(thread_slug)` → Removes thread from library
   - Requires discovery of correct endpoint

## Testing Strategy

### Unit Tests

1. **Thread Context Extraction:**
   - Test `inspect_thread_from_response()` with various message structures
   - Verify all thread fields are correctly identified

2. **Follow-up Query Construction:**
   - Test that `is_related_query=True` is set
   - Test that `frontend_context_uuid` is reused
   - Test that new `frontend_uuid` is generated

### Integration Tests

1. **End-to-end follow-up:**
   - Send initial query
   - Capture thread context
   - Send follow-up query using context
   - Verify responses are linked

2. **Library endpoints (if discovered):**
   - Test listing threads
   - Test retrieving specific thread
   - Test thread operations

## Next Steps

1. **Run discovery scripts** (requires authentication):
   ```bash
   # Authenticate first
   perplexity-cli auth
   
   # Run discovery
   python scripts/discover_threads_api.py
   python scripts/analyze_thread_response.py
   ```

2. **Analyze results:**
   - Review `docs/api_discovery_results.json`
   - Review `docs/thread_response_analysis.json`
   - Identify working endpoints

3. **Test follow-up pattern:**
   - Create test script that sends initial query
   - Captures thread context
   - Sends follow-up query
   - Verifies thread continuity

4. **Implement based on findings:**
   - If library endpoints exist → implement full library management
   - If only follow-ups work → implement thread context and follow-ups
   - Document limitations if certain features aren't available

## Known Limitations

1. **No Public API Documentation:**
   - Perplexity's API is private/undocumented
   - Implementation relies on reverse engineering

2. **Authentication Required:**
   - All discovery scripts require valid authentication token
   - Cannot test endpoints without authentication

3. **API May Change:**
   - Private APIs can change without notice
   - Implementation should be flexible and handle errors gracefully

## References

- `src/perplexity_cli/api/models.py` - Data models including `SSEMessage` and `QueryParams`
- `src/perplexity_cli/api/endpoints.py` - API client implementation
- `src/perplexity_cli/api/client.py` - SSE client implementation
- `tests/test_api_client.py` - Test examples with `thread_url_slug`

