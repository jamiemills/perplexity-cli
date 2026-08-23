"""Termination guards for the paragraph-unwrapping state machine.

This module is named so that pytest collects it before every other suite
file: the watchdog cases below must run ahead of any ordinary unwrapping
test, because a line-index-corrupting collector mutant stalls the whole
per-mutant process rather than failing an assertion.
"""

from __future__ import annotations

import signal

import pytest

from perplexity_cli.formatting.base import Formatter


def _unwrap_with_deadline(text: str, deadline_seconds: float = 0.5) -> str:
    """Run the unwrapper under a SIGALRM watchdog so non-termination fails fast."""

    def _on_deadline(signum: int, frame: object) -> None:
        raise AssertionError(
            f"unwrap_paragraph_lines exceeded {deadline_seconds}s (non-terminating)"
        )

    previous = signal.signal(signal.SIGALRM, _on_deadline)
    signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
    try:
        return Formatter.unwrap_paragraph_lines(text)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "intro\n```\ncode\n```\nafter",
            "intro\n```\ncode\n```\nafter",
            id="closed-block-between-prose",
        ),
        pytest.param(
            "```\nbody only, unclosed",
            "```\nbody only, unclosed",
            id="unclosed-fence-at-start",
        ),
        pytest.param(
            "see:\n\n```\nplain body\n```\ndone",
            "see:\n\n```\nplain body\n```\ndone",
            id="fenced-block-after-blank-line",
        ),
        pytest.param(
            "Intro\n```py\nx = 1\n```",
            "Intro\n```py\nx = 1\n```",
            id="fenced-block-after-intro",
        ),
        pytest.param(
            "head\n\n- item\n  wrapped detail\ntail",
            "head\n\n- item wrapped detail\ntail",
            id="structural-item-with-wrapped-continuation",
        ),
        pytest.param(
            "alpha\nbeta gamma\ndelta",
            "alpha beta gamma delta",
            id="multi-line-prose-joins",
        ),
    ],
)
def test_unwrap_terminates_with_canonical_output(text: str, expected: str):
    """Adversarial documents must terminate promptly with canonical unwrapping.

    Any collector that corrupts its line index either spins forever or makes
    the outer dispatcher revisit lines; the watchdog turns both into an
    immediate failure instead of a stalled test run.
    """
    assert _unwrap_with_deadline(text) == expected
