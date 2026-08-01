"""Packaging tests for bundled runtime resources.

These tests load resources through the installed distribution's resource API
(``importlib.resources``) rather than reading ``src/`` directly, so they stay
meaningful for a wheel or sdist installed into an interpreter.
"""

from __future__ import annotations

import json
from importlib import resources

from perplexity_cli.utils.config import clear_urls_cache, get_urls


def test_default_urls_are_loaded_from_distribution_resource() -> None:
    """Default URLs are readable from the installed distribution resource."""
    clear_urls_cache()

    resource = resources.files("perplexity_cli.config").joinpath("urls.json")
    assert resource.is_file()
    packaged_defaults = json.loads(resource.read_text(encoding="utf-8"))
    perplexity_defaults = packaged_defaults["perplexity"]

    url_config = get_urls()
    assert url_config.base_url == perplexity_defaults["base_url"]
    assert url_config.query_endpoint == perplexity_defaults["query_endpoint"]
    assert url_config.thread_list_endpoint == perplexity_defaults["thread_list_endpoint"]
    assert url_config.upload_url_endpoint == perplexity_defaults["upload_url_endpoint"]
    assert url_config.s3_bucket_url == perplexity_defaults["s3_bucket_url"]


def test_skill_resource_ships_in_distribution() -> None:
    """The agent skill definition is packaged with the distribution."""
    resource = resources.files("perplexity_cli.resources").joinpath("skill.md")
    assert resource.is_file()
    content = resource.read_text(encoding="utf-8")
    assert content.strip()
    assert "name:" in content


def test_distribution_metadata_matches_pyproject() -> None:
    """Installed distribution metadata agrees with pyproject.toml."""
    import importlib.metadata as importlib_metadata
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        project = tomllib.load(fh)["project"]

    distribution = importlib_metadata.distribution("pxcli")
    assert distribution.metadata["Name"] == "pxcli"
    assert distribution.version == project["version"]
    assert distribution.metadata["License-Expression"] == "MIT"
