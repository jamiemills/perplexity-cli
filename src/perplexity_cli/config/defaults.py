"""Centralised internal default constants.

All numeric and string defaults that are used across multiple modules
live here so they can be found and changed in a single location.

These are *code-level* defaults — not user-configurable via JSON or
environment variables.  For user-configurable values see
:mod:`perplexity_cli.config.models` and the ``urls.json`` / ``config.json``
files.
"""

# ---------------------------------------------------------------------------
# HTTP timeouts (seconds)
# ---------------------------------------------------------------------------

#: Default timeout for standard API requests.
DEFAULT_REQUEST_TIMEOUT: int = 60

#: Extended timeout for deep-research (multi-step) queries.
DEFAULT_DEEP_RESEARCH_TIMEOUT: int = 360

#: Timeout for S3 file-upload requests.
DEFAULT_UPLOAD_TIMEOUT: int = 300

#: Short timeout used by ``pxcli status --verify``.
DEFAULT_STATUS_CHECK_TIMEOUT: int = 10

# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

#: Maximum number of retry attempts for transient HTTP errors.
DEFAULT_MAX_RETRIES: int = 3

# ---------------------------------------------------------------------------
# Chrome DevTools Protocol
# ---------------------------------------------------------------------------

#: Default Chrome remote-debugging port.
DEFAULT_CHROME_DEBUG_PORT: int = 9222

#: Maximum time to wait for the user to authenticate (seconds).
DEFAULT_AUTH_TIMEOUT: int = 120

#: Polling interval while waiting for a session token (seconds).
DEFAULT_AUTH_POLL_INTERVAL: float = 2.0

#: Maximum time to wait for a page navigation to complete (seconds).
DEFAULT_PAGE_LOAD_TIMEOUT: int = 30

# ---------------------------------------------------------------------------
# User-facing URLs (used only in error messages / help text)
# ---------------------------------------------------------------------------

#: Link shown when a file-upload quota is exhausted.
PERPLEXITY_SETTINGS_URL: str = "https://www.perplexity.ai/settings/account"
