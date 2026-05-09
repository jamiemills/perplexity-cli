"""Tests for --timeout and --json flag behaviour in the query pipeline."""

import json
from contextlib import ExitStack
from unittest.mock import Mock, patch

from perplexity_cli.api.models import Answer
from perplexity_cli.query_runner import run_query_command


def _make_api_mock(answer: Answer | None = None):
    """Create a context-manager-compatible PerplexityAPI mock."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    if answer is not None:
        mock_api.get_complete_answer.return_value = answer
    return mock_api


def _apply_standard_patches(stack, mock_api, api_class_mock=None):
    """Apply standard patches to an ExitStack. Returns the API class mock."""
    stack.enter_context(
        patch("perplexity_cli.auth.token_manager.TokenManager", return_value=Mock())
    )
    stack.enter_context(
        patch(
            "perplexity_cli.auth.utils.load_token_optional",
            return_value=("token-123", None),
        )
    )
    stack.enter_context(
        patch("perplexity_cli.query_runner.resolve_attachment_urls", return_value=[])
    )
    cls_mock = api_class_mock or Mock(return_value=mock_api)
    stack.enter_context(patch("perplexity_cli.api.endpoints.PerplexityAPI", cls_mock))
    stack.enter_context(
        patch("perplexity_cli.query_runner.build_final_query", side_effect=lambda q: q)
    )
    return cls_mock


class TestTimeoutFlag:
    """Test --timeout flag passthrough."""

    def test_timeout_passed_to_api(self):
        """When ctx_obj has timeout=10, PerplexityAPI is called with timeout=10."""
        answer = Answer(text="Answer", references=[])
        mock_api = _make_api_mock(answer)
        api_cls = Mock(return_value=mock_api)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api, api_class_mock=api_cls)
            run_query_command(
                ctx_obj={"debug": False, "timeout": 10},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        api_cls.assert_called_once()
        assert api_cls.call_args.kwargs.get("timeout") == 10

    def test_no_timeout_uses_default(self):
        """When ctx_obj has no timeout, PerplexityAPI is called with timeout=None."""
        answer = Answer(text="Answer", references=[])
        mock_api = _make_api_mock(answer)
        api_cls = Mock(return_value=mock_api)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api, api_class_mock=api_cls)
            run_query_command(
                ctx_obj={"debug": False},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        api_cls.assert_called_once()
        assert api_cls.call_args.kwargs.get("timeout") is None


class TestJsonFlag:
    """Test --json flag on query."""

    def test_json_produces_envelope(self, capsys):
        """When json=True, stdout contains valid JSON with 'ok' and 'result' keys."""
        answer = Answer(text="JSON answer", references=[])
        mock_api = _make_api_mock(answer)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            run_query_command(
                ctx_obj={"debug": False, "json": True},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert "result" in data

    def test_json_envelope_has_answer(self, capsys):
        """Result dict contains 'answer' key."""
        answer = Answer(text="The answer text", references=[])
        mock_api = _make_api_mock(answer)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            run_query_command(
                ctx_obj={"debug": False, "json": True},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["result"]["answer"] == "The answer text"

    def test_json_non_streaming_no_raw_text(self, capsys):
        """When json=True, output is valid JSON (not raw text)."""
        answer = Answer(text="Some answer", references=[])
        mock_api = _make_api_mock(answer)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            run_query_command(
                ctx_obj={"debug": False, "json": True},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)

    def test_no_json_produces_formatted_text(self, capsys):
        """When json=False, output is normal text (no JSON envelope)."""
        answer = Answer(text="Plain text answer", references=[])
        mock_api = _make_api_mock(answer)

        with ExitStack() as stack:
            _apply_standard_patches(stack, mock_api)
            run_query_command(
                ctx_obj={"debug": False, "json": False},
                query_text="test",
                output_format="plain",
                strip_references=False,
                stream=False,
                attachments_str=(),
            )

        captured = capsys.readouterr()
        assert "Plain text answer" in captured.out
        # Should NOT be a JSON envelope
        try:
            data = json.loads(captured.out)
            assert "ok" not in data
        except json.JSONDecodeError:
            pass  # Expected -- it's plain text
