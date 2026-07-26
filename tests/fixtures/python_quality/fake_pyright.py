#!/usr/bin/env python3
"""Fake pyright executable for hermetic testing of the strict ratchet gate.

Behaviour is controlled via environment variables:

``FAKE_PYRIGHT_MODE``:
    ``pass``           — valid JSON with no diagnostics (exit 0)
    ``findings``       — valid JSON with strict diagnostics (exit 1)
    ``empty-output``   — empty stdout, successful exit (exit 0)
    ``malformed``      — invalid JSON on stdout (exit 0)
    ``tool-error``     — non-zero exit >=2 with stderr message (exit 2)
    ``timeout``        — sleep forever (simulates hang)
"""

from __future__ import annotations

import json
import os
import sys
import time

MODE = os.environ.get("FAKE_PYRIGHT_MODE", "pass")

DIAGNOSTICS_PASS: dict = {"generalDiagnostics": []}

DIAGNOSTICS_FINDINGS: dict = {
    "generalDiagnostics": [
        {
            "file": "src/perplexity_cli/core.py",
            "range": {"start": {"line": 10, "character": 5}},
            "rule": "reportUnknownParameterType",
            "message": "Type of parameter is unknown",
        },
        {
            "file": "src/perplexity_cli/handler.py",
            "range": {"start": {"line": 34, "character": 12}},
            "rule": "reportAny",
            "message": "Type is Any",
        },
    ]
}


def main() -> int:
    if MODE == "timeout":
        time.sleep(9999)
        return 0

    if MODE == "pass":
        json.dump(DIAGNOSTICS_PASS, sys.stdout)
        return 0

    if MODE == "findings":
        json.dump(DIAGNOSTICS_FINDINGS, sys.stdout)
        return 1

    if MODE == "empty-output":
        return 0

    if MODE == "malformed":
        sys.stdout.write("not valid json {")
        return 0

    if MODE == "tool-error":
        sys.stderr.write("pyright: Fatal error: Config file is invalid\n")
        return 2

    json.dump(DIAGNOSTICS_PASS, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
