#!/usr/bin/env python3
"""Fake semgrep executable for hermetic testing of the architecture ratchet gate.

Behaviour is controlled via environment variables:

``FAKE_SEMGREP_MODE``:
    ``pass``          — valid JSON with no results (exit 0)
    ``findings``       — valid JSON with architecture-rule findings (exit 0)
    ``empty-output``   — empty stdout, successful exit (exit 0)
    ``malformed``      — invalid JSON on stdout (exit 0)
    ``tool-error``     — non-zero exit with stderr message (exit 2)
    ``analysis-error`` — valid JSON with ``errors`` list (exit 0)
    ``timeout``        — sleep forever (simulates hang)
    ``non-zero-findings`` — valid JSON with findings, non-zero exit (exit 1)
"""

from __future__ import annotations

import json
import os
import sys
import time

MODE = os.environ.get("FAKE_SEMGREP_MODE", "pass")

RESULTS_EMPTY: dict = {"results": [], "errors": []}

RESULTS_FINDINGS: dict = {
    "results": [
        {
            "check_id": "function-local-import",
            "path": "src/perplexity_cli/module.py",
            "start": {"line": 42, "col": 8},
            "extra": {},
        },
        {
            "check_id": "sys-exit-outside-boundary",
            "path": "src/perplexity_cli/other.py",
            "start": {"line": 10, "col": 4},
            "extra": {},
        },
    ],
    "errors": [],
}

RESULTS_ANALYSIS_ERROR: dict = {
    "results": [],
    "errors": [{"level": "error", "message": "Cannot parse file"}],
}

RESULTS_MALFORMED: str = "not valid json {broken!"


def main() -> int:
    if MODE == "timeout":
        time.sleep(9999)
        return 0

    if MODE == "pass":
        json.dump(RESULTS_EMPTY, sys.stdout)
        return 0

    if MODE == "findings":
        json.dump(RESULTS_FINDINGS, sys.stdout)
        return 0

    if MODE == "empty-output":
        return 0

    if MODE == "malformed":
        sys.stdout.write(RESULTS_MALFORMED)
        return 0

    if MODE == "tool-error":
        sys.stderr.write("semgrep: Fatal error: Bad --config value\n")
        return 2

    if MODE == "analysis-error":
        json.dump(RESULTS_ANALYSIS_ERROR, sys.stdout)
        return 0

    if MODE == "non-zero-findings":
        json.dump(RESULTS_FINDINGS, sys.stdout)
        return 1

    json.dump(RESULTS_EMPTY, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
