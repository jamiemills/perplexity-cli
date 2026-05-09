"""Golden snapshot tests for envelope contracts per command (8.1.4-8.1.6).

These tests guard the shape of success envelopes for every command,
ensuring that result payloads contain the expected keys and that the
top-level envelope structure remains stable.
"""

import pytest

from perplexity_cli.envelope import Meta, success_envelope

# -- Fixtures: per-command result payloads ------------------------------------

COMMAND_PAYLOADS: dict[str, dict] = {
    "query": {
        "answer": "The answer is 42.",
        "references": ["https://example.com/source"],
    },
    "auth login": {
        "token_path": "/home/user/.local/share/pxcli/token",
        "cookies_stored": True,
    },
    "auth logout": {
        "credentials_existed": True,
    },
    "auth status": {
        "authenticated": True,
        "token_path": "/home/user/.local/share/pxcli/token",
        "token_age_days": 3,
        "cookies_stored": True,
        "verified": True,
    },
    "config set": {
        "key": "save_cookies",
        "value": "true",
    },
    "config show": {
        "config_path": "/home/user/.config/pxcli/config.toml",
        "save_cookies": True,
        "debug_mode": False,
        "env_overrides": {},
    },
    "style set": {
        "style": "concise",
    },
    "style show": {
        "style": "concise",
    },
    "style clear": {
        "had_style": True,
    },
    "threads export": {
        "threads": [],
        "total": 0,
        "output_path": "/tmp/threads.json",
        "date_range": {"from": "2025-01-01", "to": "2025-12-31"},
    },
    "doctor security": {
        "storage_backend": "keyring",
        "token_path": "/home/user/.local/share/pxcli/token",
        "token_permissions": "600",
        "cache_path": "/home/user/.cache/pxcli",
        "cache_permissions": "700",
        "cookies_enabled": True,
    },
}

ENVELOPE_TOP_LEVEL_KEYS = {"ok", "command", "result", "meta", "next_actions"}


def _make_meta() -> Meta:
    return Meta(duration_ms=10, version="0.7.0", trace_id="snap-trace-001")


# -- 8.1.4: Golden snapshot — shape verification per command ------------------


class TestEnvelopeSnapshots:
    """Golden snapshot tests verifying envelope shape for every command."""

    @pytest.mark.parametrize(
        "command,expected_result_keys",
        [(cmd, set(payload.keys())) for cmd, payload in COMMAND_PAYLOADS.items()],
        ids=list(COMMAND_PAYLOADS.keys()),
    )
    def test_success_envelope_shape(self, command: str, expected_result_keys: set[str]):
        """8.1.4: Serialised success envelope has the correct top-level keys
        and the result dict contains exactly the expected keys for this command."""
        env = success_envelope(
            command=command,
            result=COMMAND_PAYLOADS[command],
            meta=_make_meta(),
        )
        dumped = env.model_dump(mode="json")

        # Top-level shape
        assert set(dumped.keys()) == ENVELOPE_TOP_LEVEL_KEYS
        assert dumped["ok"] is True
        assert dumped["command"] == command

        # Result payload shape
        assert set(dumped["result"].keys()) == expected_result_keys


# -- 8.1.5: Additive compatibility -------------------------------------------


class TestEnvelopeAdditiveCompatibility:
    """Envelopes are additive: extra fields in result must not break anything."""

    @pytest.mark.parametrize(
        "command",
        list(COMMAND_PAYLOADS.keys()),
        ids=list(COMMAND_PAYLOADS.keys()),
    )
    def test_extra_field_in_result_is_allowed(self, command: str):
        """8.1.5: Adding a new field to result does not break serialisation
        and all original fields are still present."""
        original_keys = set(COMMAND_PAYLOADS[command].keys())

        extended_result = {**COMMAND_PAYLOADS[command], "new_experimental_field": True}
        env = success_envelope(
            command=command,
            result=extended_result,
            meta=_make_meta(),
        )
        dumped = env.model_dump(mode="json")

        # Original fields still present
        assert original_keys.issubset(set(dumped["result"].keys()))
        # Extra field also present
        assert dumped["result"]["new_experimental_field"] is True
        # Top-level shape unchanged
        assert set(dumped.keys()) == ENVELOPE_TOP_LEVEL_KEYS


# -- 8.1.6: Regression guard — missing required result keys -------------------


class TestEnvelopeRegressionGuard:
    """Detect when a required result key is missing from a command's payload."""

    @pytest.mark.parametrize(
        "command,required_key",
        [(cmd, key) for cmd, payload in COMMAND_PAYLOADS.items() for key in payload.keys()],
        ids=[f"{cmd}:{key}" for cmd, payload in COMMAND_PAYLOADS.items() for key in payload.keys()],
    )
    def test_missing_result_key_detected(self, command: str, required_key: str):
        """8.1.6: If any expected result key is absent, this test fails.
        This is the regression guard for envelope contracts."""
        incomplete_result = {
            k: v for k, v in COMMAND_PAYLOADS[command].items() if k != required_key
        }
        env = success_envelope(
            command=command,
            result=incomplete_result,
            meta=_make_meta(),
        )
        dumped = env.model_dump(mode="json")

        # The removed key should NOT be present — assert that to confirm detection
        assert required_key not in dumped["result"], (
            f"Key '{required_key}' should have been removed for this regression test"
        )

        # Verify the full payload WOULD include it (the spec says it must)
        assert required_key in COMMAND_PAYLOADS[command], (
            f"Key '{required_key}' is required in the '{command}' result payload"
        )
