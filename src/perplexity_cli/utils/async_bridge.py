"""Async-to-sync bridge with nested event loop support.

This module defines the **single sync/async boundary** for the CLI.

The codebase uses a mixture of sync and async code:

- **Sync:** ``api/client.py`` (SSEClient) uses ``curl_cffi.Session`` for
  streaming queries — no event loop needed.
- **Async:** ``threads/scraper.py`` (ThreadScraper) and
  ``attachments/upload_manager.py`` (AttachmentUploader) use
  ``curl_cffi.AsyncSession`` for concurrent I/O.

All async-to-sync transitions go through :func:`run_async`.  No other
module should call ``asyncio.run()`` directly.  When no event loop is
running, ``asyncio.run()`` is used.  When called from inside an
already-running loop (e.g. Jupyter, pytest-asyncio, or a future
interactive mode), the coroutine is dispatched to a new thread with
its own loop so that ``RuntimeError: This event loop is already
running`` is avoided.

Current consumers:

- ``runners/export.py`` — thread export workflow
- ``query_runner.py`` — attachment uploads
- ``auth/oauth_handler.py`` — browser-based OAuth flow
"""

import asyncio
import concurrent.futures
from collections.abc import Coroutine


def run_async[T](coro: Coroutine[object, object, T]) -> T:
    """Run an async coroutine from synchronous code.

    Handles both the common case (no running loop) and the nested case
    (already inside an event loop) transparently.

    Args:
        coro: The coroutine to execute.

    Returns:
        The return value of the coroutine.

    Raises:
        Any exception raised by the coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running — the common CLI path
        return asyncio.run(coro)

    # Already inside an event loop — run in a dedicated thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()  # ty: ignore[invalid-return-type]
