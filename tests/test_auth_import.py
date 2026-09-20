"""Tests for the ``pxcli auth import`` command.

Covers the export -> import round trip, local re-encryption, bundle
validation (VALIDATION exit 7), the save_cookies drop warning, the JSON
envelope shape, and the guarantee that credential material never reaches
console or log output.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import main

_TOKEN = "import-test-token-abc123"
_COOKIE_NAME = "cf_bm"
_COOKIE_VALUE = "import-test-cookie-xyz789"


@pytest.fixture
def _enable_save_cookies(runner) -> None:
    """Enable cookie storage in the isolated config directory."""
    result = runner.invoke(main, ["config", "set", "save_cookies", "true"])
    assert result.exit_code == 0


@pytest.fixture
def stored_credentials() -> None:
    """Store a deterministic token and cookies via the real TokenManager."""
    TokenManager().save_token(_TOKEN, cookies={_COOKIE_NAME: _COOKIE_VALUE})


def _export_bundle(runner, tmp_path: Path, *, enable_cookies: bool = False) -> Path:
    """Export the currently stored credentials and return the bundle path."""
    if enable_cookies:
        enabled = runner.invoke(main, ["config", "set", "save_cookies", "true"])
        assert enabled.exit_code == 0
    target = tmp_path / "creds.json"
    result = runner.invoke(main, ["auth", "export", "--output", str(target)])
    assert result.exit_code == 0
    return target


def _write_bundle(path: Path, **overrides: Any) -> None:
    """Write a bundle file, applying field overrides on the export shape."""
    bundle: dict[str, Any] = {
        "version": 1,
        "token": _TOKEN,
        "cookies": {},
        "exported_at": "2025-05-09T10:00:00+00:00",
    }
    bundle.update(overrides)
    path.write_text(json.dumps(bundle), encoding="utf-8")


class TestAuthImportRoundTrip:
    """Export then import restores credentials in the isolated config dir."""

    def test_round_trip_restores_token_without_cookies(self, runner, tmp_path) -> None:
        TokenManager().save_token(_TOKEN)
        bundle_path = _export_bundle(runner, tmp_path)
        TokenManager().clear_token()

        result = runner.invoke(main, ["auth", "import", str(bundle_path)])

        assert result.exit_code == 0
        token, cookies = TokenManager().load_token()
        assert token == _TOKEN
        assert cookies is None

    def test_round_trip_restores_cookies_when_enabled(
        self, runner, tmp_path, _enable_save_cookies, stored_credentials
    ) -> None:
        bundle_path = _export_bundle(runner, tmp_path, enable_cookies=True)
        assert json.loads(bundle_path.read_text(encoding="utf-8"))["cookies"]
        TokenManager().clear_token()

        result = runner.invoke(main, ["auth", "import", str(bundle_path)])

        assert result.exit_code == 0
        _, cookies = TokenManager().load_token()
        assert cookies == {_COOKIE_NAME: _COOKIE_VALUE}

    def test_import_re_encrypts_locally(self, runner, tmp_path, stored_credentials) -> None:
        bundle_path = _export_bundle(runner, tmp_path)

        result = runner.invoke(main, ["auth", "import", str(bundle_path)])

        assert result.exit_code == 0
        token_file = TokenManager().token_path
        bundle_bytes = bundle_path.read_bytes()
        token_bytes = token_file.read_bytes()
        # The stored token file is an encrypted record, not the plaintext bundle.
        assert token_bytes != bundle_bytes
        assert _TOKEN.encode() not in token_bytes

    def test_human_mode_prints_ok_line(self, runner, tmp_path, stored_credentials) -> None:
        bundle_path = _export_bundle(runner, tmp_path)
        result = runner.invoke(main, ["auth", "import", str(bundle_path)])
        assert result.exit_code == 0
        assert "[OK] Credentials imported" in result.output

    def test_unknown_top_level_keys_ignored_leniently(self, runner, tmp_path) -> None:
        bundle = tmp_path / "extra.json"
        _write_bundle(bundle, future_field="ignored")
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 0
        assert TokenManager().load_token()[0] == _TOKEN


class TestAuthImportValidation:
    """Schema violations and unreadable files exit with VALIDATION (7)."""

    def test_wrong_version_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "v2.json"
        _write_bundle(bundle, version=2)
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert "Unsupported bundle version" in result.stderr

    def test_missing_version_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "nov.json"
        _write_bundle(bundle)
        raw = json.loads(bundle.read_text(encoding="utf-8"))
        del raw["version"]
        bundle.write_text(json.dumps(raw), encoding="utf-8")
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7

    def test_empty_token_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "empty.json"
        _write_bundle(bundle, token="")
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert "non-empty string" in result.stderr
        assert not TokenManager().token_exists()

    def test_non_string_token_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "num.json"
        _write_bundle(bundle, token=12345)
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7

    def test_malformed_cookies_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "badcookies.json"
        _write_bundle(bundle, cookies={"cf_bm": 42})
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert "cookies" in result.stderr

    def test_malformed_json_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "broken.json"
        bundle.write_text("{definitely not json", encoding="utf-8")
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert "not valid JSON" in result.stderr

    def test_non_object_bundle_exits_seven(self, runner, tmp_path) -> None:
        bundle = tmp_path / "list.json"
        bundle.write_text("[1, 2, 3]", encoding="utf-8")
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert "JSON object" in result.stderr

    def test_missing_file_exits_seven(self, runner, tmp_path) -> None:
        # Recorded choice: a missing file is a validation error (exit 7),
        # not AUTH_REQUIRED (4) — nothing about the caller is unauthenticated.
        result = runner.invoke(main, ["auth", "import", str(tmp_path / "nope.json")])
        assert result.exit_code == 7
        assert "Cannot read import file" in result.stderr

    def test_validation_error_json_mode_error_envelope(self, runner, tmp_path) -> None:
        bundle = tmp_path / "v9.json"
        _write_bundle(bundle, version=99)
        result = runner.invoke(main, ["auth", "import", "--json", str(bundle)])
        assert result.exit_code == 7
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "validation_error"


class TestAuthImportCookieGate:
    """The save_cookies gate (AD7) warns loudly but still stores the token."""

    def test_cookies_dropped_warning_when_disabled(
        self, runner, tmp_path, _enable_save_cookies, stored_credentials
    ) -> None:
        bundle_path = _export_bundle(runner, tmp_path)
        assert json.loads(bundle_path.read_text(encoding="utf-8"))["cookies"]
        disabled = runner.invoke(main, ["config", "set", "save_cookies", "false"])
        assert disabled.exit_code == 0
        TokenManager().clear_token()

        result = runner.invoke(main, ["auth", "import", str(bundle_path)])

        assert result.exit_code == 0
        assert "save_cookies is disabled" in result.stderr
        assert "they will NOT be stored" in result.stderr
        assert "pxcli config set save_cookies true" in result.stderr
        token, cookies = TokenManager().load_token()
        assert token == _TOKEN
        assert cookies is None

    def test_no_warning_when_bundle_has_no_cookies(
        self, runner, tmp_path, stored_credentials
    ) -> None:
        bundle_path = _export_bundle(runner, tmp_path)
        result = runner.invoke(main, ["auth", "import", str(bundle_path)])
        assert result.exit_code == 0
        assert "save_cookies is disabled" not in result.stderr

    def test_warning_printed_before_save(
        self, runner, tmp_path, monkeypatch, capsys, _enable_save_cookies, stored_credentials
    ) -> None:
        from perplexity_cli.runners import auth as auth_runner

        bundle_path = _export_bundle(runner, tmp_path)
        assert json.loads(bundle_path.read_text(encoding="utf-8"))["cookies"]
        disabled = runner.invoke(main, ["config", "set", "save_cookies", "false"])
        assert disabled.exit_code == 0
        stderr_at_save: dict[str, str] = {}
        real_save = TokenManager.save_token

        def capturing_save(tm_self, token, cookies=None) -> None:
            stderr_at_save["err"] = capsys.readouterr().err
            real_save(tm_self, token, cookies=cookies)

        monkeypatch.setattr(TokenManager, "save_token", capturing_save)
        auth_runner.run_import_command(bundle_path)

        assert "save_cookies is disabled" in stderr_at_save["err"]


class TestAuthImportJsonMode:
    """JSON mode emits the import result envelope."""

    def test_json_envelope_shape(self, runner, tmp_path, stored_credentials) -> None:
        bundle_path = _export_bundle(runner, tmp_path)
        result = runner.invoke(main, ["auth", "import", "--json", str(bundle_path)])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["command"] == "pxcli auth import"
        assert payload["result"]["imported"] is True
        assert payload["result"]["cookies_stored"] is False

    def test_json_envelope_reports_cookies_stored(
        self, runner, tmp_path, _enable_save_cookies, stored_credentials
    ) -> None:
        bundle_path = _export_bundle(runner, tmp_path, enable_cookies=True)
        TokenManager().clear_token()

        result = runner.invoke(main, ["auth", "import", "--json", str(bundle_path)])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["result"]["imported"] is True
        assert payload["result"]["cookies_stored"] is True


class TestAuthImportNeverLeaksCredentials:
    """Credential material must never reach console or log output."""

    def test_token_absent_from_output_stderr_and_logs(
        self, runner, tmp_path, caplog, stored_credentials
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="perplexity_cli")
        bundle_path = _export_bundle(runner, tmp_path)

        # --verbose keeps INFO logging enabled through setup_logging.
        result = runner.invoke(main, ["--verbose", "auth", "import", "--json", str(bundle_path)])

        assert result.exit_code == 0
        assert _TOKEN not in result.output
        assert _TOKEN not in result.stderr
        assert _COOKIE_VALUE not in result.output
        assert _COOKIE_VALUE not in result.stderr
        assert _TOKEN not in caplog.text
        assert _COOKIE_VALUE not in caplog.text
        assert caplog.text  # the run did log (redacted) information

    def test_validation_errors_never_echo_bundle_contents(self, runner, tmp_path) -> None:
        bundle = tmp_path / "leaky.json"
        _write_bundle(bundle, token=_TOKEN, version=2)
        result = runner.invoke(main, ["auth", "import", str(bundle)])
        assert result.exit_code == 7
        assert _TOKEN not in result.output
        assert _TOKEN not in result.stderr
