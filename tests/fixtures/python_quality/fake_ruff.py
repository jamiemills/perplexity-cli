#!/usr/bin/env python3
"""Fake ruff executable for hermetic testing of the architecture ratchet gate.

Behaviour is controlled via environment variables:

``FAKE_RUFF_MODE``:
    ``pass``           — valid JSON with no findings (exit 0)
    ``findings``       — valid JSON with architecture findings (exit 1)
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

MODE = os.environ.get("FAKE_RUFF_MODE", "pass")

FINDINGS: list[dict] = [
    {
        "code": "C901",
        "filename": "src/perplexity_cli/core.py",
        "location": {"row": 55},
    },
    {
        "code": "PLR0913",
        "filename": "src/perplexity_cli/handler.py",
        "location": {"row": 120},
    },
]


def main() -> int:
    if MODE == "timeout":
        time.sleep(9999)
        return 0

    if MODE == "pass":
        json.dump([], sys.stdout)
        return 0

    if MODE == "findings":
        json.dump(FINDINGS, sys.stdout)
        return 1

    if MODE == "empty-output":
        return 0

    if MODE == "malformed":
        sys.stdout.write("not valid json {")
        return 0

    if MODE == "tool-error":
        sys.stderr.write("ruff: Fatal error: Linter crashed\n")
        return 2

    json.dump([], sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
