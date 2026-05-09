"""Tests for JSON envelope output from all runner modules."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from perplexity_cli.runners.auth import run_auth_command, run_logout_command
from perplexity_cli.runners.config import (
    run_clear_style_command,
    run_configure_command,
    run_set_config_command,
    run_show_config_command,
    run_view_style_command,
)
from perplexity_cli.runners.skill import run_show_skill_command
from perplexity_cli.runners.status import run_doctor_security_command, run_status_command


def _parse_json_stdout(captured) -> dict:
    """Parse the JSON envelope from captured stdout."""
    return json.loads(captured.out.strip())


class TestAuthLoginJson:
    """JSON output from run_auth_command()."""

    @patch("perplexity_cli.utils.config.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_json_output_has_envelope(self, mock_auth, mock_tm_class, _mock_cookies, capsys):
        """Success envelope is emitted with correct structure."""
        mock_auth.return_value = ("token-abc", {"__cf_bm": "val"})
        mock_tm = Mock()
        mock_tm.token_path = Path("/tmp/token.json")
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": True}, port=9222)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli auth login"

    @patch("perplexity_cli.utils.config.get_save_cookies_enabled", return_value=True)
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    @patch("perplexity_cli.auth.oauth_handler.authenticate_sync")
    def test_json_result_has_token_path(self, mock_auth, mock_tm_class, _mock_cookies, capsys):
        """Result contains token_path and cookies_stored."""
        mock_auth.return_value = ("token-abc", {"a": "1", "b": "2"})
        mock_tm = Mock()
        mock_tm.token_path = Path("/tmp/token.json")
        mock_tm_class.return_value = mock_tm

        run_auth_command({"json": True}, port=9222)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["result"]["token_path"] == "/tmp/token.json"
        assert envelope["result"]["cookies_stored"] == 2


class TestAuthLogoutJson:
    """JSON output from run_logout_command()."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_json_output_credentials_existed(self, mock_tm_class, capsys):
        """Envelope reports credentials_existed correctly."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm_class.return_value = mock_tm

        run_logout_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli auth logout"
        assert envelope["result"]["credentials_existed"] is True

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_json_output_no_credentials(self, mock_tm_class, capsys):
        """Envelope reports credentials_existed=False when none found."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        run_logout_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["result"]["credentials_existed"] is False


class TestAuthStatusJson:
    """JSON output from run_status_command()."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_json_output_authenticated(self, mock_tm_class, capsys):
        """Envelope shows authenticated=True when token exists."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("token-abc", {"cf": "val"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False, json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli auth status"
        assert envelope["result"]["authenticated"] is True
        assert envelope["result"]["cookies_stored"] == 1


class TestConfigShowJson:
    """JSON output from run_show_config_command()."""

    @patch("perplexity_cli.utils.config.get_feature_config_path")
    @patch("perplexity_cli.utils.config.get_feature_config")
    def test_json_output_has_config(self, mock_get_config, mock_get_path, capsys, monkeypatch):
        """Envelope contains config fields."""
        monkeypatch.delenv("PERPLEXITY_SAVE_COOKIES", raising=False)
        monkeypatch.delenv("PERPLEXITY_DEBUG_MODE", raising=False)

        mock_config = Mock()
        mock_config.save_cookies = False
        mock_config.debug_mode = True
        mock_get_config.return_value = mock_config
        mock_get_path.return_value = Path("/home/user/.config/pxcli/config.json")

        run_show_config_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli config show"
        assert envelope["result"]["save_cookies"] is False
        assert envelope["result"]["debug_mode"] is True


class TestConfigSetJson:
    """JSON output from run_set_config_command()."""

    @patch("perplexity_cli.utils.config.clear_feature_config_cache")
    @patch("perplexity_cli.utils.config.set_feature")
    def test_json_output_has_key_value(self, mock_set, mock_clear, capsys):
        """Envelope contains key and value."""
        run_set_config_command("save_cookies", "true", json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli config set"
        assert envelope["result"]["key"] == "save_cookies"
        assert envelope["result"]["value"] is True


class TestStyleSetJson:
    """JSON output from run_configure_command()."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_json_output_has_style(self, mock_sm_class, capsys):
        """Envelope contains the style string."""
        mock_sm = Mock()
        mock_sm_class.return_value = mock_sm

        run_configure_command("Be concise", json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli style set"
        assert envelope["result"]["style"] == "Be concise"


class TestStyleShowJson:
    """JSON output from run_view_style_command()."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_json_output_has_style(self, mock_sm_class, capsys):
        """Envelope contains the current style or null."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "Be formal"
        mock_sm_class.return_value = mock_sm

        run_view_style_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli style show"
        assert envelope["result"]["style"] == "Be formal"


class TestStyleClearJson:
    """JSON output from run_clear_style_command()."""

    @patch("perplexity_cli.utils.style_manager.StyleManager")
    def test_json_output_has_had_style(self, mock_sm_class, capsys):
        """Envelope reports had_style correctly."""
        mock_sm = Mock()
        mock_sm.load_style.return_value = "old style"
        mock_sm_class.return_value = mock_sm

        run_clear_style_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli style clear"
        assert envelope["result"]["had_style"] is True


class TestDoctorSecurityJson:
    """JSON output from run_doctor_security_command()."""

    @patch("perplexity_cli.utils.config.get_feature_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_json_output_has_storage_info(
        self, mock_tm_class, mock_cm_class, mock_get_config, capsys
    ):
        """Envelope contains storage and permission details."""
        mock_tm = Mock()
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.exists.return_value = False
        mock_tm.token_path = mock_token_path
        mock_tm.SECURE_PERMISSIONS = 0o600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cache_path = Mock()
        mock_cache_path.__str__ = Mock(return_value="/tmp/cache.json")
        mock_cache_path.exists.return_value = False
        mock_cm.cache_path = mock_cache_path
        mock_cm.SECURE_PERMISSIONS = 0o600
        mock_cm_class.return_value = mock_cm

        mock_config = Mock()
        mock_config.save_cookies = False
        mock_get_config.return_value = mock_config

        run_doctor_security_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli doctor security"
        assert "storage_backend" in envelope["result"]
        assert "token_path" in envelope["result"]
        assert "cookies_enabled" in envelope["result"]


class TestSkillShowJson:
    """JSON output from run_show_skill_command()."""

    def test_json_output_has_content(self, capsys):
        """Envelope contains skill content."""
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.return_value = (
                "# Skill\nContent here"
            )
            run_show_skill_command(json_mode=True)

        envelope = _parse_json_stdout(capsys.readouterr())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli skill show"
        assert envelope["result"]["content"] == "# Skill\nContent here"
