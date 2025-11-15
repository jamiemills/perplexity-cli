# Final Research Summary: Thread Query Count Issue

## Research Findings

### Problem Confirmed
The API's `query_count` field does NOT accurately reflect the number of queries in a thread.

**Evidence from CDP Research:**
- Thread `1e8ef0ac` ("and this thread has 3"):
  - API `query_count`: **1**
  - DOM query count: **3** ✓
  
- Thread `1f344d10` ("this is a thread and it has two messages"):
  - API `query_count`: **1**
  - DOM query count: **2** ✓
  
- Thread `b4cf5f8d` ("this is a thread and it only has one message"):
  - API `query_count`: **1**
  - DOM query count: **1** ✓ (matches)

### Key Discoveries

1. **API Limitation**: `/rest/thread/list_ask_threads` always returns `query_count: 1` regardless of actual queries
2. **No Detail Endpoint**: All tested thread detail endpoints return 403 Forbidden
3. **DOM Shows Truth**: The actual query count is visible in the DOM via CSS classes
4. **URL Format**: Threads use `/search/{slug}` not `/thread/{slug}`

## Current Implementation Issue

**File**: `src/perplexity_cli/cli.py` (lines 688-692)

**Current Code:**
```python
# Groups threads by frontend_context_uuid - WRONG APPROACH
conversation_counts: dict[str, int] = {}
for t in thread_list:
    conversation_counts[t.frontend_context_uuid] = conversation_counts.get(t.frontend_context_uuid, 0) + 1
```

**Problem**: This counts threads in a conversation, not queries in a thread.

## Solution Options

### Option 1: Remove Query Count Display (Recommended)
- Remove "Queries" column from `threads` command
- Or show API's `query_count` with a disclaimer
- Simplest and most honest approach

### Option 2: Use DOM Parsing (Not Feasible)
- Load each thread page and parse DOM
- Too slow for CLI tool
- Requires browser automation

### Option 3: Accept API Limitation
- Display API's `query_count` as-is
- Add note that it may be inaccurate
- Focus on other features

## Recommended Implementation

**Remove or deprecate query count display** since we cannot reliably get accurate counts from the API.

**Changes needed:**
1. Remove "Queries" column from `threads` table output
2. Remove `query_count` from JSON output (or keep with note)
3. Update documentation to explain limitation

## Follow-up Research Still Needed

We still need to research follow-up behavior:
- What parameters are required for follow-ups?
- Does thread slug persist or change?
- How to properly link follow-ups to existing threads?

This research can be done by:
1. Navigating to a thread in browser
2. Sending a follow-up query
3. Capturing the request payload
4. Comparing with our current implementation

