#!/usr/bin/env bash
# =============================================================================
# clean-repo-setup.sh — provision a clean (no-secret) git repository.
#
# Used by tests/test_gitleaks_prepush.py to materialise a deterministic
# fixture repo with two ordinary commits and no synthetic secrets.
#
# Usage: clean-repo-setup.sh <target_dir>
#
# Owner: jamie.mills@gmail.com — test fixture, no real credential.
# =============================================================================
set -euo pipefail

target="${1:?usage: clean-repo-setup.sh <target_dir>}"
mkdir -p "$target"
cd "$target"

git init --initial-branch=main >/dev/null
git config user.email "test@example.com"
git config user.name "Test User"

echo "# Clean Repository" > README.md
git add README.md
git commit -m "chore: initialise repository" >/dev/null

cat > hello.py <<'PYEOF'
"""Trivial module used to exercise clean-scan paths."""


def hello() -> str:
    """Return a friendly greeting."""
    return "hello, world"
PYEOF
git add hello.py
git commit -m "feat: add hello module" >/dev/null
