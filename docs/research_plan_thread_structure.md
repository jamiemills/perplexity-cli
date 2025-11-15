# Research Plan: Understanding Thread Structure and Query Counts

## Problem Statement

Based on user feedback:
- Thread `b4cf5f8d` has 1 message → Should show query_count: 1 ✓
- Thread `1f344d10` has 2 messages → Should show query_count: 2 ✗ (currently shows 1)
- Thread `1e8ef0ac` has 3 messages → Should show query_count: 3 ✗ (currently shows 1)

All three threads show `query_count: 1` in the API response, but the user confirms they have different numbers of messages.

## Current Understanding (Likely Incorrect)

**Current assumption:**
- Each `thread_url_slug` = one query
- Multiple queries in a conversation = multiple thread slugs with same `frontend_context_uuid`
- `query_count` in API response = queries for THIS thread slug (always 1)

**Problem:**
- This doesn't match reality - threads can have multiple queries/messages with the SAME slug
- The `query_count` field might represent something else, or we need a different endpoint

## Research Questions

1. **Thread Structure:**
   - Can one `thread_url_slug` contain multiple queries?
   - Or does each query get its own slug, but they're displayed together?
   - What does `query_count` in the list API actually represent?

2. **Query Counting:**
   - How does Perplexity count queries in a thread?
   - Is there a thread detail endpoint that shows the correct count?
   - Do we need to fetch thread details separately?

3. **Follow-up Behavior:**
   - When you follow up on a thread, does the slug change?
   - Or does the same slug get updated with a new query?
   - How does the browser track multiple queries in one thread?

## Research Steps

### Step 1: Test Thread Detail Endpoints

**Script**: `scripts/research_thread_detail_endpoint.py`

Test potential endpoints:
- `/rest/thread/{slug}`
- `/rest/thread/get_thread?slug={slug}`
- `/rest/thread/detail?slug={slug}`
- `/api/thread/{slug}`
- `/rest/conversation/{slug}`
- `/rest/thread/list_thread_queries?slug={slug}`

**Goal**: Find endpoint that returns full thread details including correct query count.

### Step 2: Inspect Thread Pages via CDP

**Script**: `scripts/inspect_thread_page.py`

For each thread (1e8ef0ac, 1f344d10, b4cf5f8d):
1. Navigate to thread page
2. Extract DOM structure to count visible queries/messages
3. Capture network requests when page loads
4. Look for API calls that fetch thread details
5. Extract thread data from `window.__NEXT_DATA__` or React state

**Expected Findings**:
- Actual number of queries visible on page
- API endpoint used to load thread details
- Structure of thread data in browser

### Step 3: Research Follow-up Behavior

**Script**: `scripts/research_followup_behavior.py`

1. Navigate to a thread
2. Send a follow-up query in browser
3. Capture request to `/rest/sse/perplexity_ask`
4. Monitor response and page updates
5. Check if thread slug changes or stays same
6. Verify query count after follow-up

**Expected Findings**:
- Exact parameters for follow-up requests
- How thread structure changes after follow-up
- Whether slug persists or changes
- How query count is tracked

### Step 4: Analyze API Response Structure

**Current Data**: `docs/list_threads_response.json`

**Analysis**:
- Check if `query_count` field is consistent
- Look for patterns in `frontend_context_uuid` grouping
- Compare `total_threads` vs individual `query_count`
- See if there's a field that indicates conversation size

## Implementation Plan (After Research)

Based on findings, we will:

1. **Fix Query Count Display**
   - Use correct endpoint/method to get actual query count
   - Update `threads` command to show accurate counts
   - May need to fetch thread details separately for each thread

2. **Fix Follow-up Implementation**
   - Update `submit_followup_query` with correct parameters
   - Ensure follow-ups add to existing thread correctly
   - Verify thread slug behavior matches browser

3. **Update Data Models**
   - May need to add fields or methods to `Thread` model
   - May need new `ThreadDetail` model if detail endpoint exists

4. **Update Tests**
   - Add tests for correct query counting
   - Add tests for follow-up behavior
   - Verify against actual browser behavior

## Key Files to Modify (After Research)

- `src/perplexity_cli/api/endpoints.py` - Add thread detail endpoint if found
- `src/perplexity_cli/api/models.py` - Update Thread model if needed
- `src/perplexity_cli/cli.py` - Fix query count calculation in `threads` command
- `src/perplexity_cli/api/endpoints.py` - Fix `submit_followup_query` implementation

## Research Scripts Created

1. `scripts/research_thread_detail_endpoint.py` - Test potential thread detail endpoints
2. `scripts/inspect_thread_page.py` - Inspect thread pages via CDP
3. `scripts/research_followup_behavior.py` - Research follow-up behavior via CDP
4. `scripts/research_thread_structure.py` - General thread structure research

## Next Steps

1. Run `research_thread_detail_endpoint.py` to find working endpoints
2. Run `inspect_thread_page.py` with Chrome DevTools enabled to inspect the three threads
3. Run `research_followup_behavior.py` to understand follow-up behavior
4. Analyze all findings
5. Update implementation based on discoveries

