"""Tests for the status command runner."""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from perplexity_cli.runners.status import (
    _build_status_envelope,
    _get_json_mode_from_ctx,
    _get_token_age_days,
    _handle_authenticated_status,
    _handle_no_token,
    _output_status_text,
    _output_token_modified_time,
    _output_verification_result,
    _verify_token,
    run_doctor_security_command,
    run_status_command,
)

# ---------------------------------------------------------------------------
# _get_json_mode_from_ctx
# ---------------------------------------------------------------------------


class TestGetJsonModeFromCtx:
    """Tests for _get_json_mode_from_ctx()."""

    def test_returns_false_when_no_context(self) -> None:
        with patch("perplexity_cli.runners.status.click.get_current_context", return_value=None):
            assert _get_json_mode_from_ctx() is False

    def test_returns_true_from_ctx_obj(self) -> None:
        mock_ctx = Mock()
        mock_ctx.obj = {"json": True}
        with patch(
            "perplexity_cli.runners.status.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_json_mode_from_ctx() is True

    def test_returns_false_when_key_missing(self) -> None:
        mock_ctx = Mock()
        mock_ctx.obj = {}
        with patch(
            "perplexity_cli.runners.status.click.get_current_context", return_value=mock_ctx
        ):
            assert _get_json_mode_from_ctx() is False


# ---------------------------------------------------------------------------
# _get_token_age_days
# ---------------------------------------------------------------------------


class TestGetTokenAgeDays:
    """Tests for _get_token_age_days()."""

    def test_returns_none_when_path_missing(self) -> None:
        path = Mock()
        path.stat.side_effect = OSError
        assert _get_token_age_days(path) is None

    def test_returns_days_since_modified(self) -> None:
        path = Mock()
        days_ago = datetime.now() - timedelta(days=5)
        path.stat.return_value = Mock(st_mtime=days_ago.timestamp())
        assert _get_token_age_days(path) == 5


# ---------------------------------------------------------------------------
# _verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    """Tests for _verify_token()."""

    def test_returns_true_on_successful_verification(self) -> None:
        with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.get_complete_answer.return_value = Mock(text="OK")
            mock_api_class.return_value.__enter__.return_value = mock_api

            result = _verify_token("token", {}, Mock())
            assert result is True

    def test_returns_false_on_empty_response(self) -> None:
        with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.get_complete_answer.return_value = Mock(text="")
            mock_api_class.return_value.__enter__.return_value = mock_api

            result = _verify_token("token", {}, Mock())
            assert result is False

    def test_returns_false_on_api_error(self) -> None:
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        with patch("perplexity_cli.api.endpoints.PerplexityAPI") as mock_api_class:
            mock_api_class.return_value.__enter__.side_effect = PerplexityRequestError("down")

            result = _verify_token("token", {}, Mock())
            assert result is False


# ---------------------------------------------------------------------------
# _output_verification_result
# ---------------------------------------------------------------------------


class TestOutputVerificationResult:
    """Tests for _output_verification_result()."""

    def test_prints_ok_when_verified_true(self, capsys) -> None:
        _output_verification_result(True, Mock())
        assert "Token is valid and working" in capsys.readouterr().out

    def test_prints_error_when_verified_false(self, capsys) -> None:
        _output_verification_result(False, Mock())
        assert "Token verification failed" in capsys.readouterr().out

    def test_prints_info_when_verified_none(self, capsys) -> None:
        _output_verification_result(None, Mock())
        assert "empty response" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _output_token_modified_time
# ---------------------------------------------------------------------------


class TestOutputTokenModifiedTime:
    """Tests for _output_token_modified_time()."""

    def test_prints_nothing_when_age_is_none(self, capsys) -> None:
        _output_token_modified_time(Mock(), None)
        assert capsys.readouterr().out == ""

    def test_prints_timestamp_when_age_available(self, capsys) -> None:
        path = Mock()
        path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_token_modified_time(path, 5)
        assert "2023-11-14" in capsys.readouterr().out

    def test_handles_stat_error(self, capsys) -> None:
        path = Mock()
        path.stat.side_effect = OSError
        _output_token_modified_time(path, 5)
        assert "unavailable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _output_status_text
# ---------------------------------------------------------------------------


class TestOutputStatusText:
    """Tests for _output_status_text()."""

    def test_shows_token_length_and_cookies(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("tok", {"c": "v"}, 5, None, verify=False, tm=tm)
        captured = capsys.readouterr()
        assert "3 characters" in captured.out
        assert "1 stored" in captured.out

    def test_shows_live_verification_not_run(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("tok", {}, 5, None, verify=False, tm=tm)
        assert "Live verification not run" in capsys.readouterr().out

    def test_shows_verification_result_when_verify_true(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        _output_status_text("tok", {}, 5, True, verify=True, tm=tm)
        assert "Token is valid and working" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _handle_no_token
# ---------------------------------------------------------------------------


class TestHandleNoToken:
    """Tests for _handle_no_token()."""

    def test_human_mode_with_hint(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        _handle_no_token(json_mode=False, tm=tm, show_auth_hint=True)
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
        assert "pxcli auth login" in captured.out

    def test_human_mode_without_hint(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        _handle_no_token(json_mode=False, tm=tm, show_auth_hint=False)
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
        assert "pxcli auth login" not in captured.out

    def test_json_mode_writes_envelope(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        _handle_no_token(json_mode=True, tm=tm)
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is False


# ---------------------------------------------------------------------------
# _build_status_envelope
# ---------------------------------------------------------------------------


class TestBuildStatusEnvelope:
    """Tests for _build_status_envelope()."""

    def test_builds_authenticated_envelope(self) -> None:
        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        env = _build_status_envelope(True, tm, token_age_days=5, cookies_stored=2, verified=True)
        assert env.ok is True
        result = env.result
        assert result["authenticated"] is True
        assert result["token_age_days"] == 5
        assert result["cookies_stored"] == 2
        assert result["verified"] is True

    def test_builds_unauthenticated_envelope(self) -> None:
        tm = Mock()
        tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        env = _build_status_envelope(False, tm)
        assert env.ok is True
        assert env.result["authenticated"] is False


# ---------------------------------------------------------------------------
# _handle_authenticated_status
# ---------------------------------------------------------------------------


class TestHandleAuthenticatedStatus:
    """Tests for _handle_authenticated_status()."""

    def test_json_mode_writes_envelope(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.__str__ = Mock(return_value="/tmp/token.json")
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)

        _handle_authenticated_status(
            token="tok",
            cookies={"c": "v"},
            verify=False,
            json_mode=True,
            tm=tm,
            logger=Mock(),
        )
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is True

    def test_human_mode_prints_output(self, capsys) -> None:
        tm = Mock()
        tm.token_path = Mock()
        tm.token_path.stat.return_value = Mock(st_mtime=1700000000.0)

        _handle_authenticated_status(
            token="tok",
            cookies={},
            verify=False,
            json_mode=False,
            tm=tm,
            logger=Mock(),
        )
        assert "Authenticated" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_doctor_security
# ---------------------------------------------------------------------------


class TestRunDoctorSecurity:
    """Tests for run_doctor_security_command()."""

    @patch("perplexity_cli.utils.config.get_feature_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_json_mode_writes_envelope(
        self,
        mock_tm_class,
        mock_cm_class,
        mock_feature_config,
        capsys,
    ) -> None:
        mock_tm = Mock()
        mock_tm.token_path = Mock()
        mock_tm.token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_tm.token_path.exists.return_value = True
        mock_tm.token_path.stat.return_value = Mock(st_mode=0o100600)
        mock_tm.SECURE_PERMISSIONS = 0o100600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock()
        mock_cm.cache_path.__str__ = Mock(return_value="/tmp/cache.json")
        mock_cm.cache_path.exists.return_value = True
        mock_cm.cache_path.stat.return_value = Mock(st_mode=0o100600)
        mock_cm.SECURE_PERMISSIONS = 0o100600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=False)

        run_doctor_security_command(json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert "token_path" in envelope["result"]
        assert "cookies_enabled" in envelope["result"]

    @patch("perplexity_cli.utils.config.get_feature_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_human_mode_prints_output(
        self,
        mock_tm_class,
        mock_cm_class,
        mock_feature_config,
        capsys,
    ) -> None:
        mock_tm = Mock()
        mock_tm.token_path = Mock()
        mock_tm.token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_tm.token_path.exists.return_value = True
        mock_tm.token_path.stat.return_value = Mock(st_mode=0o100600)
        mock_tm.SECURE_PERMISSIONS = 0o100600
        mock_tm_class.return_value = mock_tm

        mock_cm = Mock()
        mock_cm.cache_path = Mock()
        mock_cm.cache_path.__str__ = Mock(return_value="/tmp/cache.json")
        mock_cm.cache_path.exists.return_value = True
        mock_cm.cache_path.stat.return_value = Mock(st_mode=0o100600)
        mock_cm.SECURE_PERMISSIONS = 0o100600
        mock_cm_class.return_value = mock_cm

        mock_feature_config.return_value = Mock(save_cookies=True)

        run_doctor_security_command(json_mode=False)

        captured = capsys.readouterr()
        assert "Perplexity CLI Security" in captured.out
        assert "Cookie storage warning" in captured.out


# ---------------------------------------------------------------------------
# run_status_command (existing tests preserved)
# ---------------------------------------------------------------------------


class TestRunStatusCommand:
    """Tests for run_status_command()."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows not authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False)

        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows authenticated status."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("token-abc", {"cf": "val"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False)

        captured = capsys.readouterr()
        assert "Authenticated" in captured.out

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows authenticated=False."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False, json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is False

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows authenticated=True with details."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("token-abc", {"cf": "val"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False, json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is True
        assert envelope["result"]["token_path"] == "/tmp/token.json"
        assert envelope["result"]["cookies_stored"] == 1
