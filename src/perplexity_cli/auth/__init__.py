"""Authentication module for Perplexity CLI."""

import warnings

from .oauth_handler import authenticate_with_browser
from .token_manager import TokenManager

# Suppress unused coroutine warnings from oauth_handler
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message=".*coroutine.*authenticate_with_browser.*was never awaited",
)

__all__ = ["authenticate_with_browser", "TokenManager"]
