# Research Findings and Implementation Plan

## Problem Statement

**User Report:**
- Thread `b4cf5f8d` has 1 message → Shows query_count: 1 ✓
- Thread `1f344d10` has 2 messages → Shows query_count: 1 ✗ (should be 2)  
- Thread `1e8ef0ac` has 3 messages → Shows query_count: 1 ✗ (should be 3)

**Current Implementation Issue:**
- Our code groups threads by `frontend_context_uuid` to count queries
- This is incorrect - it counts threads in a conversation, not queries in a thread
- The API `query_count` field always returns `1`, regardless of actual query count

## What We Know

### From API Response Analysis:
- `/rest/thread/list_ask_threads` endpoint returns threads with `query_count: 1` for ALL threads
- Each thread has a unique `slug` (thread_url_slug)
- Threads can share the same `frontend_context_uuid` (same conversation)
- Each thread has its own `context_uuid`, `read_write_token`

### From Previous Research:
- Follow-up queries create NEW thread slugs (each query gets its own slug)
- Follow-ups reuse `frontend_context_uuid` (same conversation)
- `context_uuid` changes per query
- Our current follow-up implementation may be missing required parameters

### Current Code Issues:

1. **Query Count Calculation** (`src/perplexity_cli/cli.py:688-692`):
   ```python
   # WRONG: This counts threads with same frontend_context_uuid, not queries in thread
   conversation_counts: dict[str, int] = {}
   for t in thread_list:
       conversation_counts[t.frontend_context_uuid] = conversation_counts.get(t.frontend_context_uuid, 0) + 1
   ```

2. **Follow-up Implementation** (`src/perplexity_cli/api/endpoints.py:406-457`):
   - May be using wrong parameters
   - May not be linking to existing thread correctly

## What We Need to Research

### Research Question 1: How are queries counted in a thread?

**Hypothesis A**: One thread slug = one query
- Each query gets its own slug
- To count queries, we need to count threads with same `frontend_context_uuid`
- **Problem**: User says threads have multiple queries with same slug

**Hypothesis B**: One thread slug = multiple queries
- Thread slug persists across follow-ups
- Queries are stored within the thread
- Need a detail endpoint to get actual query count
- **Problem**: API `query_count` always shows 1

**Research Needed:**
- Inspect thread pages to see actual structure
- Find API endpoint that returns thread details with correct query count
- Understand relationship between slug and queries

### Research Question 2: How do follow-ups work?

**Current Understanding:**
- Follow-ups create new thread slugs
- They're linked by `frontend_context_uuid`
- But user says follow-ups should add to existing thread

**Research Needed:**
- Capture actual browser follow-up request
- See if thread slug persists or changes
- Understand how Perplexity links queries to threads

## Research Scripts Ready

1. **`scripts/inspect_thread_page.py`**
   - Inspects thread DOM structure
   - Captures network requests
   - Extracts thread data from page

2. **`scripts/research_thread_detail_endpoint.py`**
   - Tests potential thread detail endpoints
   - Looks for endpoint with correct query count

3. **`scripts/research_followup_behavior.py`**
   - Captures follow-up requests from browser
   - Monitors thread structure changes

## Implementation Plan (After Research)

### Phase 1: Fix Query Count Display

**Option A: Use Thread Detail Endpoint** (if found)
- Add `get_thread_detail(slug)` to `PerplexityAPI`
- Fetch detail for each thread to get accurate count
- Cache results

**Option B: Count Queries Differently** (if no detail endpoint)
- May need to fetch thread content and count queries
- Or use a different method to determine query count

**Option C: Use Different Field** (if research reveals one)
- Update Thread model to use correct field
- Update display logic

### Phase 2: Fix Follow-up Implementation

- Update `submit_followup_query()` with correct parameters from research
- Ensure thread slug behavior matches browser
- Verify follow-ups add to existing thread

### Phase 3: Update Tests

- Add tests for correct query counting
- Update follow-up tests
- Verify against browser behavior

## Files to Modify

1. `src/perplexity_cli/api/endpoints.py`
   - Add `get_thread_detail()` if endpoint found
   - Fix `submit_followup_query()` parameters

2. `src/perplexity_cli/api/models.py`
   - Update Thread model if needed
   - Add ThreadDetail model if detail endpoint exists

3. `src/perplexity_cli/cli.py`
   - Fix query count calculation (lines 688-692)
   - Update display logic

4. `tests/test_followup_verification.py`
   - Update tests for correct behavior

## Next Steps

1. **Run Research Scripts** (requires Chrome DevTools):
   ```bash
   # Start Chrome with debugging
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   
   # Run research
   python scripts/inspect_thread_page.py
   python scripts/research_thread_detail_endpoint.py
   python scripts/research_followup_behavior.py 1e8ef0ac
   ```

2. **Analyze Results:**
   - Check `docs/thread_inspection_*.json`
   - Check `docs/thread_detail_endpoints.json`
   - Check `docs/followup_research_*.json`

3. **Update Implementation:**
   - Fix query count calculation
   - Fix follow-up behavior
   - Update tests

