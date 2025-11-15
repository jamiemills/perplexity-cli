# Follow-up Implementation Analysis

## Current Implementation Status

### Request Structure ✅

Our implementation correctly structures follow-up requests:

```json
{
  "query_str": "...",
  "params": {
    "is_related_query": true,
    "frontend_context_uuid": "...",
    "context_uuid": "...",
    "read_write_token": "...",
    "thread_url_slug": "...",
    ...
  }
}
```

This matches the expected structure from research (`docs/our_followup_request.json`).

### Code Flow ✅

1. **Thread Lookup**: `find_thread_by_identifier()` finds thread by hash or slug
2. **Context Retrieval**: 
   - First tries cache (`load_thread_context()`)
   - Falls back to `found_thread.to_thread_context()`
   - Saves to cache for future use
3. **Request Building**: `submit_followup_query()` builds `QueryParams` with:
   - `is_related_query=True`
   - `frontend_context_uuid` from thread context
   - `context_uuid` from thread context
   - `read_write_token` from thread context
   - `thread_url_slug` from thread context
4. **Request Submission**: Uses `QueryRequest.to_dict()` which wraps params correctly

### Potential Issues

#### Issue 1: Stale Thread Context
**Problem**: Thread context from `list_threads()` may be from an older query in the conversation.

**Current Behavior**: We use the specific thread's context (the one the user requested), which should be correct.

**Status**: ✅ This is the intended behavior - user specifies which thread to follow up on.

#### Issue 2: Thread URL Slug
**Problem**: Each query gets a new `thread_url_slug`, but we're using the old slug from `list_threads()`.

**Current Behavior**: We use the thread's slug from `list_threads()` as `thread_url_slug` in the request.

**Status**: ⚠️ This might be correct - we're telling Perplexity which thread we're following up on.

#### Issue 3: Context UUID Changes
**Problem**: `context_uuid` changes per query, but we're using the one from `list_threads()`.

**Current Behavior**: We use the thread's `context_uuid` from `list_threads()`.

**Status**: ⚠️ This might be the issue - we may need the latest `context_uuid` from the conversation.

## Research Needed

To definitively fix follow-ups, we need to:

1. **Capture Browser Request**: Use `scripts/research_followup_behavior.py` to capture actual browser request when sending a follow-up
2. **Compare Parameters**: Compare browser request with our implementation
3. **Identify Differences**: Find any missing or incorrect parameters
4. **Fix Implementation**: Update code based on findings

## Verification Script

Created `scripts/verify_followup_implementation.py` to verify our request structure matches expected format.

## Next Steps

1. Run follow-up research script (requires user to send follow-up in browser)
2. Compare browser request with our implementation
3. Fix any differences found
4. Test that follow-ups work correctly

