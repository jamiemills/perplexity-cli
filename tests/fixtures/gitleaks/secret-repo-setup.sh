#!/usr/bin/env bash
# =============================================================================
# secret-repo-setup.sh — provision a repo containing a SYNTHETIC secret.
#
# The strings below are NOT real credentials.  They are crafted to match
# gitleaks' built-in aws-access-token / generic-api-key rules so that
# integration tests can assert exit-code 10 (findings) deterministically.
#
# Usage: secret-repo-setup.sh <target_dir>
#
# Owner: jamie.mills@gmail.com — test fixture, no real credential.
# =============================================================================
set -euo pipefail

target="${1:?usage: secret-repo-setup.sh <target_dir>}"
mkdir -p "$target"
cd "$target"

git init --initial-branch=main >/dev/null
git config user.email "test@example.com"
git config user.name "Test User"

echo "# Test Repo" > README.md
git add README.md
git commit -m "chore: initialise repository" >/dev/null

# SYNTHETIC test fixture — NOT a real credential.
cat > config.py <<'PYEOF'
# Synthetic test fixture — NOT a real credential.
AWS_ACCESS_KEY_ID = "AKIA0123456789ABCDEF"
AWS_SECRET_ACCESS_KEY = "c4a82c662a22c001b83142d1265c7fb8360b3aa"
PYEOF
git add config.py
git commit -m "leak: add config with synthetic secret" >/dev/null
