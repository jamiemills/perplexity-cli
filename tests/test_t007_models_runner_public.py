"""T007 public-boundary tests for the models command runner."""

from __future__ import annotations

import json
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock

import pytest

from perplexity_cli.envelope import envelope_to_dict
from perplexity_cli.models.model_config import ModelConfigEntry, SubscriptionLevel
from perplexity_cli.runners import models
from perplexity_cli.utils.config import get_user_settings_endpoint
from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, PerplexityRequestError


class _ClientContextStub:
    """Context-manager shim yielding the wrapped client without suppression."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __enter__(self) -> Any:
        return self._client

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


def _entry(model_id: str = "sonar") -> ModelConfigEntry:
    """Create one representative API model entry."""
    return ModelConfigEntry(
        label="Search",
        description="Fast answers",
        subscription_tier="pro",
        non_reasoning_model=model_id,
        reasoning_model="sonar-reasoning",
        is_default=True,
    )


def _patch_runner(monkeypatch: pytest.MonkeyPatch, service: MagicMock) -> None:
    """Stub authentication and network setup for the public runner call."""
    monkeypatch.setattr(models, "_resolve_auth", lambda: ("token", {"sid": "cookie"}))
    monkeypatch.setattr(
        models, "_create_rest_client", lambda token, cookies: _ClientContextStub(object())
    )
    monkeypatch.setattr(models, "_detect_subscription_level", lambda client: SubscriptionLevel.PRO)
    monkeypatch.setattr(models, "_create_model_service", lambda client, level: service)


def test_public_runner_emits_exact_json_result_and_schema_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON mode exposes model fields and forwards schema inclusion."""
    service = MagicMock()
    service.list_available_models.return_value = [_entry()]
    _patch_runner(monkeypatch, service)
    write_envelope = MagicMock(
        side_effect=lambda envelope, include_schema: print(json.dumps(envelope_to_dict(envelope)))
    )
    monkeypatch.setattr(models, "write_envelope", write_envelope)

    models.run_models_list_command({"json": True, "schema": True})

    output = json.loads(capsys.readouterr().out)
    assert output["command"] == "pxcli models list"
    assert output["result"]["models"] == [
        {
            "model_id": "sonar",
            "label": "Search",
            "tier": "pro",
            "description": "Fast answers",
            "reasoning_model": "sonar-reasoning",
            "is_default": True,
        }
    ]
    write_envelope.assert_called_once()
    assert write_envelope.call_args.kwargs["include_schema"] == "with_schema"


def test_public_runner_human_mode_reports_http_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Human mode reports HTTP failures as actionable stderr and exits one."""
    service = MagicMock()
    service.list_available_models.side_effect = PerplexityHTTPStatusError("Forbidden")
    _patch_runner(monkeypatch, service)

    with pytest.raises(SystemExit) as exc_info:
        models.run_models_list_command(None)

    assert exc_info.value.code == 1
    assert "Failed to fetch models: Forbidden" in capsys.readouterr().err


def test_public_runner_human_mode_reports_request_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Human mode distinguishes network failures from HTTP failures."""
    service = MagicMock()
    service.list_available_models.side_effect = PerplexityRequestError("offline")
    _patch_runner(monkeypatch, service)

    with pytest.raises(SystemExit) as exc_info:
        models.run_models_list_command({"json": False, "schema": False})

    assert exc_info.value.code == 1
    assert "Network error: offline" in capsys.readouterr().err


def test_subscription_detection_falls_back_to_pro_on_invalid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed settings do not prevent authenticated model listing."""
    client = MagicMock()
    client.get_json.side_effect = ValueError("bad settings")
    logger = MagicMock()
    monkeypatch.setattr(models, "get_logger", lambda: logger)

    assert models._detect_subscription_level(client) is SubscriptionLevel.PRO
    logger.warning.assert_called_once_with(
        "Could not detect subscription level, defaulting to Pro: %s",
        client.get_json.side_effect,
    )


def test_public_runner_passes_auth_dependencies_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public runner resolves auth with the real dependency arguments."""
    logger = MagicMock()
    token_manager = object()
    auth_result = ("token", {"sid": "cookie"})
    execute = MagicMock()
    monkeypatch.setattr(models, "get_logger", lambda: logger)
    monkeypatch.setattr(models, "TokenManager", lambda: token_manager)
    load_token = MagicMock(return_value=auth_result)
    monkeypatch.setattr(models, "load_token_optional", load_token)
    monkeypatch.setattr(models, "_execute_models_list", execute)

    models.run_models_list_command({"json": False, "schema": False})

    load_token.assert_called_once_with(token_manager, logger)
    execute.assert_called_once_with("token", {"sid": "cookie"}, "human", "no_schema")


def test_public_runner_builds_rest_client_with_auth_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing path preserves both token and cookies in the REST client."""
    auth_context = MagicMock()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    rest_client = MagicMock(return_value=client)
    service = MagicMock()
    service.list_available_models.return_value = []
    monkeypatch.setattr(models, "AuthContext", auth_context)
    monkeypatch.setattr(models, "RestClient", rest_client)
    monkeypatch.setattr(models, "_resolve_auth", lambda: ("token", {"sid": "cookie"}))
    monkeypatch.setattr(models, "_create_model_service", lambda client, level: service)
    monkeypatch.setattr(models, "_output_json", MagicMock())

    models.run_models_list_command({"json": True, "schema": True})

    auth_context.assert_called_once_with(token="token", cookies={"sid": "cookie"})
    rest_client.assert_called_once_with(auth=auth_context.return_value)
    client.get_json.assert_called_once()


def test_public_runner_detects_subscription_and_preserves_output_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid settings response selects the service tier and JSON schema mode."""
    client = MagicMock()
    client.get_json.return_value = {"subscription_status": "active"}
    service = MagicMock()
    service.list_available_models.return_value = []
    create_service = MagicMock(return_value=service)
    output_json = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(models, "_resolve_auth", lambda: ("token", None))
    monkeypatch.setattr(
        models, "_create_rest_client", lambda token, cookies: _ClientContextStub(client)
    )
    monkeypatch.setattr(models, "_create_model_service", create_service)
    monkeypatch.setattr(models, "_output_json", output_json)
    monkeypatch.setattr(models, "get_logger", lambda: logger)

    models.run_models_list_command({"json": True, "schema": True})

    create_service.assert_called_once_with(client, SubscriptionLevel.PRO)
    output_json.assert_called_once_with([], "with_schema")
    logger.debug.assert_called_once_with("Detected subscription level: %s", "pro")


def test_public_runner_uses_settings_endpoint_and_free_tier(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public listing path passes a valid free-tier response to the service."""
    client = MagicMock()
    client.get_json.return_value = {
        "subscription_status": "none",
        "subscription_source": "none",
        "subscription_tier": "null",
        "default_model": "turbo",
    }
    service = MagicMock()
    service.list_available_models.return_value = []
    create_service = MagicMock(return_value=service)
    monkeypatch.setattr(models, "_resolve_auth", lambda: ("token", None))
    monkeypatch.setattr(
        models, "_create_rest_client", lambda token, cookies: _ClientContextStub(client)
    )
    monkeypatch.setattr(models, "_create_model_service", create_service)

    models.run_models_list_command(None)

    assert capsys.readouterr().out == "No models available.\n"
    client.get_json.assert_called_once_with(get_user_settings_endpoint())
    create_service.assert_called_once_with(client, SubscriptionLevel.FREE)


def test_public_runner_authentication_failure_terminates_before_listing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing credentials produce only the authentication error and stop execution."""
    logger = MagicMock()
    execute = MagicMock()
    monkeypatch.setattr(models, "_resolve_auth", lambda: (None, {"sid": "stale"}))
    monkeypatch.setattr(models, "get_logger", lambda: logger)
    monkeypatch.setattr(models, "_execute_models_list", execute)

    with pytest.raises(SystemExit) as exc_info:
        models.run_models_list_command({"json": True, "schema": True})

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.out == ""
    assert captured.err == "[ERROR] Authentication required. Run 'pxcli auth login' first.\n"
    logger.error.assert_called_once_with("Model listing attempted without authentication")
    execute.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected_error", "expected_log_message"),
    [
        (
            PerplexityHTTPStatusError("Forbidden"),
            "[ERROR] Failed to fetch models: Forbidden\n",
            "HTTP error fetching models: %s",
        ),
        (
            PerplexityRequestError("offline"),
            "[ERROR] Network error: offline\n",
            "Network error fetching models: %s",
        ),
        (
            ValueError("bad response"),
            "[ERROR] Unexpected error: bad response\n",
            "Unexpected error fetching models: %s",
        ),
    ],
)
def test_public_runner_human_errors_preserve_classification_and_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    expected_error: str,
    expected_log_message: str,
) -> None:
    """Human mode emits the matching error text and logs the matching category."""
    logger = MagicMock()
    service = MagicMock()
    service.list_available_models.side_effect = failure
    _patch_runner(monkeypatch, service)
    monkeypatch.setattr(models, "get_logger", lambda: logger)

    with pytest.raises(SystemExit) as exc_info:
        models.run_models_list_command({"json": False, "schema": False})

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == expected_error
    logger.error.assert_called_once_with(expected_log_message, failure)


def test_public_runner_human_path_passes_exact_mode_and_renders(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Human mode uses the exact non-JSON output path and schema value."""
    entry = _entry()
    service = MagicMock()
    service.list_available_models.return_value = [entry]
    _patch_runner(monkeypatch, service)

    models.run_models_list_command({"json": False, "schema": True})

    assert "sonar" in capsys.readouterr().out


def test_public_runner_json_error_forwards_exception_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON failures use the structured error handler with exact arguments."""
    service = MagicMock()
    failure = ValueError("bad response")
    service.list_available_models.side_effect = failure
    _patch_runner(monkeypatch, service)
    handle_error = MagicMock(side_effect=RuntimeError("stopped"))
    monkeypatch.setattr(models, "handle_error", handle_error)

    with pytest.raises(RuntimeError, match="stopped"):
        models.run_models_list_command({"json": True, "schema": False})

    handle_error.assert_called_once_with(failure, "pxcli models list", output_format="json")


def test_public_runner_human_path_reports_unexpected_error_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unexpected human-mode failures retain their classification and message."""
    logger = MagicMock()
    service = MagicMock()
    service.list_available_models.side_effect = ValueError("bad response")
    _patch_runner(monkeypatch, service)
    monkeypatch.setattr(models, "get_logger", lambda: logger)

    with pytest.raises(SystemExit) as exc_info:
        models.run_models_list_command(None)

    assert exc_info.value.code == 1
    assert "Unexpected error: bad response" in capsys.readouterr().err
    logger.error.assert_called_once_with(
        "Unexpected error fetching models: %s",
        service.list_available_models.side_effect,
    )
