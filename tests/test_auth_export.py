"""Tests for the ``pxcli auth export`` command.

Covers the bundle contract, secure file permissions, the pre-write
warning, the AUTH_REQUIRED (exit 4) path, --output overrides, and the
guarantee that credential material never reaches console or log output.
"""

from __future__ import annotations

import json
import logging
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import main
from perplexity_cli.runners import auth as auth_runner

_POSIX = sys.platform != "win32"
_TOKEN = "export-test-token-abc123"
_COOKIE = "export-test-cookie-xyz789"


@pytest.fixture
def stored_credentials() -> None:
    """Store a deterministic token and cookies via the real TokenManager."""
    TokenManager().save_token(_TOKEN, cookies={"cf_bm": _COOKIE})


def _read_bundle(path: Path) -> dict[str, Any]:
    """Load and return the JSON bundle written by the export command."""
    return json.loads(path.read_text(encoding="utf-8"))


class TestAuthExportSuccess:
    """Successful exports write a versioned, timestamped, secure bundle."""

    def test_success_writes_correct_bundle(self, runner, tmp_path, stored_credentials) -> None:
        target = tmp_path / "creds.json"
        result = runner.invoke(main, ["auth", "export", "--output", str(target)])

        assert result.exit_code == 0
        assert target.exists()
        bundle = _read_bundle(target)
        assert bundle["version"] == 1
        assert bundle["token"] == _TOKEN
        # Cookie storage is disabled by default, so an empty mapping exports.
        assert bundle["cookies"] == {}
        datetime.fromisoformat(bundle["exported_at"])  # raises if not ISO-8601
        assert bundle["exported_at"].endswith("+00:00")

    @pytest.mark.skipif(not _POSIX, reason="POSIX file permissions")
    def test_file_written_with_0600_permissions(self, runner, tmp_path, stored_credentials) -> None:
        target = tmp_path / "creds.json"
        result = runner.invoke(main, ["auth", "export", "--output", str(target)])

        assert result.exit_code == 0
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_human_mode_prints_ok_line(self, runner, tmp_path, stored_credentials) -> None:
        target = tmp_path / "creds.json"
        result = runner.invoke(main, ["auth", "export", "--output", str(target)])

        assert result.exit_code == 0
        assert f"[OK] Credentials exported to {target}" in result.output

    def test_default_filename_in_cwd(
        self, runner, tmp_path, monkeypatch, stored_credentials
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["auth", "export"])

        assert result.exit_code == 0
        created = list(tmp_path.glob("pxcli-auth-*.json"))
        assert len(created) == 1
        # Filename follows pxcli-auth-YYYY-MM-DD-HHMMSS.json.
        assert re.fullmatch(r"pxcli-auth-\d{4}-\d{2}-\d{2}-\d{6}\.json", created[0].name)

    def test_output_short_flag_honoured(
        self, runner, tmp_path, monkeypatch, stored_credentials
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["auth", "export", "-o", "custom-name.json"])

        assert result.exit_code == 0
        assert (tmp_path / "custom-name.json").exists()

    def test_warning_printed_to_stderr_before_write(
        self, tmp_path, monkeypatch, capsys, stored_credentials
    ) -> None:
        stderr_at_write: dict[str, str] = {}
        real_write = auth_runner.atomic_write_json

        def capturing_write(path: Path, content: object, mode: int = 0o600) -> None:
            stderr_at_write["err"] = capsys.readouterr().err
            real_write(path, content, mode)

        monkeypatch.setattr(auth_runner, "atomic_write_json", capturing_write)
        auth_runner.run_export_command(tmp_path / "creds.json")

        assert "PLAINTEXT session credentials" in stderr_at_write["err"]
        assert "0600" in stderr_at_write["err"]
        assert "--output" in stderr_at_write["err"]
        captured = capsys.readouterr()
        assert "[OK] Credentials exported to" in captured.out


class TestAuthExportJsonMode:
    """JSON mode emits a path-only envelope."""

    def test_json_envelope_contains_path_not_token(
        self, runner, tmp_path, stored_credentials
    ) -> None:
        target = tmp_path / "creds.json"
        result = runner.invoke(main, ["auth", "export", "--json", "--output", str(target)])

        assert result.exit_code == 0
        # click's result.output mixes stderr (the warning); stdout is the envelope.
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["command"] == "pxcli auth export"
        assert payload["result"]["path"] == str(target)
        assert _TOKEN not in result.stdout
        assert _COOKIE not in result.stdout


class TestAuthExportNotAuthenticated:
    """Without a stored token the command exits with AUTH_REQUIRED (4)."""

    def test_missing_token_exits_four_without_writing_file(self, runner, tmp_path) -> None:
        target = tmp_path / "creds.json"
        result = runner.invoke(main, ["auth", "export", "--output", str(target)])

        assert result.exit_code == 4
        assert not target.exists()

    def test_missing_token_human_mode_stderr_message(self, runner, tmp_path) -> None:
        result = runner.invoke(main, ["auth", "export", "--output", str(tmp_path / "creds.json")])

        assert result.exit_code == 4
        assert "pxcli auth login" in result.stderr

    def test_missing_token_json_mode_error_envelope(self, runner) -> None:
        result = runner.invoke(main, ["auth", "export", "--json"])

        assert result.exit_code == 4
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "authentication_required"


class TestAuthExportNeverLeaksCredentials:
    """Credential material must never reach console or log output."""

    def test_token_absent_from_output_stderr_and_logs(
        self, runner, tmp_path, caplog, stored_credentials
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="perplexity_cli")
        target = tmp_path / "creds.json"

        # --verbose keeps INFO logging enabled through setup_logging.
        result = runner.invoke(
            main, ["--verbose", "auth", "export", "--json", "--output", str(target)]
        )

        assert result.exit_code == 0
        assert _TOKEN not in result.output
        assert _TOKEN not in result.stderr
        assert _COOKIE not in result.output
        assert _COOKIE not in result.stderr
        assert _TOKEN not in caplog.text
        assert _COOKIE not in caplog.text
        assert caplog.text  # the run did log (redacted) information
