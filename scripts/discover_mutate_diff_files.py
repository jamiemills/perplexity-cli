from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = "src/perplexity_cli/"


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _base_ref() -> str:
    refs = _git_lines("rev-parse", "--abbrev-ref", "origin/HEAD")
    return refs[0] if refs else "origin/master"


def _is_source_file(path: str) -> bool:
    candidate = PROJECT_ROOT / path
    return (
        path.startswith(SOURCE_ROOT)
        and path.endswith(".py")
        and candidate.is_file()
        and candidate.name != "__init__.py"
        and "__pycache__" not in candidate.parts
    )


def discover_mutate_diff_files() -> list[str]:
    base_ref = _base_ref()
    paths = [
        *_git_lines("diff", "--name-only", f"{base_ref}...HEAD", "--", SOURCE_ROOT),
        *_git_lines("diff", "--name-only", "--cached", "--", SOURCE_ROOT),
        *_git_lines("diff", "--name-only", "--", SOURCE_ROOT),
        *_git_lines("ls-files", "--others", "--exclude-standard", "--", SOURCE_ROOT),
    ]
    return sorted({path for path in paths if _is_source_file(path)})


def main() -> int:
    for path in discover_mutate_diff_files():
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
