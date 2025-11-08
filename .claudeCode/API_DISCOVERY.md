# Perplexity API Discovery - Phase 1 Research

**Date**: 2025-11-08
**Research Method**: Chrome DevTools Protocol network monitoring
**Status**: ✅ COMPLETE

---

## Key Finding: Query API Endpoint

### Primary Query Endpoint

**URL**: `POST https://www.perplexity.ai/rest/sse/perplexity_ask`

**Type**: Server-Sent Events (SSE) streaming endpoint

**Purpose**: Submit queries and receive streaming responses

---

## Request Structure

### HTTP Method
```
POST
```

### URL
```
https://www.perplexity.ai/rest/sse/perplexity_ask
```

### Required Headers
```
Content-Type: application/json
Accept: text/event-stream
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36
Authorization: Bearer <token>
x-perplexity-request-reason: perplexity-query-state-provider
```

### Request Body Structure
```json
{
  "params": {
    "attachments": [],
    "language": "en-US",
    "timezone": "Europe/London",
    "search_focus": "internet",
    "sources": ["web"],
    "search_recency_filter": null,
    "frontend_uuid": "<uuid>",
    "mode": "copilot",
    "model_preference": "pplx_pro",
    "is_related_query": false,
    "is_sponsored": false,
    "frontend_context_uuid": "<uuid>",
    "prompt_source": "user",
    "query_source": "home",
    "is_incognito": false,
    "local_search_enabled": false,
    "use_schematized_api": true,
    "send_back_text_in_streaming_api": false,
    "supported_block_use_cases": [
      "answer_modes",
      "media_items",
      "knowledge_cards",
      "inline_entity_cards",
      "place_widgets",
      "finance_widgets",
      "sports_widgets",
      "flight_status_widgets",
      "shopping_widgets",
      "jobs_widgets",
      "search_result_widgets",
      "clarification_responses",
      "inline_images",
      "inline_assets",
      "placeholder_cards",
      "diff_blocks",
      "inline_knowledge_cards",
      "entity_group_v2",
      "refinement_filters",
      "canvas_mode",
      "maps_preview",
      "answer_tabs",
      "price_comparison_widgets"
    ],
    "client_coordinates": null,
    "mentions": [],
    "dsl_query": "<your query here>",
    "skip_search_enabled": true,
    "is_nav_suggestions_disabled": false,
    "always_search_override": false,
    "override_no_search": false,
    "should_ask_for_mcp_tool_confirmation": true,
    "browser_agent_allow_once_from_toggle": false,
    "version": "2.18"
  },
  "query_str": "<your query here>"
}
```

### Required Fields (Minimal)
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
  "query_str": "<your query>"
}
```

---

## Response Structure

### Response Type
**Server-Sent Events (SSE)** - Text streaming format

### Content-Type
```
text/event-stream; charset=utf-8
```

### SSE Message Format
```
event: message
data: {<json_payload>}
```

### Response Stream Structure

The response is a stream of SSE messages, each containing a JSON payload with incremental updates.

**Key Fields in Each Message**:
```json
{
  "backend_uuid": "<uuid>",
  "context_uuid": "<uuid>",
  "uuid": "<request_uuid>",
  "frontend_context_uuid": "<uuid>",
  "display_model": "pplx_pro",
  "mode": "COPILOT",
  "thread_url_slug": "<slug>",
  "status": "PENDING" | "IN_PROGRESS" | "COMPLETE",
  "text_completed": false | true,
  "blocks": [
    {
      "intended_usage": "web_results" | "answer_tabs" | "pro_search_steps",
      "web_result_block": {...},
      "diff_block": {...},
      "plan_block": {...}
    }
  ],
  "cursor": "<cursor_id>",
  "final_sse_message": false | true
}
```

### Answer Extraction

**Search Results** appear in `blocks` with `intended_usage: "web_results"`:
```json
{
  "blocks": [{
    "intended_usage": "web_results",
    "diff_block": {
      "field": "web_result_block",
      "patches": [{
        "op": "replace",
        "path": "",
        "value": {
          "progress": "IN_PROGRESS",
          "web_results": [
            {
              "name": "Paris - Wikipedia",
              "snippet": "Paris is the capital and largest city of France...",
              "url": "https://en.wikipedia.org/wiki/Paris",
              "timestamp": "2001-11-06T00:00:00"
            }
          ]
        }
      }]
    }
  }]
}
```

**Answer Text** appears in later messages in the stream, typically in blocks with text content.

**Final Message** has `final_sse_message: true` indicating the stream is complete.

---

## Other Discovered Endpoints

### Rate Limiting
```
GET https://www.perplexity.ai/rest/rate-limit/all?version=2.18&source=default
```
Returns rate limit information for the user.

### Thread Management
```
POST https://www.perplexity.ai/rest/thread/mark_viewed/<thread_uuid>?version=2.18&source=default
```
Marks a thread as viewed.

### Feedback
```
POST https://www.perplexity.ai/rest/entry/should-show-feedback/<entry_uuid>?version=2.18&source=default
```
Checks if feedback prompt should be shown.

### User Collections
```
GET https://www.perplexity.ai/rest/collections/list_user_collections?limit=30&offset=0&version=2.18&source=default
```
Lists user's saved collections.

### Version Info
```
GET https://www.perplexity.ai/api/version
```
Returns API version information.

---

## Implementation Strategy

### For Phase 3: API Client

1. **HTTP Client Configuration**
   - Use `httpx` with SSE streaming support
   - Add Bearer token authentication
   - Set proper headers (User-Agent, Content-Type, Accept)

2. **Query Submission**
   - POST to `/rest/sse/perplexity_ask`
   - Generate UUIDs for `frontend_uuid` and `frontend_context_uuid`
   - Include minimal required parameters
   - Handle SSE streaming response

3. **Response Parsing**
   - Parse SSE format (`event: message\ndata: {...}`)
   - Extract JSON from each `data:` line
   - Monitor `blocks` array for results
   - Look for `web_results` and answer text
   - Check `final_sse_message` to know when complete

4. **Answer Extraction**
   - Collect text from streaming blocks
   - Extract final answer when `text_completed: true`
   - Optionally include sources from `web_results`

---

## Authentication Details

### Token Format
- JWT encrypted with AES-256-GCM
- Length: ~484 characters
- Format: `eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0...`

### Authentication Header
```
Authorization: Bearer <jwt_token>
```

### Token Source
- Extracted from browser localStorage: `pplx-next-auth-session`
- Or from cookies: `__Secure-next-auth.session-token`

### Token Validation
- Verified working with `/api/user` endpoint (returns user profile)
- Used successfully for query submission to `/rest/sse/perplexity_ask`

---

## API Versioning

All REST endpoints use query parameters:
```
?version=2.18&source=default
```

Current API version: **2.18**

---

## Notes & Observations

1. **SSE Streaming**: Responses use Server-Sent Events for real-time streaming
   - Requires special handling (not standard JSON response)
   - Multiple messages sent incrementally
   - Final message indicated by `final_sse_message: true`

2. **Complex Request Parameters**: Many optional parameters for advanced features
   - Minimal viable request only needs: query_str, version, UUIDs
   - Can simplify for CLI use case

3. **UUID Generation**: Frontend generates UUIDs for request tracking
   - `frontend_uuid`: Request identifier
   - `frontend_context_uuid`: Session/context identifier

4. **Search Results**: Provided before answer in `web_results` blocks
   - Contains source URLs, snippets, timestamps
   - Can extract for citation purposes

5. **Model Selection**: `model_preference: "pplx_pro"`
   - Pro model used for queries
   - May have free tier options

6. **Thread Management**: Each query creates a thread with slug
   - Format: `what-is-the-capital-of-france-L86vRtELQ6.qJj9k6CzYhQ`
   - Can be used for follow-up queries

---

## Implementation Plan for Phase 3

### 3.1 HTTP Client (client.py)
- Use `httpx.stream()` for SSE support
- Add authentication headers with Bearer token
- Implement SSE parsing (event/data format)
- Handle connection errors and timeouts

### 3.2 Endpoint Abstractions (endpoints.py)
- `submit_query(query: str, token: str) -> Iterator[dict]`
  - Generates UUIDs
  - Builds request payload
  - Streams SSE responses
  - Parses event-stream format

### 3.3 Data Models (models.py)
- `QueryRequest`: Request structure
- `QueryResponse`: Response structure
- `WebResult`: Search result structure
- `Block`: Answer block structure

### 3.4 Answer Extraction
- Parse SSE stream for text blocks
- Accumulate answer text from incremental updates
- Detect completion via `final_sse_message` flag
- Return complete answer text

---

## Test Query Used

**Query**: "What is the capital of France?"

**Result**: Successfully received streaming response with:
- Search results from Wikipedia, Britannica, BBC, etc.
- Web snippets with Paris identified as capital
- Streaming updates via SSE
- Thread created: `what-is-the-capital-of-france-L86vRtELQ6.qJj9k6CzYhQ`

**Response Time**: ~2-3 seconds for complete answer

---

## Security Considerations

1. **Token in Headers**: Always use Bearer authentication
2. **UUID Generation**: Use Python `uuid.uuid4()` for uniqueness
3. **Input Validation**: Sanitize query_str to prevent injection
4. **Response Validation**: Parse JSON safely, handle malformed SSE
5. **Error Handling**: Catch network errors, invalid tokens, rate limits

---

## Ready for Implementation

With this API discovery complete, Phase 3 can now:
1. Implement SSE client for streaming responses
2. Build query submission with proper request format
3. Parse responses and extract answers
4. Handle errors and edge cases

All authentication is in place, API structure is documented, ready to build!
