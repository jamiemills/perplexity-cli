# Research Execution Plan: Thread Structure and Query Counts

## Current Understanding (Likely Incorrect)

### What We Know:
- API endpoint `/rest/thread/list_ask_threads` returns threads with `query_count: 1` for all threads
- User confirms threads have 1, 2, and 3 messages respectively
- Our current code groups by `frontend_context_uuid` to count queries - this is WRONG

### What We Need to Discover:

1. **Thread Structure:**
   - Does one `thread_url_slug` contain multiple queries, or does each query get its own slug?
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

## Research Scripts Created

1. **`scripts/inspect_thread_page.py`**
   - Inspects thread pages via CDP
   - Extracts DOM structure
   - Captures network requests
   - **Run**: `python scripts/inspect_thread_page.py`

2. **`scripts/research_thread_detail_endpoint.py`**
   - Tests potential thread detail endpoints
   - **Run**: `python scripts/research_thread_detail_endpoint.py`

3. **`scripts/research_followup_behavior.py`**
   - Researches follow-up behavior via CDP
   - **Run**: `python scripts/research_followup_behavior.py <thread_hash>`

## Research Execution Steps

### Step 1: Get Thread Info from API

First, let's get the actual thread slugs for the three threads:

```bash
python -c "
import sys
sys.path.insert(0, 'src')
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import find_thread_by_identifier

tm = TokenManager()
token = tm.load_token()
api = PerplexityAPI(token=token)

for th in ['1e8ef0ac', '1f344d10', 'b4cf5f8d']:
    thread = find_thread_by_identifier(api, th)
    if thread:
        print(f'{th}: {thread.slug}')
"
```

### Step 2: Inspect Thread Pages

**Prerequisites:**
- Chrome running with `--remote-debugging-port=9222`
- CLI authenticated

**Run:**
```bash
python scripts/inspect_thread_page.py
```

**What to check in results:**
- `page_data.messages` - count of visible queries/messages
- `captured_requests` - API endpoints called when loading thread
- Look for thread detail endpoints

### Step 3: Test Detail Endpoints

**Run:**
```bash
python scripts/research_thread_detail_endpoint.py
```

**What to check:**
- Any endpoints returning 200 status
- Response structure (especially `query_count` field)
- Whether detail endpoint shows different query count

### Step 4: Research Follow-up

**Run:**
```bash
python scripts/research_followup_behavior.py 1e8ef0ac
```

**What to do:**
1. Script navigates to thread page
2. Wait for "MONITORING FOR FOLLOW-UP REQUEST" message
3. Send a follow-up query in the browser
4. Script captures the request

**What to check:**
- Request parameters
- Whether thread slug changes
- How query count updates

## Analysis After Research

1. **Compare findings:**
   - DOM query count vs API `query_count`
   - Thread detail endpoint response vs list endpoint response
   - Follow-up request parameters vs our current implementation

2. **Determine fixes:**
   - If detail endpoint exists → use it to get correct query count
   - If no detail endpoint → may need to count queries differently
   - Update follow-up implementation based on captured request

## Implementation Plan (After Research)

Based on research findings, we will:

1. **Fix Query Count:**
   - Use correct endpoint/method to get actual query count
   - Update `threads` command display
   - May need to fetch thread details separately

2. **Fix Follow-ups:**
   - Update `submit_followup_query()` with correct parameters
   - Ensure follow-ups add to existing thread
   - Verify thread slug behavior

3. **Update Tests:**
   - Add tests for correct query counting
   - Update follow-up tests based on findings

