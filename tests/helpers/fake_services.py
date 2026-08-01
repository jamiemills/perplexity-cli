"""Typed fakes for the status and export runner test boundaries.

These fakes replace the unrestricted ``Mock()`` chains and deep
constructor-patch stacks previously used by ``tests/test_status_runner.py``
and ``tests/test_export_runner.py``.  Each fake implements only the small
surface that the runner modules rely on, and tests exercise real behaviour
(typed config models, real ``tmp_path`` files) wherever the state under test
is a genuine boundary.

The boundaries covered are:

* **token** — :class:`FakeTokenManager` for ``TokenManager``.
* **state** — :class:`FakeCacheManager` for ``ThreadCacheManager`` and
  :class:`FakeClickContext` for Click's current-context object.
* **path** — :class:`FakePath` for path-like arguments that only need
  ``stat``/``exists``/``__str__``; real ``tmp_path`` files are used where
  the filesystem state itself is under test.
* **model** — the real pydantic ``FeatureConfig``/``RateLimitConfig``
  models are used instead of mocks.
* **scraper** — :class:`FakeThreadScraper` for ``ThreadScraper``.
* **progress** — the progress callback passed to the scraper fake is
  invoked and recorded so tests can assert exact progress updates.
* **clock** — :class:`FixedClock` makes token-age computations
  deterministic instead of wall-clock dependent.
* **gateway** — :class:`FakeAPIGateway` for the ``PerplexityAPI`` /
  ``QueryGateway`` verification boundary.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from perplexity_cli.contracts.query import Answer
from perplexity_cli.threads.exporter import ThreadRecord


class _PathLike(Protocol):
    """Path-like surface used by the runner modules."""

    def stat(self) -> os.stat_result:
        """Return a stat result for the path."""

    def exists(self) -> bool:
        """Return whether the path exists."""

    def __str__(self) -> str:
        """Render the path as a string."""


@dataclass(frozen=True, slots=True)
class FakePath:
    """Path fake exposing only the stat/exists/str surface runners use.

    Attributes:
        value: String rendered by ``str()``.
        st_mtime: Modification timestamp returned by ``stat().st_mtime``.
        st_mode: Permission mode returned by ``stat().st_mode``.
        exists_value: Value returned by :meth:`exists`.
        stat_error: Exception type raised by :meth:`stat`, or None.
    """

    value: str = "/tmp/token.json"
    st_mtime: float | None = None
    st_mode: int | None = None
    exists_value: bool = True
    stat_error: type[BaseException] | None = None

    def __str__(self) -> str:
        """Render the fake path as its configured string value."""
        return self.value

    def exists(self) -> bool:
        """Return the configured existence flag."""
        return self.exists_value

    def stat(self) -> os.stat_result:
        """Return a stat result built from the configured members.

        Raises:
            BaseException: The configured ``stat_error``, if any.
        """
        if self.stat_error is not None:
            raise self.stat_error()
        mode = self.st_mode if self.st_mode is not None else 0o600
        mtime = self.st_mtime if self.st_mtime is not None else 0.0
        return os.stat_result((mode, 0, 0, 0, 0, 0, 0, mtime, mtime, mtime))


@dataclass(frozen=True, slots=True)
class FakeClickContext:
    """Click context fake exposing the ``obj`` mapping runners read."""

    obj: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FakeTokenManager:
    """``TokenManager`` fake for the auth boundary.

    Attributes:
        token_path: Path rendered in status output.
        token_exists_value: Value returned by :meth:`token_exists`.
        load_token_result: Value returned by :meth:`load_token`.
        load_token_error: Exception raised by :meth:`load_token`, if any.
        SECURE_PERMISSIONS: Expected secure file mode for doctor reports.
    """

    token_path: _PathLike = field(default_factory=FakePath)
    token_exists_value: bool = True
    load_token_result: tuple[str | None, dict[str, str] | None] = ("tok", None)
    load_token_error: Exception | None = None
    SECURE_PERMISSIONS: int = 0o600

    def token_exists(self) -> bool:
        """Return whether a token is considered present."""
        return self.token_exists_value

    def load_token(self) -> tuple[str | None, dict[str, str] | None]:
        """Return the configured token, raising ``load_token_error`` if set.

        Raises:
            Exception: The configured ``load_token_error``, if any.
        """
        if self.load_token_error is not None:
            raise self.load_token_error
        return self.load_token_result


@dataclass(slots=True)
class FakeCacheManager:
    """``ThreadCacheManager`` fake backed by real filesystem state.

    ``cache_exists`` reflects whether the configured cache file exists on
    disk, and :meth:`clear_cache` unlinks it, so tests exercise the real
    file lifecycle without any mocks.

    Attributes:
        cache_path: Path to the cache file.
        SECURE_PERMISSIONS: Expected secure file mode for doctor reports.
        cache_exists_calls: Number of :meth:`cache_exists` invocations.
        clear_calls: Number of :meth:`clear_cache` invocations.
    """

    cache_path: Path = Path("/tmp/threads-cache.json")
    SECURE_PERMISSIONS: int = 0o600
    cache_exists_calls: int = 0
    clear_calls: int = 0

    def cache_exists(self) -> bool:
        """Record and return whether the cache file currently exists."""
        self.cache_exists_calls += 1
        return self.cache_path.exists()

    def clear_cache(self) -> None:
        """Record and perform the cache clear by unlinking the file."""
        self.clear_calls += 1
        self.cache_path.unlink(missing_ok=True)


@dataclass(slots=True)
class FakeThreadScraper:
    """Async ``ThreadScraper`` fake for the export runner boundary.

    ``scrape_all_threads`` records its arguments, invokes the progress
    callback with the configured thread count, and either returns the
    configured threads or raises ``scrape_error`` when set.

    Attributes:
        threads: Thread dicts returned on a successful scrape.
        scrape_error: Exception raised by a scrape, if any.
        progress_calls: Every ``(current, total)`` progress update emitted.
        scrape_calls: Snapshot of the arguments of every scrape request.
    """

    threads: list[ThreadRecord] = field(default_factory=list)
    scrape_error: Exception | None = None
    progress_calls: list[tuple[int, int]] = field(default_factory=list)
    scrape_calls: list[dict[str, object]] = field(default_factory=list)

    async def scrape_all_threads(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ThreadRecord]:
        """Record the request, then return the threads or raise as configured.

        Raises:
            Exception: The configured ``scrape_error``, if any.
        """
        self.scrape_calls.append(
            {
                "from_date": from_date,
                "to_date": to_date,
                "progress_callback": progress_callback,
            }
        )
        if self.scrape_error is not None:
            raise self.scrape_error
        if progress_callback is not None and self.threads:
            progress_callback(len(self.threads), len(self.threads))
            self.progress_calls.append((len(self.threads), len(self.threads)))
        return self.threads


@dataclass(slots=True)
class FakeAPIGateway:
    """``PerplexityAPI`` / ``QueryGateway`` fake for token verification.

    Attributes:
        answer_text: Text returned by :meth:`get_complete_answer`.
        enter_error: Exception raised by :meth:`__enter__`, if any.
        queries: Every query passed to :meth:`get_complete_answer`.
    """

    answer_text: str | None = "OK"
    enter_error: Exception | None = None
    queries: list[str] = field(default_factory=list)

    def __enter__(self) -> FakeAPIGateway:
        """Enter the context, raising ``enter_error`` if configured.

        Raises:
            Exception: The configured ``enter_error``, if any.
        """
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Exit the context without suppressing exceptions."""

    def get_complete_answer(self, query: str, **kwargs: object) -> Answer:
        """Record the query and return an answer with the configured text."""
        self.queries.append(query)
        return Answer(text=self.answer_text or "")


class FixedClock:
    """Deterministic ``datetime`` replacement for age-computation tests.

    Drop-in for the ``datetime`` module name in ``runners.status``: it
    supplies ``now()`` and ``fromtimestamp`` so token-age calculations are
    reproducible rather than wall-clock dependent.
    """

    NOW = datetime(2025, 1, 10, 12, 0, 0)

    @classmethod
    def now(cls) -> datetime:
        """Return the fixed clock value."""
        return cls.NOW

    @staticmethod
    def fromtimestamp(timestamp: float) -> datetime:
        """Convert a POSIX timestamp to a naive datetime."""
        return datetime.fromtimestamp(timestamp)
