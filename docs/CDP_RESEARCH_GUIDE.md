# CDP Research Guide: Understanding Thread Structure

## Prerequisites

1. **Chrome must be running with remote debugging:**
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   ```

2. **Authenticate the CLI:**
   ```bash
   perplexity-cli auth
   ```

## Research Scripts

### 1. Inspect Thread Pages

**Script**: `scripts/inspect_thread_page.py`

**What it does:**
- Navigates to each of the three threads (1e8ef0ac, 1f344d10, b4cf5f8d)
- Extracts DOM structure to count visible queries/messages
- Captures network requests when page loads
- Looks for thread detail API endpoints

**How to run:**
```bash
python scripts/inspect_thread_page.py
```

**What to look for:**
- Number of query/message elements in DOM
- API endpoints called when loading thread page
- Thread data in `window.__NEXT_DATA__`
- Any endpoints that return thread details

### 2. Research Follow-up Behavior

**Script**: `scripts/research_followup_behavior.py <thread_hash>`

**What it does:**
- Navigates to a thread
- Waits for you to send a follow-up query in browser
- Captures the exact request payload
- Monitors how thread structure changes

**How to run:**
```bash
python scripts/research_followup_behavior.py 1e8ef0ac
```

**What to do:**
1. Script will navigate to thread page
2. Wait for "MONITORING FOR FOLLOW-UP REQUEST" message
3. Send a follow-up query in the browser
4. Script will capture the request

**What to look for:**
- Exact parameters in follow-up request
- Whether thread slug changes or stays same
- How query count updates after follow-up

### 3. Test Thread Detail Endpoints

**Script**: `scripts/research_thread_detail_endpoint.py`

**What it does:**
- Tests various potential thread detail endpoints
- Looks for endpoints that return full thread information
- Checks if any endpoint shows correct query count

**How to run:**
```bash
python scripts/research_thread_detail_endpoint.py
```

**What to look for:**
- Any endpoint that returns 200 status
- Response structure (especially `query_count` field)
- Whether detail endpoint shows different query count than list endpoint

## Key Questions to Answer

1. **How many queries are actually visible on each thread page?**
   - Check DOM structure from `inspect_thread_page.py` results
   - Compare with API `query_count: 1`

2. **What API endpoint loads thread details?**
   - Look at network requests captured by `inspect_thread_page.py`
   - Check if there's a `/rest/thread/{slug}` or similar endpoint

3. **How does follow-up work?**
   - Check request payload from `research_followup_behavior.py`
   - Verify if thread slug changes or stays same
   - See if query count updates

4. **What's the relationship between thread slug and queries?**
   - Does one slug = one query, or can one slug have multiple queries?
   - How are multiple queries linked together?

## Expected Output Files

After running scripts, check `docs/` directory for:
- `thread_inspection_*.json` - Thread page inspection results
- `thread_detail_endpoints.json` - Endpoint test results
- `followup_research_*.json` - Follow-up behavior results

## Analysis Steps

1. **Compare DOM query count with API query_count**
   - If DOM shows 3 queries but API shows 1, we need a different endpoint

2. **Find thread detail endpoint**
   - Look for endpoints that return 200 in `thread_detail_endpoints.json`
   - Check if they return correct query count

3. **Understand follow-up behavior**
   - Check if thread slug persists or changes
   - Verify required parameters for follow-ups

4. **Update implementation**
   - Use correct endpoint/method to get query count
   - Fix follow-up implementation based on findings

