"""Early termination guards for envelope serialisation mutation tests."""

from __future__ import annotations

import inspect
import io
import signal
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from perplexity_cli.envelope import envelope_to_dict, write_envelope


def _run_with_deadline(call: Callable[[], Any], deadline_seconds: float = 1.0) -> Any:
    """Run a finite envelope probe under a watchdog."""

    def _on_deadline(signum: int, frame: object) -> None:
        raise AssertionError(f"envelope probe exceeded {deadline_seconds}s")

    previous = signal.signal(signal.SIGALRM, _on_deadline)
    signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("serialiser", [envelope_to_dict, write_envelope])
def test_envelope_default_is_stable_across_three_bounded_calls(
    serialiser: Callable[..., Any],
) -> None:
    """The no-schema default remains observable and terminates repeatedly."""
    envelope = MagicMock()
    envelope.model_dump.return_value = {"ok": True, "command": "probe"}

    def _probe() -> str:
        defaults = inspect.signature(serialiser).parameters["include_schema"].default
        assert defaults == "no_schema"
        if serialiser is envelope_to_dict:
            assert serialiser(envelope) == {"ok": True, "command": "probe"}
            return "dict"

        output = io.StringIO()
        serialiser(envelope, output=output)
        assert output.getvalue() == '{"ok": true, "command": "probe"}\n'
        return "write"

    for _ in range(3):
        assert _run_with_deadline(_probe) in {"dict", "write"}
