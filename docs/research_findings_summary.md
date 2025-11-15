# Research Findings: Thread Structure and Query Counts

## Current Understanding (Likely Incorrect)

### What We Thought:
- Each `thread_url_slug` = one query
- `query_count` in API = queries for this thread slug
- Multiple queries = multiple slugs with same `frontend_context_uuid`

### What User Reports:
- Thread `b4cf5f8d` has 1 message → Shows query_count: 1 ✓
- Thread `1f344d10` has 2 messages → Shows query_count: 1 ✗ (should be 2)
- Thread `1e8ef0ac` has 3 messages → Shows query_count: 1 ✗ (should be 3)

**Conclusion**: The `query_count` field in the list API response is NOT the actual number of queries in the thread. It appears to always be 1, regardless of how many queries/messages the thread actually contains.

## Key Questions to Answer via CDP Research

1. **Thread Structure:**
   - Does one thread slug contain multiple queries, or does each query get its own slug?
   - How does Perplexity display multiple queries in the browser?
   - What API endpoint does the browser use to load thread details?

2. **Query Counting:**
   - Is there a thread detail endpoint that returns the correct query count?
   - How does the browser determine how many queries are in a thread?
   - Is the count stored somewhere else in the API response?

3. **Follow-up Behavior:**
   - When following up, does the thread slug change or stay the same?
   - What parameters are required to properly link follow-ups?
   - How does the browser track that queries belong to the same thread?

## Research Scripts Ready

1. `scripts/research_thread_detail_endpoint.py` - Test potential endpoints
2. `scripts/inspect_thread_page.py` - Inspect thread pages via CDP
3. `scripts/research_followup_behavior.py` - Research follow-up behavior

## Next Steps

1. Run research scripts with Chrome DevTools enabled
2. Analyze findings
3. Update implementation based on discoveries

