# Thread Context Cache Explanation

## What is the Cache?

The thread context cache is a **local file** that stores `ThreadContext` objects for threads you've queried. It's located at:

**`~/.config/perplexity-cli/threads.json`**

## How It Works

### When Context is Saved

Thread context is automatically saved to the cache in two scenarios:

1. **After submitting a query** (`submit_query()`):
   - When `auto_save_context=True` (default)
   - After the query completes, the final message contains thread context
   - This context is saved to cache with the thread slug as the key

2. **After submitting a follow-up** (`submit_followup_query()`):
   - When `auto_save_context=True` (default)
   - The new thread slug and updated context are saved

### When Context is Loaded

The cache is checked in the `followup` and `continue` commands:

```python
# In followup command (src/perplexity_cli/cli.py:954)
thread_context = load_thread_context(actual_slug)

if thread_context:
    # Use cached context (most reliable - from actual query response)
    logger.debug(f"Using cached thread context for slug: {actual_slug}")
else:
    # Cache miss - fall back to list_threads() context
    thread_context = found_thread.to_thread_context()
```

## Cache Structure

The cache file (`threads.json`) looks like this:

```json
{
  "thread-slug-1": {
    "context": {
      "thread_url_slug": "thread-slug-1",
      "frontend_context_uuid": "uuid-123",
      "context_uuid": "context-uuid-456",
      "read_write_token": "token-789"
    },
    "saved_at": "2025-11-09T20:00:00"
  },
  "thread-slug-2": {
    "context": {
      "thread_url_slug": "thread-slug-2",
      "frontend_context_uuid": "uuid-456",
      "context_uuid": "context-uuid-789",
      "read_write_token": "token-abc"
    },
    "saved_at": "2025-11-09T19:00:00"
  }
}
```

## Why Cache is Important

### Cache is More Reliable

**Cached context** comes from actual query responses - it's the context that was used successfully in a real query.

**`list_threads()` context** comes from the API's thread list endpoint - it may be:
- Stale (from an older query in the conversation)
- Incomplete (missing some fields)
- Not the latest context needed for follow-ups

### Cache TTL

- Cache entries expire after **30 days**
- Expired entries are automatically ignored
- Cache is stored with restrictive permissions (0600)

## Current Behavior

### In `followup` Command:

1. **First**: Try to load from cache (`load_thread_context()`)
   - If found → Use cached context ✅ (most reliable)

2. **If cache miss**: Use context from `list_threads()` (`found_thread.to_thread_context()`)
   - This may be stale or incomplete ⚠️
   - Context is then saved to cache for future use

### The Problem

When cache miss occurs, we're using context from `list_threads()` which:
- May be from an older query in the conversation
- May not have the latest `context_uuid` or `read_write_token`
- May not be the correct context for follow-ups

## Proposed Fix

Instead of using the requested thread's context directly, when cache miss occurs:

1. Find **all threads** with the same `frontend_context_uuid` (same conversation)
2. Use the **most recent** thread's context (by `last_query_datetime`)
3. This ensures we use the latest context in the conversation

This way, even if cache miss occurs, we still get the most up-to-date context from the conversation.

