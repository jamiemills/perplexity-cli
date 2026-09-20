"""Integration tests wiring PXCLI_SESSION_LOG into the query flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.api.models import Answer
from perplexity_cli.query_runner import QueryOptions, run_query_command
from perplexity_cli.session_log import SessionLogger
from perplexity_cli.utils.exceptions import UpstreamSchemaError
from tests.helpers.query_deps import patched_dep

if TYPE_CHECKING:
    from pytest import CapSys, MonkeyPatch


def _make_api_mock(answer: Answer | None = None) -> Mock:
    """Create a context-manager-compatible PerplexityAPI mock."""
    mock_api = Mock()
    mock_api.__enter__ = Mock(return_value=mock_api)
    mock_api.__exit__ = Mock(return_value=False)
    if answer is not None:
        mock_api.get_complete_answer.return_value = answer
    return mock_api


def _default_options() -> QueryOptions:
    """Build QueryOptions with sensible test defaults."""
    return QueryOptions(
        output_format="plain",
        strip_references=False,
        stream=False,
        attachments=(),
        model_preference=None,
        request_param_overrides=(),
    )


def _isolate_session_env(monkeypatch: MonkeyPatch, tmp_path: Path, *, enabled: bool) -> None:
    """Pin PXCLI_SESSION_LOG and XDG_DATA_HOME to avoid ambient leakage (DR14)."""
    monkeypatch.delenv("PXCLI_SESSION_LOG", raising=False)
    if enabled:
        monkeypatch.setenv("PXCLI_SESSION_LOG", "true")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def _run_batch_query(answer: Answer | None = None, error: Exception | None = None) -> None:
    """Run a batch query against a mocked API dependency."""
    mock_api = _make_api_mock(answer)
    if error is not None:
        mock_api.get_complete_answer.side_effect = error
    query_logger = Mock()
    query_logger.isEnabledFor.return_value = False

    with (
        patched_dep("TokenManager", Mock(return_value=Mock())),
        patched_dep("load_token_optional", Mock(return_value=("token-123", None))),
        patch(
            "perplexity_cli.query_runner.resolve_attachment_urls", return_value=[], autospec=True
        ),
        patched_dep("PerplexityAPI", Mock(return_value=mock_api)),
        patched_dep("get_logger", lambda: query_logger),
        patch("perplexity_cli.query_runner.build_final_query", return_value="final query"),
    ):
        run_query_command(
            ctx_obj={"debug": False},
            query_text="What is Python?",
            options=_default_options(),
        )


def _read_session_events(tmp_path: Path) -> list[dict[str, object]]:
    """Read events from the single session file under the isolated sessions dir."""
    sessions_dir = tmp_path / "pxcli" / "sessions"
    files = sorted(sessions_dir.glob("*.ndjson"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_query_writes_invocation_and_ok_response(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """An enabled session log records one invocation and one ok response event."""
    _isolate_session_env(monkeypatch, tmp_path, enabled=True)

    _run_batch_query(answer=Answer(text="Test answer", references=[]))

    events = _read_session_events(tmp_path)
    assert len(events) == 2
    invocation, response = events
    assert invocation["type"] == "invocation"
    assert invocation["command"] == "query"
    assert invocation["args"] == {"mode": "batch", "json": False, "stream": False}
    assert response["type"] == "response"
    assert response["ok"] is True
    assert isinstance(response["duration_ms"], int)
    assert invocation["session_id"] == response["session_id"]


def test_query_failure_records_error_response(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CapSys
) -> None:
    """A failing query records a non-ok response with unchanged error behaviour."""
    _isolate_session_env(monkeypatch, tmp_path, enabled=True)

    with pytest.raises(SystemExit) as exc_info:
        _run_batch_query(error=UpstreamSchemaError("bad payload"))

    assert exc_info.value.code == 7
    assert "Error: bad payload" in capsys.readouterr().err
    events = _read_session_events(tmp_path)
    assert len(events) == 2
    assert events[0]["type"] == "invocation"
    assert events[1]["type"] == "response"
    assert events[1]["ok"] is False


def test_env_unset_creates_no_sessions_dir(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """No sessions directory is created when PXCLI_SESSION_LOG is unset."""
    _isolate_session_env(monkeypatch, tmp_path, enabled=False)

    _run_batch_query(answer=Answer(text="Test answer", references=[]))

    assert not (tmp_path / "pxcli").exists()


def test_session_log_create_failure_keeps_query_output(
    monkeypatch: MonkeyPatch, tmp_path: Path, capsys: CapSys
) -> None:
    """An OSError from session logging leaves query output and exit behaviour intact."""
    _isolate_session_env(monkeypatch, tmp_path, enabled=True)
    monkeypatch.setattr(SessionLogger, "create", Mock(side_effect=OSError("disk unavailable")))

    _run_batch_query(answer=Answer(text="Test answer", references=[]))

    captured = capsys.readouterr()
    assert "Test answer" in captured.out
    assert "ERROR" not in captured.err
    assert not (tmp_path / "pxcli" / "sessions").exists()
