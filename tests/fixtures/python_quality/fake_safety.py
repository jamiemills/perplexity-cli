#!/usr/bin/env python3
"""Fake safety CLI executable for hermetic testing.

Behaviour is controlled via environment variables:

``FAKE_SAFETY_MODE``:
    ``pass``        — no vulnerabilities found (exit 0)
    ``vulnerable``  — scan-failing vulnerability found (exit 64)
    ``tool-error``  — safety CLI crash (exit 2)
    ``timeout``     — hang forever
"""

from __future__ import annotations

import os
import sys
import time

MODE = os.environ.get("FAKE_SAFETY_MODE", "pass")


def main() -> int:
    if MODE == "timeout":
        time.sleep(9999)
        return 0

    if MODE == "pass":
        print("No known security vulnerabilities found.")
        return 0

    if MODE == "vulnerable":
        print(
            "Vulnerable package: requests<2.32.2 (CVE-2024-XXXXX)",
            file=sys.stderr,
        )
        print("Scan complete — 1 vulnerability found.")
        return 64

    if MODE == "tool-error":
        print("Error: Could not fetch vulnerability database.", file=sys.stderr)
        return 2

    print("No known security vulnerabilities found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
