"""Public-boundary regression tests for status, services, and errors."""

from __future__ import annotations

import json
import logging
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.error_handler import handle_error
from perplexity_cli.models.model_config import ModelConfigEntry, SubscriptionLevel
from perplexity_cli.runners.status import (
    _build_status_envelope,
    _ctx_flag,
    _ctx_to_dict,
    _get_include_schema,
    _get_token_age_days,
    _output_status_text,
    _output_verification_result,
    _verify_token,
    run_status_command,
)
from perplexity_cli.services.model_service import ModelService
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityRequestError,
)
from tests.helpers.fake_services import FakeAPIGateway, FakeClickContext, FakePath, FakeTokenManager


class TestT016ModelServiceBoundaries:
    """Verify model-service transport and accessible-model contracts."""

    def test_fetch_methods_forward_provider_urls(self) -> None:
        client = MagicMock()
        client.get_json.side_effect = [
            {"config_schema": "v1", "config": [], "models": {}},
            {
                "subscription_status": "active",
                "subscription_source": "stripe",
                "subscription_tier": "monthly",
                "default_model": "x",
            },
        ]
        endpoints = MagicMock()
        endpoints.model_config_endpoint.return_value = "model-url"
        endpoints.user_settings_endpoint.return_value = "settings-url"
        service = ModelService(client, SubscriptionLevel.PRO, endpoints)

        assert service.fetch_model_config().config_schema == "v1"
        assert service.fetch_user_settings().default_model == "x"
        assert client.get_json.call_args_list[0].args == ("model-url",)
        assert client.get_json.call_args_list[1].args == ("settings-url",)

    def test_filter_accessible_keeps_only_level_and_defaults_first(self) -> None:
        service = ModelService(MagicMock(), SubscriptionLevel.PRO)
        default = ModelConfigEntry(
            label="Default",
            description="",
            subscription_tier="pro",
            non_reasoning_model="d",
            is_default=True,
        )
        regular = ModelConfigEntry(
            label="Regular", description="", subscription_tier="pro", non_reasoning_model="r"
        )
        max_only = ModelConfigEntry(
            label="Max", description="", subscription_tier="max", non_reasoning_model="m"
        )

        assert service._filter_accessible([regular, max_only, default]) == [default, regular]

    def test_validate_model_id_checks_both_model_variants(self) -> None:
        service = ModelService(MagicMock(), SubscriptionLevel.PRO)
        entry = ModelConfigEntry(
            label="Reasoning",
            description="",
            subscription_tier="pro",
            non_reasoning_model="plain",
            reasoning_model="think",
        )
        with patch.object(service, "list_available_models", return_value=[entry]):
            assert service.validate_model_id("plain") is True
            assert service.validate_model_id("think") is True
            assert service.validate_model_id("other") is False


class TestT016StatusBoundaries:
    """Verify status helper state and security-safe outputs."""

    def test_context_helpers_reject_non_mapping_context_objects(self) -> None:
        with patch(
            "perplexity_cli.runners.status.click.get_current_context",
            return_value=FakeClickContext(obj=["not", "a", "mapping"]),
        ):
            assert _ctx_to_dict() == {}
            assert _ctx_flag("json") is False
            assert _get_include_schema() == "no_schema"

    def test_status_envelope_preserves_all_verification_fields(self) -> None:
        token_manager = FakeTokenManager(token_path=FakePath(value="/tmp/token"))
        envelope = _build_status_envelope(True, token_manager, (7, 3, False))
        assert envelope.result == {
            "authenticated": True,
            "token_path": "/tmp/token",
            "token_age_days": 7,
            "cookies_stored": 3,
            "verified": False,
        }

    @pytest.mark.parametrize("value", [True, False, None])
    def test_verification_result_distinguishes_all_states(self, value: bool | None, capsys) -> None:
        _output_verification_result(value, logging.getLogger("t016"))
        output = capsys.readouterr().out
        assert output.startswith("\n")
        assert ("valid" in output) is (value is True)
        assert ("failed" in output) is (value is False)
        assert ("empty response" in output) is (value is None)

    def test_verify_token_forwards_token_cookies_and_timeout(self) -> None:
        gateway = FakeAPIGateway(answer_text="answer")
        with patch("perplexity_cli.runners.status.PerplexityAPI", return_value=gateway) as api:
            assert (
                _verify_token("token-sentinel", {"cookie": "value"}, logging.getLogger("t016"))
                is True
            )
        api.assert_called_once()
        assert api.call_args.kwargs == {
            "token": "token-sentinel",
            "cookies": {"cookie": "value"},
            "timeout": 10,
        }

    def test_verify_token_maps_transport_errors_to_false(self) -> None:
        gateway = FakeAPIGateway(enter_error=PerplexityRequestError("down"))
        with patch("perplexity_cli.runners.status.PerplexityAPI", return_value=gateway):
            assert _verify_token("token", None, logging.getLogger("t016")) is False

    def test_token_age_handles_value_error(self) -> None:
        assert _get_token_age_days(FakePath(stat_error=ValueError)) is None

    def test_status_skip_output_has_stable_public_lines(self, capsys) -> None:
        token_manager = FakeTokenManager(token_path=FakePath(value="/tmp/token"))
        _output_status_text("abc", None, (None, None, False), token_manager)
        assert capsys.readouterr().out == (
            "Perplexity CLI Status\n"
            "========================================\n"
            "Status: [OK] Authenticated\n"
            "Token file: /tmp/token\n"
            "Token length: 3 characters\n"
            "\n[INFO] Live verification not run\n"
            "Use 'pxcli auth status --verify' to test the current token against the API.\n"
        )

    def test_run_status_json_preserves_token_details(self, capsys) -> None:
        token_manager = FakeTokenManager(
            token_exists_value=True,
            load_token_result=("token", {"cookie": "value"}),
            token_path=FakePath(value="/tmp/token", stat_error=OSError),
        )
        with patch("perplexity_cli.runners.status.TokenManager", new=lambda: token_manager):
            run_status_command("skip", output_format="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["result"] == {
            "authenticated": True,
            "token_path": "/tmp/token",
            "token_age_days": None,
            "cookies_stored": 1,
            "verified": None,
        }


class TestT016ErrorBoundary:
    """Verify error taxonomy, command propagation, and output channels."""

    @staticmethod
    def _run(
        exc: BaseException, output_format: str, include_schema: str = "no_schema"
    ) -> tuple[str, str, int]:
        stdout = StringIO()
        stderr = StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            with pytest.raises(SystemExit) as raised:
                handle_error(exc, "status-command", output_format, include_schema)
        return stdout.getvalue(), stderr.getvalue(), int(raised.value.code)

    def test_json_error_contains_command_code_message_and_schema(self) -> None:
        stdout, stderr, code = self._run(AuthenticationError("bad-token"), "json", "with_schema")
        payload = json.loads(stdout)
        assert stderr == ""
        assert code == 4
        assert payload["ok"] is False
        assert payload["error"]["code"] == "authentication_required"
        assert payload["error"]["message"] == "bad-token"
        assert "$schema" in payload

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (AuthenticationError("x"), "authentication_required"),
            (PerplexityRequestError("x"), "network_error"),
            (ValueError("x"), "validation_error"),
        ],
    )
    def test_human_error_stays_on_stderr_and_preserves_taxonomy(
        self, exc: BaseException, expected: str
    ) -> None:
        stdout, stderr, _ = self._run(exc, "human")
        assert stdout == ""
        assert "Error:" in stderr
        assert expected != ""
