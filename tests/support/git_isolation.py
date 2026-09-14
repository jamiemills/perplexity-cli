"""Isolate tests from inherited git repository-location variables.

Git exports ``GIT_DIR`` (and an absolute ``GIT_INDEX_FILE``) to hooks whenever
the repository is a linked worktree.  When pytest runs from such a hook -- for
example lefthook's ``pre-commit`` -- every ``git`` subprocess spawned by a test
inherits those variables, so ``cwd=tmp_path`` no longer redirects the command:
``git init``/``add``/``commit``/``reset`` mutate the *invoking* worktree
instead of the throwaway repository, moving the real branch and rewriting its
index.

Scrubbing these variables at ``pytest_configure`` time, before collection,
keeps test repositories confined to their temporary paths regardless of how
pytest was launched.
"""

from __future__ import annotations

import os

import pytest

GIT_LOCATION_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
)


def scrub_git_location_env() -> None:
    """Remove inherited git repository-location variables from ``os.environ``."""
    for name in GIT_LOCATION_VARS:
        os.environ.pop(name, None)


def pytest_configure(config: pytest.Config) -> None:
    """Scrub git repository-location variables before test collection."""
    scrub_git_location_env()
