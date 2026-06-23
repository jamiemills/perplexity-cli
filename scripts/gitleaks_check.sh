#!/usr/bin/env bash
# =============================================================================
# gitleaks_check.sh — secret detection for pre-push and CI.
#
# Runs gitleaks against the commit range being pushed (or full history in CI).
# Uses the current gitleaks git command style.
#
# Environment variable CI_NO_SKIP:
#   When set to "1" or "true", gitleaks unavailability is a hard failure.
#   This is used in CI to ensure secret scanning cannot silently skip.
#
# Exit codes:
#   0 — no secrets found, or gitleaks not installed and CI_NO_SKIP not set
#   1 — secrets detected, push blocked
#   2 — gitleaks not installed and CI_NO_SKIP is set to "1" or "true"
#   3 — not a git repository
# =============================================================================
set -euo pipefail

_CI_NO_SKIP="${CI_NO_SKIP:-}"

# --- pre-flight -----------------------------------------------------------
if ! command -v gitleaks &>/dev/null; then
    if [ "$_CI_NO_SKIP" = "1" ] || [ "$_CI_NO_SKIP" = "true" ]; then
        echo "ERROR: gitleaks is required but not installed."
        echo "Install: brew install gitleaks"
        echo "Or see: https://github.com/gitleaks/gitleaks#installing"
        exit 2
    fi
    echo "gitleaks is not installed — skipping secret scan."
    echo "Install: brew install gitleaks"
    echo "Or see: https://github.com/gitleaks/gitleaks#installing"
    echo "CI gitleaks + infisical pre-commit will still catch secrets."
    exit 0
fi

if ! git rev-parse --git-dir &>/dev/null; then
    echo "Not a git repository."
    exit 3
fi

# --- determine scan mode ----------------------------------------------------
# If a log-opts range is passed (e.g. via make gitleaks-ci), use it.
# Otherwise, determine the range from the push context.
if [ -n "${1:-}" ]; then
    range="$1"
else
    branch=$(git rev-parse --abbrev-ref HEAD)

    if [ "$branch" = "HEAD" ]; then
        range="HEAD"
    else
        remote_branch="origin/$branch"
        if git rev-parse --verify "$remote_branch" &>/dev/null; then
            range="$remote_branch..HEAD"
        else
            base="origin/main"
            git rev-parse --verify "$base" &>/dev/null || base="origin/master"
            if git rev-parse --verify "$base" &>/dev/null; then
                range="$base..HEAD"
            else
                range="HEAD"
            fi
        fi
    fi
fi

# --- scan ------------------------------------------------------------------
echo "gitleaks: scanning commits in range '$range'..."

gitleaks git \
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
