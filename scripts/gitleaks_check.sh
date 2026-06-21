#!/usr/bin/env bash
# =============================================================================
# gitleaks_check.sh — pre-push secret detection.
#
# Determines the commit range being pushed (remote tracking branch..HEAD)
# and runs gitleaks detect against those commits.  Called by lefthook
# pre-push and `make gitleaks`.
#
# Exit codes:
#   0 — no secrets found, or gitleaks not installed (skip)
#   1 — secrets detected, push blocked
#   3 — not a git repository
# =============================================================================
set -euo pipefail

# --- pre-flight -----------------------------------------------------------
if ! command -v gitleaks &>/dev/null; then
    echo "gitleaks is not installed — skipping pre-push secret scan."
    echo "Install: brew install gitleaks"
    echo "Or see: https://github.com/gitleaks/gitleaks#installing"
    echo "CI gitleaks + infisical pre-commit will still catch secrets."
    exit 0
fi

if ! git rev-parse --git-dir &>/dev/null; then
    echo "Not a git repository."
    exit 3
fi

# --- determine commit range ------------------------------------------------
# Scan commits on the current branch that are ahead of the remote tracking
# branch.  If the branch has no upstream, scan all commits on the branch.
branch=$(git rev-parse --abbrev-ref HEAD)

if [ "$branch" = "HEAD" ]; then
    # Detached HEAD — scan the single commit
    range="HEAD"
else
    remote_branch="origin/$branch"
    if git rev-parse --verify "$remote_branch" &>/dev/null; then
        range="$remote_branch..HEAD"
    else
        # New branch with no remote tracking — scan everything reachable
        # from HEAD that isn't on the base branch (default: origin/main).
        base="origin/main"
        git rev-parse --verify "$base" &>/dev/null || base="origin/master"
        if git rev-parse --verify "$base" &>/dev/null; then
            range="$base..HEAD"
        else
            range="HEAD"
        fi
    fi
fi

# --- scan ------------------------------------------------------------------
echo "gitleaks: scanning commits in range '$range'..."

# --no-banner suppresses the ascii art; --verbose shows findings.
gitleaks detect \
    --source=. \
    --verbose \
    --redact \
    --log-opts="$range"

exit_code=$?

if [ "$exit_code" -eq 0 ]; then
    echo "gitleaks: no secrets detected."
else
    echo ""
    echo "ERROR: gitleaks detected secrets in the commits being pushed."
    echo "Push rejected.  Remove the secrets and amend your commits."
    echo "For help: https://github.com/gitleaks/gitleaks#pre-commit"
fi

exit "$exit_code"
