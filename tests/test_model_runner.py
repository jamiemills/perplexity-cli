"""Tests for the model list runner.

Validates the orchestration of model listing, including auth resolution,
REST client usage, table/JSON output formatting, and error handling.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.models.model_config import (
    ModelConfigEntry,
    ModelConfigResponse,
    ModelInfo,
    SubscriptionLevel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_model_config() -> ModelConfigResponse:
    """Return a realistic ModelConfigResponse for testing."""
    return ModelConfigResponse(
        config_schema="v1",
        models={
            "pplx_pro": ModelInfo(label="Best", description="Auto-select", mode="search"),
            "gpt54": ModelInfo(
                label="GPT-5.4",
                description="OpenAI",
                mode="search",
                provider="OPENAI",
            ),
            "gpt55": ModelInfo(
                label="GPT-5.5",
                description="OpenAI top",
                mode="search",
                provider="OPENAI",
            ),
            "claude46sonnet": ModelInfo(
                label="Claude Sonnet 4.6",
                description="Anthropic",
                mode="search",
                provider="ANTHROPIC",
            ),
        },
        config=[
            ModelConfigEntry(
                label="Best",
                description="Auto-select the best model",
                subscription_tier="pro",
                non_reasoning_model="pplx_pro",
                is_default=True,
            ),
            ModelConfigEntry(
                label="GPT-5.4",
                description="OpenAI GPT-5.4",
                subscription_tier="pro",
                non_reasoning_model="gpt54",
                reasoning_model="gpt54_thinking",
            ),
            ModelConfigEntry(
                label="GPT-5.5",
                description="OpenAI GPT-5.5",
                subscription_tier="max",
                non_reasoning_model="gpt55",
                reasoning_model="gpt55_thinking",
            ),
            ModelConfigEntry(
                label="Claude Sonnet 4.6",
                description="Anthropic Claude",
                subscription_tier="pro",
                non_reasoning_model="claude46sonnet",
            ),
        ],
        default_models={"search": "pplx_pro"},
    )


def _mock_model_service(
    model_config: ModelConfigResponse, level: SubscriptionLevel = SubscriptionLevel.PRO
) -> MagicMock:
    """Create a mock ModelService returning models filtered by level."""
    service = MagicMock()
    accessible = [entry for entry in model_config.config if entry.is_accessible(level)]
    service.list_available_models.return_value = accessible
    return service


# ---------------------------------------------------------------------------
# Tests: format_model_table
# ---------------------------------------------------------------------------


class TestFormatModelTable:
    """Tests for the plain-text table formatting helper."""

    def test_formats_table_with_columns(
        self,
        sample_model_config: ModelConfigResponse,
    ) -> None:
        from perplexity_cli.runners.models import format_model_table

        entries = [
            entry
            for entry in sample_model_config.config
            if entry.is_accessible(SubscriptionLevel.PRO)
        ]
        output = format_model_table(entries)

        assert "MODEL ID" in output
        assert "LABEL" in output
        assert "TIER" in output
        assert "pplx_pro" in output
        assert "gpt54" in output
        assert "Best" in output

    def test_empty_entries_returns_message(self) -> None:
        from perplexity_cli.runners.models import format_model_table

        output = format_model_table([])
        assert "No models available" in output

    def test_default_model_marked(
        self,
        sample_model_config: ModelConfigResponse,
    ) -> None:
        from perplexity_cli.runners.models import format_model_table

        entries = [
            entry
            for entry in sample_model_config.config
            if entry.is_accessible(SubscriptionLevel.PRO)
        ]
        output = format_model_table(entries)
        # The default model should have a marker
        assert "(default)" in output.lower() or "*" in output


# ---------------------------------------------------------------------------
# Tests: build_models_json_result
# ---------------------------------------------------------------------------


class TestBuildModelsJsonResult:
    """Tests for the JSON result builder."""

    def test_builds_result_dict(
        self,
        sample_model_config: ModelConfigResponse,
    ) -> None:
        from perplexity_cli.runners.models import build_models_json_result

        entries = [
            entry
            for entry in sample_model_config.config
            if entry.is_accessible(SubscriptionLevel.PRO)
        ]
        result = build_models_json_result(entries)

        assert "models" in result
        assert isinstance(result["models"], list)
        assert len(result["models"]) == 3

    def test_model_dict_has_required_fields(
        self,
        sample_model_config: ModelConfigResponse,
    ) -> None:
        from perplexity_cli.runners.models import build_models_json_result

        entries = [
            entry
            for entry in sample_model_config.config
            if entry.is_accessible(SubscriptionLevel.PRO)
        ]
        result = build_models_json_result(entries)
        model = result["models"][0]

        assert "model_id" in model
        assert "label" in model
        assert "tier" in model
        assert "description" in model

    def test_empty_entries_returns_empty_list(self) -> None:
        from perplexity_cli.runners.models import build_models_json_result

        result = build_models_json_result([])
        assert result["models"] == []

    def test_includes_reasoning_model_when_present(
        self,
        sample_model_config: ModelConfigResponse,
    ) -> None:
        from perplexity_cli.runners.models import build_models_json_result

        entries = [
            entry
            for entry in sample_model_config.config
            if entry.is_accessible(SubscriptionLevel.PRO)
        ]
        result = build_models_json_result(entries)
        # GPT-5.4 has a reasoning model
        gpt54 = next(m for m in result["models"] if m["model_id"] == "gpt54")
        assert gpt54["reasoning_model"] == "gpt54_thinking"

        # Best has no reasoning model
        best = next(m for m in result["models"] if m["model_id"] == "pplx_pro")
        assert best["reasoning_model"] is None


# ---------------------------------------------------------------------------
# Tests: run_models_list_command
# ---------------------------------------------------------------------------


class TestRunModelsListCommand:
    """Tests for the main orchestration function."""

    def test_outputs_table_by_default(
        self,
        sample_model_config: ModelConfigResponse,
        capsys,
    ) -> None:
        from perplexity_cli.runners.models import run_models_list_command

        mock_service = _mock_model_service(sample_model_config)
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            run_models_list_command(ctx_obj=None)

        captured = capsys.readouterr()
        assert "MODEL ID" in captured.out
        assert "pplx_pro" in captured.out

    def test_pro_user_does_not_see_max_models(
        self,
        sample_model_config: ModelConfigResponse,
        capsys,
    ) -> None:
        from perplexity_cli.runners.models import run_models_list_command

        mock_service = _mock_model_service(sample_model_config, SubscriptionLevel.PRO)
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            run_models_list_command(ctx_obj=None)

        captured = capsys.readouterr()
        assert "pplx_pro" in captured.out
        assert "gpt54" in captured.out
        # Max-only model should be excluded
        assert "gpt55" not in captured.out

    def test_outputs_json_envelope_when_json_mode(
        self,
        sample_model_config: ModelConfigResponse,
        capsys,
    ) -> None:
        from perplexity_cli.runners.models import run_models_list_command

        mock_service = _mock_model_service(sample_model_config)
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            run_models_list_command(ctx_obj={"json": True, "schema": False})

        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["ok"] is True
        assert data["command"] == "pxcli models list"
        assert "models" in data["result"]

    def test_exits_on_auth_failure(self, capsys) -> None:
        from perplexity_cli.runners.models import run_models_list_command

        with patch(
            "perplexity_cli.runners.models._resolve_auth",
            return_value=(None, None),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run_models_list_command(ctx_obj=None)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "authentication" in captured.err.lower()

    def test_exits_on_http_error(
        self,
        sample_model_config: ModelConfigResponse,
        capsys,
    ) -> None:
        from perplexity_cli.runners.models import run_models_list_command
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_service = MagicMock()
        mock_service.list_available_models.side_effect = PerplexityHTTPStatusError(
            "Forbidden",
        )
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run_models_list_command(ctx_obj=None)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "error" in captured.err.lower() or "ERROR" in captured.err

    def test_exits_on_network_error(self, capsys) -> None:
        from perplexity_cli.runners.models import run_models_list_command
        from perplexity_cli.utils.exceptions import PerplexityRequestError

        mock_service = MagicMock()
        mock_service.list_available_models.side_effect = PerplexityRequestError(
            "Connection refused",
        )
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run_models_list_command(ctx_obj=None)

            assert exc_info.value.code == 1

    def test_exits_on_unexpected_error(self, capsys) -> None:
        from perplexity_cli.runners.models import run_models_list_command

        mock_service = MagicMock()
        mock_service.list_available_models.side_effect = RuntimeError("unexpected")
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run_models_list_command(ctx_obj=None)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "unexpected" in captured.err.lower()

    def test_json_mode_error_calls_handle_error(self, capsys) -> None:
        from perplexity_cli.runners.models import run_models_list_command
        from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError

        mock_service = MagicMock()
        mock_service.list_available_models.side_effect = PerplexityHTTPStatusError(
            "Server error",
        )
        with (
            patch(
                "perplexity_cli.runners.models._create_model_service",
                return_value=mock_service,
            ),
            patch(
                "perplexity_cli.runners.models._resolve_auth",
                return_value=("token", {}),
            ),
            patch(
                "perplexity_cli.runners.models._create_rest_client",
                return_value=MagicMock(),
            ),
            patch(
                "perplexity_cli.runners.models._detect_subscription_level",
                return_value=SubscriptionLevel.PRO,
            ),
            patch("perplexity_cli.error_handler.handle_error") as mock_handle,
        ):
            # handle_error in json_mode calls sys.exit internally
            mock_handle.side_effect = SystemExit(1)
            with pytest.raises(SystemExit):
                run_models_list_command(ctx_obj={"json": True, "schema": False})

            mock_handle.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: _resolve_auth
# ---------------------------------------------------------------------------


class TestResolveAuth:
    """Tests for the auth resolution helper."""

    def test_returns_token_and_cookies(self) -> None:
        from perplexity_cli.runners.models import _resolve_auth

        with (
            patch("perplexity_cli.auth.token_manager.TokenManager") as mock_tm_cls,
            patch("perplexity_cli.auth.utils.load_token_optional") as mock_load,
        ):
            mock_load.return_value = ("tok-123", {"cf": "cookie"})
            result = _resolve_auth()

        assert result == ("tok-123", {"cf": "cookie"})
        mock_tm_cls.assert_called_once()

    def test_returns_none_when_no_token(self) -> None:
        from perplexity_cli.runners.models import _resolve_auth

        with (
            patch("perplexity_cli.auth.token_manager.TokenManager"),
            patch("perplexity_cli.auth.utils.load_token_optional") as mock_load,
        ):
            mock_load.return_value = (None, None)
            result = _resolve_auth()

        assert result == (None, None)


# ---------------------------------------------------------------------------
# Tests: _create_model_service
# ---------------------------------------------------------------------------


class TestCreateRestClient:
    """Tests for the REST client factory helper."""

    def test_creates_client_with_auth_context(self) -> None:
        from perplexity_cli.runners.models import _create_rest_client

        with patch("perplexity_cli.api.rest_client.RestClient") as mock_client_cls:
            _create_rest_client("tok-123", {"cf": "cookie"})

        mock_client_cls.assert_called_once()


class TestCreateModelService:
    """Tests for the service factory helper."""

    def test_creates_service_with_given_level(self) -> None:
        from perplexity_cli.runners.models import _create_model_service

        mock_client = MagicMock()
        with patch("perplexity_cli.services.model_service.ModelService") as mock_svc_cls:
            _create_model_service(mock_client, SubscriptionLevel.PRO)

        call_kwargs = mock_svc_cls.call_args
        assert call_kwargs.kwargs["subscription_level"] == SubscriptionLevel.PRO

    def test_passes_rest_client_to_service(self) -> None:
        from perplexity_cli.runners.models import _create_model_service

        mock_client = MagicMock()
        with patch("perplexity_cli.services.model_service.ModelService") as mock_svc_cls:
            _create_model_service(mock_client, SubscriptionLevel.MAX)

        call_kwargs = mock_svc_cls.call_args
        assert call_kwargs.kwargs["rest_client"] is mock_client


class TestDetectSubscriptionLevel:
    """Tests for the subscription level detection helper."""

    def test_returns_pro_for_active_subscriber(self) -> None:
        from perplexity_cli.runners.models import _detect_subscription_level

        mock_client = MagicMock()
        mock_client.get_json.return_value = {
            "subscription_status": "active",
            "subscription_source": "stripe",
            "subscription_tier": "monthly",
            "default_model": "turbo",
        }
        level = _detect_subscription_level(mock_client)
        assert level == SubscriptionLevel.PRO

    def test_returns_free_for_inactive_user(self) -> None:
        from perplexity_cli.runners.models import _detect_subscription_level

        mock_client = MagicMock()
        mock_client.get_json.return_value = {
            "subscription_status": "none",
            "subscription_source": "none",
            "subscription_tier": "null",
            "default_model": "turbo",
        }
        level = _detect_subscription_level(mock_client)
        assert level == SubscriptionLevel.FREE

    def test_defaults_to_pro_on_api_error(self) -> None:
        from perplexity_cli.runners.models import _detect_subscription_level

        mock_client = MagicMock()
        mock_client.get_json.side_effect = RuntimeError("API failure")
        level = _detect_subscription_level(mock_client)
        assert level == SubscriptionLevel.PRO


# ---------------------------------------------------------------------------
# Tests: _output_json
# ---------------------------------------------------------------------------


class TestOutputJson:
    """Tests for the JSON output helper."""

    def test_writes_json_envelope(self, capsys) -> None:
        from perplexity_cli.runners.models import _output_json

        entries = [
            ModelConfigEntry(
                label="Test",
                description="Test model",
                subscription_tier="pro",
                non_reasoning_model="test_model",
            ),
        ]
        _output_json(entries, include_schema=False)

        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["ok"] is True
        assert data["command"] == "pxcli models list"
        assert len(data["result"]["models"]) == 1
