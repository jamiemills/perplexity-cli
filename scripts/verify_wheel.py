"""Verify that the built wheel contains all required packaged resources.

Usage::

    python scripts/verify_wheel.py
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    """Check that the newest wheel in dist/ includes expected files."""
    wheels = sorted(Path("dist").glob("pxcli-*.whl"))
    if not wheels:
        msg = "No built wheel found in dist/."
        raise SystemExit(msg)

    with ZipFile(wheels[-1]) as wheel:
        names = set(wheel.namelist())

    required = "perplexity_cli/config/urls.json"
    if required not in names:
        msg = f"Missing required packaged resource: {required}"
        raise SystemExit(msg)

    print(f"Verified required packaged resource: {required}")


if __name__ == "__main__":
    main()
