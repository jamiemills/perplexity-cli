"""Tests for the status command runner."""

import json
import logging
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest

from perplexity_cli.config.models import FeatureConfig
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
from perplexity_cli.utils.exceptions import AuthenticationError, PerplexityRequestError
from tests.helpers.fake_services import (
    FakeAPIGateway,
    FakeCacheManager,
    FakeClickContext,
    FakePath,
    FakeTokenManager,
    FixedClock,
)

_LOGGER = logging.getLogger("test-status-runner")


@contextmanager
def _patch_doctor_dependencies(tm, cache_manager, feature_config):
    """Patch the doctor command's dependency construction points with fakes."""
    with (
        patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm),
        patch("perplexity_cli.runners.status.ThreadCacheManager", new=lambda: cache_manager),
        patch("perplexity_cli.runners.status.get_feature_config", new=lambda: feature_config),
    ):
        yield


def _status_token_manager() -> FakeTokenManager:
    """Build a token-manager fake with a fixed token-file mtime."""
    return FakeTokenManager(token_path=FakePath(value="/tmp/token.json", st_mtime=1700000000.0))


# ---------------------------------------------------------------------------
# _get_json_mode_from_ctx
# ---------------------------------------------------------------------------


class TestGetJsonModeFromCtx:
    """Tests for _get_json_mode_from_ctx()."""

    @pytest.mark.parametrize(
        ("ctx_obj", "expected"),
        [
            pytest.param(None, "human", id="no-context"),
            pytest.param({"json": True}, "json", id="json-true"),
            pytest.param({}, "human", id="json-missing"),
        ],
    )
    def test_json_mode_from_ctx(self, ctx_obj: object, expected: str) -> None:
        with patch(
            "perplexity_cli.runners.status.click.get_current_context",
            new=lambda *args, **kwargs: None if ctx_obj is None else FakeClickContext(obj=ctx_obj),
        ):
            assert _get_json_mode_from_ctx() == expected


# ---------------------------------------------------------------------------
# _get_token_age_days
# ---------------------------------------------------------------------------


class TestGetTokenAgeDays:
    """Tests for _get_token_age_days()."""

    def test_returns_none_when_path_missing(self, tmp_path) -> None:
        missing = tmp_path / "missing-token.json"
        assert _get_token_age_days(missing) is None

    @pytest.mark.parametrize(
        "stat_error",
        [
            pytest.param(OSError, id="os-error"),
            pytest.param(AttributeError, id="attribute-error"),
            pytest.param(TypeError, id="type-error"),
        ],
    )
    def test_returns_none_on_stat_error(self, stat_error: type[BaseException]) -> None:
        path = FakePath(stat_error=stat_error)
        assert _get_token_age_days(path) is None

    def test_returns_days_since_modified(self) -> None:
        mtime = (FixedClock.NOW - timedelta(days=5)).timestamp()
        path = FakePath(st_mtime=mtime)
        with patch("perplexity_cli.runners.status.datetime", new=FixedClock):
            assert _get_token_age_days(path) == 5


# ---------------------------------------------------------------------------
# _verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    """Tests for _verify_token()."""

    @pytest.mark.parametrize(
        ("gateway", "expected"),
        [
            pytest.param(FakeAPIGateway(answer_text="OK"), True, id="success"),
            pytest.param(FakeAPIGateway(answer_text=""), False, id="empty-response"),
            pytest.param(
                FakeAPIGateway(enter_error=PerplexityRequestError("down")),
                False,
                id="api-error",
            ),
        ],
    )
    def test_verify_token(self, gateway: FakeAPIGateway, expected: bool) -> None:
        with patch(
            "perplexity_cli.runners.status.PerplexityAPI", new=lambda *args, **kwargs: gateway
        ):
            result = _verify_token("token", {}, _LOGGER)
            assert result is expected


# ---------------------------------------------------------------------------
# _output_verification_result
# ---------------------------------------------------------------------------


class TestOutputVerificationResult:
    """Tests for _output_verification_result()."""

    @pytest.mark.parametrize(
        ("verified", "expected_line"),
        [
            pytest.param(True, "\n[OK] Token is valid and working", id="verified"),
            pytest.param(False, "\n[ERROR] Token verification failed", id="failed"),
            pytest.param(
                None,
                "\n[INFO] Token verification returned empty response",
                id="empty",
            ),
        ],
    )
    def test_prints_exact_result(self, verified: object, expected_line: str, capsys) -> None:
        _output_verification_result(verified, _LOGGER)
        assert capsys.readouterr().out == expected_line + "\n"


# ---------------------------------------------------------------------------
# _output_token_modified_time
# ---------------------------------------------------------------------------


class TestOutputTokenModifiedTime:
    """Tests for _output_token_modified_time()."""

    def test_prints_nothing_when_age_is_none(self, capsys) -> None:
        _output_token_modified_time(FakePath(), None)
        assert capsys.readouterr().out == ""

    def test_prints_timestamp_when_age_available(self, capsys) -> None:
        _output_token_modified_time(FakePath(st_mtime=1700000000.0), 5)
        assert "2023-11-14" in capsys.readouterr().out

    def test_handles_stat_error(self, capsys) -> None:
        _output_token_modified_time(FakePath(stat_error=OSError), 5)
        assert "unavailable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _output_status_text
# ---------------------------------------------------------------------------


class TestOutputStatusText:
    """Tests for _output_status_text()."""

    def test_shows_token_length_and_cookies(self, capsys) -> None:
        tm = _status_token_manager()
        _output_status_text("tok", {"c": "v"}, (5, None, False), tm=tm)
        captured = capsys.readouterr()
        assert "3 characters" in captured.out
        assert "1 stored" in captured.out

    def test_shows_live_verification_not_run(self, capsys) -> None:
        tm = _status_token_manager()
        _output_status_text("tok", {}, (5, None, False), tm=tm)
        assert "Live verification not run" in capsys.readouterr().out

    def test_shows_verification_result_when_verify_true(self, capsys) -> None:
        tm = _status_token_manager()
        _output_status_text("tok", {}, (5, True, True), tm=tm)
        assert "Token is valid and working" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _handle_no_token
# ---------------------------------------------------------------------------


class TestHandleNoToken:
    """Tests for _handle_no_token()."""

    def test_human_mode_with_hint(self, capsys) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json"))
        _handle_no_token(output_format="human", tm=tm, show_auth_hint="show")
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
        assert "pxcli auth login" in captured.out

    def test_human_mode_without_hint(self, capsys) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json"))
        _handle_no_token(output_format="human", tm=tm, show_auth_hint="hide")
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
        assert "pxcli auth login" not in captured.out

    def test_json_mode_writes_envelope(self, capsys) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json"))
        _handle_no_token(output_format="json", tm=tm)
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is False


# ---------------------------------------------------------------------------
# _build_status_envelope
# ---------------------------------------------------------------------------


class TestBuildStatusEnvelope:
    """Tests for _build_status_envelope()."""

    def test_builds_authenticated_envelope(self) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json"))
        env = _build_status_envelope(True, tm, (5, 2, True))
        assert env.ok is True
        result = env.result
        assert result["authenticated"] is True
        assert result["token_age_days"] == 5
        assert result["cookies_stored"] == 2
        assert result["verified"] is True

    def test_builds_unauthenticated_envelope(self) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json"))
        env = _build_status_envelope(False, tm)
        assert env.ok is True
        assert env.result["authenticated"] is False


# ---------------------------------------------------------------------------
# _handle_authenticated_status
# ---------------------------------------------------------------------------


class TestHandleAuthenticatedStatus:
    """Tests for _handle_authenticated_status()."""

    def test_json_mode_writes_envelope(self, capsys) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json", st_mtime=1700000000.0))
        _handle_authenticated_status(("tok", {"c": "v"}, "skip", "json"), tm=tm, logger=_LOGGER)
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is True

    def test_human_mode_prints_output(self, capsys) -> None:
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/token.json", st_mtime=1700000000.0))
        _handle_authenticated_status(("tok", {}, "skip", "human"), tm=tm, logger=_LOGGER)
        assert "Authenticated" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_doctor_security
# ---------------------------------------------------------------------------


class TestRunDoctorSecurity:
    """Tests for run_doctor_security_command()."""

    @staticmethod
    def _prepare_secure_files(tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")
        token_file.chmod(0o600)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{}")
        cache_file.chmod(0o600)
        return token_file, cache_file

    def test_json_mode_writes_envelope(self, tmp_path, capsys) -> None:
        token_file, cache_file = self._prepare_secure_files(tmp_path)
        tm = FakeTokenManager(token_path=token_file)
        cache_manager = FakeCacheManager(cache_path=cache_file)
        with _patch_doctor_dependencies(tm, cache_manager, FeatureConfig(save_cookies=False)):
            run_doctor_security_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert "token_path" in envelope["result"]
        assert "cookies_enabled" in envelope["result"]

    def test_human_mode_prints_output(self, tmp_path, capsys) -> None:
        token_file, cache_file = self._prepare_secure_files(tmp_path)
        tm = FakeTokenManager(token_path=token_file)
        cache_manager = FakeCacheManager(cache_path=cache_file)
        with _patch_doctor_dependencies(tm, cache_manager, FeatureConfig(save_cookies=True)):
            run_doctor_security_command(output_format="human")

        captured = capsys.readouterr()
        assert "Perplexity CLI Security" in captured.out
        assert "Cookie storage warning" in captured.out


# ---------------------------------------------------------------------------
# run_status_command (existing tests preserved)
# ---------------------------------------------------------------------------


class TestRunStatusCommand:
    """Tests for run_status_command()."""

    def test_not_authenticated_human(self, capsys):
        """Human output shows not authenticated."""
        tm = FakeTokenManager(token_exists_value=False)
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip")

        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out

    def test_authenticated_human(self, capsys):
        """Human output shows authenticated status."""
        tm = FakeTokenManager(
            token_exists_value=True,
            load_token_result=("token-abc", {"cf": "val"}),
            token_path=FakePath(value="/tmp/token.json", st_mtime=1700000000.0),
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip")

        captured = capsys.readouterr()
        assert "Authenticated" in captured.out

    def test_not_authenticated_json(self, capsys):
        """JSON output shows authenticated=False."""
        tm = FakeTokenManager(
            token_exists_value=False, token_path=FakePath(value="/tmp/token.json")
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip", output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is False

    def test_authenticated_json(self, capsys):
        """JSON output shows authenticated=True with details."""
        tm = FakeTokenManager(
            token_exists_value=True,
            load_token_result=("token-abc", {"cf": "val"}),
            token_path=FakePath(value="/tmp/token.json", st_mtime=1700000000.0),
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip", output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is True
        assert envelope["result"]["token_path"] == "/tmp/token.json"
        assert envelope["result"]["cookies_stored"] == 1


class TestStatusRunnerMutationKillers:
    """Mutation-killing tests for status runner edge cases."""

    def test_describe_file_permissions_none_path(self):
        from perplexity_cli.runners.status import _describe_file_permissions

        assert _describe_file_permissions(None, 0o600) == "not present"

    def test_describe_file_permissions_nonexistent_path(self, tmp_path):
        from perplexity_cli.runners.status import _describe_file_permissions

        missing = tmp_path / "does_not_exist.json"
        assert _describe_file_permissions(missing, 0o600) == "not present"

    def test_describe_file_permissions_secure(self, tmp_path):
        import os

        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "secure.json"
        f.write_text("{}")
        os.chmod(f, 0o600)
        result = _describe_file_permissions(f, 0o600)
        assert result == "secure (0o600)"

    def test_describe_file_permissions_insecure(self, tmp_path):
        import os

        from perplexity_cli.runners.status import _describe_file_permissions

        f = tmp_path / "insecure.json"
        f.write_text("{}")
        os.chmod(f, 0o644)
        result = _describe_file_permissions(f, 0o600)
        assert "insecure" in result
        assert "0o644" in result
        assert "expected 0o600" in result

    def test_output_status_text_no_cookies_no_line(self, capsys):
        tm = _status_token_manager()
        _output_status_text("tok", None, (5, None, False), tm=tm)
        captured = capsys.readouterr()
        assert "Cookies:" not in captured.out

    def test_output_status_text_with_cookies_count(self, capsys):
        tm = _status_token_manager()
        _output_status_text("tok", {"a": "1", "b": "2", "c": "3"}, (5, None, False), tm=tm)
        captured = capsys.readouterr()
        assert "Cookies: 3 stored" in captured.out

    def test_output_status_text_verify_true_verified_false(self, capsys):
        tm = _status_token_manager()
        _output_status_text("tok", {}, (5, False, True), tm=tm)
        captured = capsys.readouterr()
        assert "[ERROR] Token verification failed" in captured.out

    def test_output_status_text_token_length_exact(self, capsys):
        tm = _status_token_manager()
        _output_status_text("abcdef", {}, (0, None, False), tm=tm)
        captured = capsys.readouterr()
        assert "Token length: 6 characters" in captured.out

    def test_get_token_age_days_zero_days(self):
        path = FakePath(st_mtime=FixedClock.NOW.timestamp())
        with patch("perplexity_cli.runners.status.datetime", new=FixedClock):
            assert _get_token_age_days(path) == 0

    def test_build_status_envelope_default_token_info(self):
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/t.json"))
        env = _build_status_envelope(True, tm)
        assert env.result["token_age_days"] is None
        assert env.result["cookies_stored"] == 0
        assert env.result["verified"] is None

    def test_handle_no_token_json_includes_schema_flag(self, capsys):
        tm = FakeTokenManager(token_path=FakePath(value="/tmp/t.json"))
        with patch(
            "perplexity_cli.runners.status.click.get_current_context",
            new=lambda *args, **kwargs: FakeClickContext(obj={}),
        ):
            _handle_no_token(output_format="json", tm=tm)
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["authenticated"] is False

    def test_run_status_auth_error_insecure_permissions(self, capsys):
        tm = FakeTokenManager(
            token_exists_value=True,
            load_token_error=AuthenticationError("insecure permissions"),
            token_path=FakePath(value="/tmp/t.json"),
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip")

        captured = capsys.readouterr()
        assert "Token file has insecure permissions" in captured.out
        assert "chmod 0600" in captured.out

    def test_run_status_empty_token_shows_no_hint(self, capsys):
        tm = FakeTokenManager(
            token_exists_value=True,
            load_token_result=("", None),
            token_path=FakePath(value="/tmp/t.json"),
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm):
            run_status_command(verify="skip")

        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
        assert "pxcli auth login" not in captured.out

    def test_run_status_verify_json_verified_true(self, capsys):
        tm = FakeTokenManager(
            token_exists_value=True,
            load_token_result=("tok", {"c": "v"}),
            token_path=FakePath(value="/tmp/t.json", st_mtime=1700000000.0),
        )
        with (
            patch("perplexity_cli.runners.status.TokenManager", new=lambda: tm),
            patch(
                "perplexity_cli.runners.status.PerplexityAPI",
                new=lambda *args, **kwargs: FakeAPIGateway(answer_text="answer"),
            ),
        ):
            run_status_command(verify="verify", output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["verified"] is True
        assert envelope["result"]["cookies_stored"] == 1

    def test_doctor_security_human_no_cookie_warning(self, tmp_path, capsys):
        tm = FakeTokenManager(token_path=tmp_path / "token.json")
        cache_manager = FakeCacheManager(cache_path=tmp_path / "cache.json")
        with _patch_doctor_dependencies(tm, cache_manager, FeatureConfig(save_cookies=False)):
            run_doctor_security_command(output_format="human")

        captured = capsys.readouterr()
        assert "Cookie storage enabled: False" in captured.out
        assert "Cookie storage warning" not in captured.out

    def test_doctor_security_json_cookies_enabled(self, tmp_path, capsys):
        tm = FakeTokenManager(token_path=tmp_path / "token.json")
        cache_manager = FakeCacheManager(cache_path=tmp_path / "cache.json")
        with _patch_doctor_dependencies(tm, cache_manager, FeatureConfig(save_cookies=True)):
            run_doctor_security_command(output_format="json")

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["result"]["cookies_enabled"] is True
        assert envelope["result"]["token_permissions"] == "not present"
        assert envelope["result"]["cache_permissions"] == "not present"
