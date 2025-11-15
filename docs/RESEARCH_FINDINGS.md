# Research Findings: Thread Structure and Query Counts

## Key Discovery

### Thread Query Count Mismatch

**Finding**: The API's `query_count` field does NOT reflect the actual number of queries in a thread.

**Evidence**:
- Thread `1e8ef0ac` (title: "and this thread has 3"):
  - API `query_count`: 1
  - DOM query elements: **3** (`"_class___query__": 3`)
  
- Thread `1f344d10` (title: "this is a thread and it has two messages"):
  - API `query_count`: 1
  - Expected: 2 queries (based on title)
  
- Thread `b4cf5f8d` (title: "this is a thread and it only has one message"):
  - API `query_count`: 1
  - Expected: 1 query (matches API)

## What This Means

1. **The `query_count` field in `/rest/thread/list_ask_threads` is unreliable**
   - It appears to always return `1`, regardless of actual query count
   - Cannot be used to determine how many queries are in a thread

2. **Thread structure:**
   - One thread slug can contain multiple queries
   - Queries are displayed together on the thread page
   - The DOM shows the actual query count via CSS classes

3. **Our current implementation is wrong:**
   - We group threads by `frontend_context_uuid` to count queries
   - This counts threads in a conversation, not queries in a thread
   - We need a different approach

## Research Results

### Thread Detail Endpoints
- **Status**: No working endpoints found
- All tested endpoints returned 403 Forbidden
- Cannot fetch thread details via API

### Thread Page Inspection
- **URL Format**: `/search/{slug}` (not `/thread/{slug}`)
- **DOM Structure**: Query elements found via CSS class selectors
- **Network Requests**: No thread detail API calls captured (may require authentication)

## Next Steps

### Option 1: Count Queries from DOM (Not Feasible)
- Would require loading each thread page and parsing DOM
- Too slow and unreliable for CLI tool

### Option 2: Use Different API Field
- Check if there's another field in the API response that shows correct count
- Review all fields in `Thread` model

### Option 3: Count Threads with Same Slug
- If multiple queries share the same slug, count them
- But research shows each query gets its own slug

### Option 4: Accept Limitation
- Acknowledge that accurate query count is not available via API
- Display API's `query_count` with a note that it may be inaccurate
- Or remove query count from display

## Recommendation

Since we cannot reliably get query counts from the API, we should:
1. Remove or deprecate the query count display
2. Or show the API's `query_count` with a disclaimer
3. Focus on fixing follow-up behavior instead

## Follow-up Research Needed

Still need to research:
- How follow-ups actually work
- What parameters are required
- Whether thread slug persists or changes

