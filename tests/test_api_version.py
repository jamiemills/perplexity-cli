"""Tests for API version handling in envelope metadata (8.1.1-8.1.3)."""

import re

import pytest

from perplexity_cli.envelope import (
    Meta,
    success_envelope,
)
from perplexity_cli.utils.version import get_version


def _make_meta(version: str = "0.7.0") -> Meta:
    return Meta(duration_ms=42, version=version, trace_id="test-trace-001")


class TestApiVersion:
    """Verify that envelope version metadata behaves correctly."""

    def test_envelope_accepts_valid_semver_version(self):
        """8.1.1: An envelope with a valid semver meta.version is accepted."""
        meta = _make_meta("0.7.0")
        env = success_envelope(command="query", result={"answer": "ok"}, meta=meta)

        dumped = env.model_dump(mode="json")
        assert dumped["meta"]["version"] == "0.7.0"

    @pytest.mark.parametrize(
        "version_str",
        [
            "1.0.0",
            "0.0.1-alpha",
            "2024.05.09",
            "dev",
            "0.7.0-rc.1+build.42",
        ],
    )
    def test_envelope_accepts_any_version_string(self, version_str: str):
        """8.1.2: The version field is a free-form string with no validation constraint."""
        meta = _make_meta(version_str)
        env = success_envelope(command="query", result={"answer": "ok"}, meta=meta)

        assert env.meta.version == version_str

    def test_envelopes_differ_only_in_version(self):
        """8.1.3: Two envelopes with different meta.version values are structurally
        identical except for the version field."""
        result = {"answer": "hello", "references": ["https://example.com"]}

        env_a = success_envelope(
            command="query",
            result=result,
            meta=_make_meta("0.6.0"),
        )
        env_b = success_envelope(
            command="query",
            result=result,
            meta=_make_meta("0.7.0"),
        )

        dump_a = env_a.model_dump(mode="json")
        dump_b = env_b.model_dump(mode="json")

        # Versions differ
        assert dump_a["meta"]["version"] != dump_b["meta"]["version"]

        # Everything else is identical
        dump_a["meta"]["version"] = dump_b["meta"]["version"]
        assert dump_a == dump_b

    def test_get_version_returns_semver_like_string(self):
        """Verify that get_version() returns a string resembling semver."""
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0
        # Should start with digits (e.g. "0.7.0" or "0.7.0.dev1")
        assert re.match(r"^\d+\.\d+", version), (
            f"get_version() returned '{version}', expected semver-like format"
        )

    def test_success_envelope_builder_propagates_meta(self):
        """Verify success_envelope() correctly threads meta through."""
        meta = _make_meta("0.7.0")
        env = success_envelope(command="auth login", result={"token_path": "/tmp"}, meta=meta)

        assert env.ok is True
        assert env.meta is not None
        assert env.meta.version == "0.7.0"
        assert env.meta.duration_ms == 42
        assert env.meta.trace_id == "test-trace-001"
        assert env.meta.truncated is False
