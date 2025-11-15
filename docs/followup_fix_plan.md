# Plan to Fix Follow-up Threads

## Problem Statement

Follow-up queries are creating new threads instead of continuing existing threads. When a user runs `perplexity-cli followup <hash> "query"`, the follow-up creates a new thread instead of adding to the existing thread conversation.

## Root Cause Hypothesis

Based on research and code analysis, the issue is likely:

1. **Stale Context from `list_threads()`**: The thread context retrieved from `list_threads()` may be from an older query in the conversation, not the latest one needed for follow-ups.

2. **Incorrect `thread_url_slug` Usage**: The `thread_url_slug` in the request might need to be the parent thread's slug (the one we're following up on), but we might be using a different slug.

3. **Missing Latest Context**: We're using `found_thread.to_thread_context()` which gets context from `list_threads()` response, but we should potentially use the latest context from the actual query response.

## Research Findings

### From `docs/our_followup_request.json`:
- Browser request includes `thread_url_slug` in params
- All context fields are present: `context_uuid`, `read_write_token`, `frontend_context_uuid`
- `is_related_query: true` is set

### From `docs/followup_test_results.json`:
- Follow-up queries create NEW thread slugs (expected)
- `frontend_context_uuid` stays the same (good - links conversation)
- Initial and follow-up share same `frontend_context_uuid`

### Key Insight:
- Each query gets its own `thread_url_slug` (changes per query)
- Queries are linked by `frontend_context_uuid` (stays constant)
- The `thread_url_slug` in follow-up request should be the PARENT thread's slug (the one we're following up on)

## Implementation Plan

### Phase 1: Diagnostic & Research

#### Step 1.1: Create Diagnostic Script
**File**: `scripts/diagnose_followup_issue.py`

**Purpose**: Identify exact issue with follow-ups

**Actions**:
1. Submit initial query
2. Extract thread context from response
3. Submit follow-up using that context
4. Check if `frontend_context_uuid` matches
5. List threads and verify they appear together
6. Compare context from `list_threads()` vs query response
7. Report findings

#### Step 1.2: Capture Browser Follow-up Request
**File**: `scripts/research_followup_behavior.py` (already exists)

**Actions**:
1. Navigate to thread page
2. Send follow-up query in browser
3. Capture exact request payload
4. Compare with our implementation
5. Identify any differences

### Phase 2: Identify the Issue

#### Step 2.1: Compare Context Sources
Compare thread context from:
- `list_threads()` response (`Thread.to_thread_context()`)
- Query response (`extract_thread_context()`)
- Browser request (if captured)

**Hypothesis**: Context from `list_threads()` may be stale or incomplete.

#### Step 2.2: Analyze Request Payload
Compare our request with browser request:
- Field presence
- Field values
- Field locations
- Any missing fields

### Phase 3: Fix Implementation

#### Option A: Use Query Response Context (Recommended)
**If**: Context from query response is more accurate than `list_threads()`

**Changes**:
1. Update `followup` command to fetch thread by making a test query or using cached context
2. Prefer cached context (from previous queries) over `list_threads()` context
3. If cache miss, warn user that context may be stale

**Files to modify**:
- `src/perplexity_cli/cli.py` - `followup` command
- `src/perplexity_cli/utils/thread_context.py` - Context management

#### Option B: Fix Context from `list_threads()`
**If**: `list_threads()` context is correct but incomplete

**Changes**:
1. Ensure `Thread.to_thread_context()` includes all required fields
2. Verify `read_write_token` is present
3. Verify `context_uuid` is latest for the thread

**Files to modify**:
- `src/perplexity_cli/api/models.py` - `Thread.to_thread_context()`

#### Option C: Fix Request Parameters
**If**: Request structure is wrong

**Changes**:
1. Update `QueryParams` to include missing fields
2. Fix parameter values
3. Ensure `thread_url_slug` is parent thread's slug

**Files to modify**:
- `src/perplexity_cli/api/models.py` - `QueryParams`
- `src/perplexity_cli/api/endpoints.py` - `submit_followup_query()`

### Phase 4: Implementation Details

#### Fix 1: Improve Context Retrieval
**Current**: Uses `found_thread.to_thread_context()` from `list_threads()`

**Proposed**: 
1. Check cache first (most reliable - from actual query responses)
2. If cache miss, try to get latest context by:
   - Finding all threads with same `frontend_context_uuid`
   - Using the most recent one (by `last_query_datetime`)
   - Or warning user that context may be stale

**Code Location**: `src/perplexity_cli/cli.py:953-973`

#### Fix 2: Ensure Latest Context
**Current**: Uses specific thread's context (may be old)

**Proposed**:
- When cache miss, find all threads with same `frontend_context_uuid`
- Use the most recent thread's context (by `last_query_datetime`)
- This ensures we use the latest context in the conversation

**Code Location**: `src/perplexity_cli/cli.py:958-973`

#### Fix 3: Validate Context Completeness
**Current**: Basic validation in `submit_followup_query()`

**Proposed**:
- Check that all recommended fields are present
- Warn if optional fields are missing
- Log context details for debugging

**Code Location**: `src/perplexity_cli/api/endpoints.py:406-429`

### Phase 5: Testing

#### Step 5.1: Create Integration Test
**File**: `tests/test_followup_fix.py` (new)

**Test**: Verify follow-ups link correctly
1. Create initial query
2. Send follow-up
3. Verify `frontend_context_uuid` matches
4. List threads and verify they appear together
5. Verify thread count increases

#### Step 5.2: Update Existing Tests
**Files**:
- `tests/test_followup_verification.py`
- `tests/test_threads_integration.py`

**Updates**:
- Fix any incorrect expectations
- Add tests for context retrieval
- Add tests for latest context usage

### Phase 6: Documentation

#### Step 6.1: Update User Documentation
**File**: `README.md`

**Updates**:
- Document how follow-ups work
- Explain thread context behavior
- Add troubleshooting section

#### Step 6.2: Update Developer Documentation
**File**: `docs/FOLLOWUP_FIX_PLAN.md` (this file)

**Updates**:
- Document the fix
- Explain why it works
- Add notes about thread behavior

## Detailed Implementation Steps

### Step 1: Create Diagnostic Script

```python
# scripts/diagnose_followup_issue.py
1. Submit initial query: "What is Python?"
2. Extract context from response
3. Submit follow-up: "What are its features?"
4. Extract context from follow-up response
5. Verify frontend_context_uuid matches
6. List threads and find matching frontend_context_uuid
7. Report: How many threads found? Are they linked?
```

### Step 2: Fix Context Retrieval in `followup` Command

**Current Code** (`src/perplexity_cli/cli.py:953-973`):
```python
thread_context = load_thread_context(actual_slug)
if thread_context:
    # Use cached
else:
    thread_context = found_thread.to_thread_context()
```

**Proposed Fix**:
```python
thread_context = load_thread_context(actual_slug)
if thread_context:
    # Use cached (most reliable)
else:
    # Cache miss - try to get latest context from conversation
    # Find all threads with same frontend_context_uuid
    all_threads = api.list_threads(limit=100, offset=0, search_term="")
    matching_threads = [
        t for t in all_threads 
        if t.frontend_context_uuid == found_thread.frontend_context_uuid
    ]
    
    if matching_threads:
        # Use most recent thread's context
        latest_thread = max(matching_threads, key=lambda t: t.last_query_datetime)
        thread_context = latest_thread.to_thread_context()
        logger.info(f"Using latest context from thread: {latest_thread.slug}")
    else:
        # Fallback to requested thread's context
        thread_context = found_thread.to_thread_context()
        logger.warning(f"Using requested thread context (may be stale): {actual_slug}")
```

### Step 3: Enhance Logging

Add detailed logging to help debug:
- Log which context source is used (cache, latest thread, requested thread)
- Log all context field values
- Log request payload (in debug mode)
- Log response context fields

### Step 4: Update Tests

Add test that verifies:
- Follow-ups use latest context when cache miss
- Follow-ups link to existing threads correctly
- Thread list shows linked threads together

## Success Criteria

After fix:
- ✅ Follow-up queries add to existing thread (same `frontend_context_uuid`)
- ✅ Threads appear together in thread list
- ✅ Context is correctly maintained across follow-ups
- ✅ Diagnostic script confirms threads are linked
- ✅ All tests pass
- ✅ Manual testing confirms behavior matches browser

## Files to Modify

1. **`src/perplexity_cli/cli.py`**
   - Update `followup` command context retrieval (lines 953-973)
   - Use latest context from conversation when cache miss
   - Add better logging

2. **`src/perplexity_cli/cli.py`**
   - Update `continue` command similarly (lines 1140-1176)

3. **`src/perplexity_cli/api/endpoints.py`**
   - Enhance logging in `submit_followup_query()` (already done)
   - Add validation for context completeness

4. **`scripts/diagnose_followup_issue.py`** (new)
   - Diagnostic script to identify issue

5. **`tests/test_followup_fix.py`** (new)
   - Integration test for fix

6. **`tests/test_followup_verification.py`**
   - Update existing tests

## Implementation Priority

1. **High Priority**: Fix context retrieval to use latest context
2. **Medium Priority**: Add diagnostic script
3. **Medium Priority**: Enhance logging
4. **Low Priority**: Update documentation

## Next Steps

1. Create diagnostic script to confirm the issue
2. Implement fix to use latest context from conversation
3. Test fix with real queries
4. Update tests
5. Update documentation
