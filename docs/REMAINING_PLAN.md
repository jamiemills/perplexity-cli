# Remaining Plan Items

## Completed ✅

1. **Query Count Research** - Confirmed API `query_count` is unreliable
2. **Query Count Fix** - Removed "Queries" column from threads command
3. **URL Format Fix** - Updated URLs to use `/search/` instead of `/thread/`

## Remaining Tasks

### 1. Follow-up Behavior Research (REQUIRES USER INTERACTION)

**Status**: Script ready, needs to be run with user sending a follow-up query

**What needs to happen**:
1. Run: `python scripts/research_followup_behavior.py <thread_hash>`
2. Script will navigate to thread page
3. **User must send a follow-up query in the browser** while script is monitoring
4. Script will capture the exact request payload
5. Compare captured request with our current implementation

**Script**: `scripts/research_followup_behavior.py`
- Updated to use `/search/` URL format
- Ready to capture follow-up requests

**Expected Output**: `docs/followup_research_<hash>.json` with:
- Captured request payload
- Initial thread state
- Final thread state

### 2. Fix Follow-up Implementation (AFTER RESEARCH)

**Status**: Waiting on research findings

**What needs to be done**:
1. Compare captured browser request with our `submit_followup_query()` implementation
2. Identify missing or incorrect parameters
3. Update `QueryParams` model if needed
4. Update `submit_followup_query()` method
5. Test that follow-ups properly link to existing threads

**Files to modify**:
- `src/perplexity_cli/api/models.py` - Update `QueryParams` if needed
- `src/perplexity_cli/api/endpoints.py` - Fix `submit_followup_query()`
- `src/perplexity_cli/cli.py` - Update `followup` and `continue` commands if needed

### 3. Update Tests

**Status**: Waiting on implementation fixes

**What needs to be done**:
1. Update follow-up tests to verify correct behavior
2. Add integration tests that verify follow-ups link to existing threads
3. Ensure all tests pass

**Files to modify**:
- `tests/test_followup_verification.py`
- `tests/test_followup_thread_linking.py`
- `tests/test_threads_integration.py`

## Next Steps

**Immediate**: Run follow-up research script
```bash
python scripts/research_followup_behavior.py 1e8ef0ac
```
Then send a follow-up query in the browser while script is running.

**After Research**: Analyze findings and fix implementation

**After Fix**: Update tests and verify everything works

