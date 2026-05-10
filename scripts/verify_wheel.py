"""Verify that the built wheel contains all required packaged resources."""

from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    """Check that the newest wheel in dist/ includes expected files."""
    wheels = sorted(Path("dist").glob("pxcli-*.whl"))
    if not wheels:
        raise SystemExit("No built wheel found in dist/.")

    with ZipFile(wheels[-1]) as wheel:
        names = set(wheel.namelist())

    required = "perplexity_cli/config/urls.json"
    if required not in names:
        raise SystemExit(f"Missing required packaged resource: {required}")

    print(f"Verified required packaged resource: {required}")


if __name__ == "__main__":
    main()
