"""Packaging tests for bundled runtime resources."""

import json
from pathlib import Path

from perplexity_cli.utils.config import clear_urls_cache, get_urls


def test_default_urls_are_loaded_from_packaged_resource() -> None:
    """Default URLs are readable from the installed package resource."""
    clear_urls_cache()

    url_config = get_urls()
    packaged_defaults = json.loads(
        (
            Path(__file__).resolve().parents[1] / "src" / "perplexity_cli" / "config" / "urls.json"
        ).read_text(encoding="utf-8")
    )
    perplexity_defaults = packaged_defaults["perplexity"]

    assert url_config.base_url == perplexity_defaults["base_url"]
    assert url_config.query_endpoint == perplexity_defaults["query_endpoint"]
    assert url_config.thread_list_endpoint == perplexity_defaults.get(
        "thread_list_endpoint", "/rest/thread/list_ask_threads"
    )
