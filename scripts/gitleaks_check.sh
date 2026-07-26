#!/usr/bin/env bash
# =============================================================================
# gitleaks_check.sh — secret detection for pre-push and CI.
#
# Three explicit modes:
#   pre-push REMOTE_NAME REMOTE_URL   Reads 4-field ref updates from stdin.
#   ci-full                           Scans the entire repository history.
#   range OLD NEW                     Scans the OLD..NEW commit range.
#
# Backward-compatible invocations (for the Makefile which must not change):
#   scripts/gitleaks_check.sh               — pre-push via stdin or local range.
#   CI_NO_SKIP=1 scripts/gitleaks_check.sh  — full-repo CI scan.
#
# Exit codes:
#   0   — no secrets found (clean)
#   10  — secrets detected (findings)
#   other non-zero — scanning error (bad version, missing gitleaks, etc.)
#
# Pre-push stdin format (standard git pre-push hook):
#   <local_oid> <local_ref> <remote_oid> <remote_ref>
#   ... one row per ref being pushed ...
#
# Object-format-aware: zero-OID detection works for SHA-1 (40 zeros) and
# future SHA-256 (64 zeros) refspecs.
# =============================================================================

readonly REQUIRED_GITLEAKS_VERSION="8.30"

# ---------------------------------------------------------------------------
# Diagnostics — run inside a controlled status block so set -e
# does not silence diagnostics.
# ---------------------------------------------------------------------------

_die() {
    echo "gitleaks_check: ERROR: $*" >&2
    exit 3
}

# ---------------------------------------------------------------------------
# Object-format-aware zero-OID detection.
# Returns 0 (success) when the argument is an all-zeroes object ID.
# ---------------------------------------------------------------------------

_is_zero_oid() {
    local oid="$1"
    [[ "$oid" =~ ^0+$ ]]
}

# ---------------------------------------------------------------------------
# Peel a ref (branches and tags) to a commit SHA.
# ---------------------------------------------------------------------------

_peel_ref() {
    local ref="$1"
    git rev-parse --verify "$ref^{commit}" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Version check — parse ``gitleaks version`` and reject unsupported versions.
# ---------------------------------------------------------------------------

_check_version() {
    local raw_version
    raw_version="$(gitleaks version 2>/dev/null)" || {
        _die "failed to run 'gitleaks version'"
    }

    raw_version="${raw_version#v}"
    raw_version="${raw_version##[[:space:]]}"
    raw_version="${raw_version%%[[:space:]]}"

    if [[ "$raw_version" != "$REQUIRED_GITLEAKS_VERSION"* ]]; then
        _die "unsupported gitleaks version '$raw_version' (requires $REQUIRED_GITLEAKS_VERSION.x)"
    fi
}

# ---------------------------------------------------------------------------
# Require gitleaks binary.  Hard failure — there is no silent skip path.
# ---------------------------------------------------------------------------

_require_gitleaks() {
    if ! command -v gitleaks &>/dev/null; then
        _die "gitleaks is required but not installed"
    fi
}

# ---------------------------------------------------------------------------
# Validate that a single stdin row has exactly 4 fields.
# ---------------------------------------------------------------------------

_validate_row() {
    local local_oid="$1" local_ref="$2" remote_oid="$3" remote_ref="$4"

    if [[ -z "$local_oid" || -z "$local_ref" || -z "$remote_oid" || -z "$remote_ref" ]]; then
        _die "malformed pre-push row (expected 4 fields): $local_oid $local_ref $remote_oid $remote_ref"
    fi
}

# ---------------------------------------------------------------------------
# Normalise commit OIDs: peel tags to commit SHAs.
# ---------------------------------------------------------------------------

_to_commit_oid() {
    local ref="$1"
    local peeled
    peeled="$(_peel_ref "$ref")" || true
    if [[ -n "$peeled" ]]; then
        echo "$peeled"
    else
        echo "$ref"
    fi
}

# ---------------------------------------------------------------------------
# Scan a commit range with gitleaks.
# Returns gitleaks exit code (0 = clean, 10 = findings, other = error).
# ---------------------------------------------------------------------------

_scan_range() {
    local range="$1"
    echo "gitleaks: scanning commits in range '$range'..."

    gitleaks git \
        --verbose \
        --redact \
        --exit-code 10 \
        --log-opts="$range"
}

# ---------------------------------------------------------------------------
# Pre-push mode: collect commits-to-scan from stdin refspecs, then scan
# the mathematical union via a single git rev-list pass.
# ---------------------------------------------------------------------------

_pre_push_scan() {
    local remote_name="$1"
    local remote_url="$2"
    local collected_ranges=()
    local row_count=0
    local deleted_count=0

    while IFS=' ' read -r local_oid local_ref remote_oid remote_ref; do
        local_oid="${local_oid##[[:space:]]}";  local_oid="${local_oid%%[[:space:]]}"
        local_ref="${local_ref##[[:space:]]}";  local_ref="${local_ref%%[[:space:]]}"
        remote_oid="${remote_oid##[[:space:]]}"; remote_oid="${remote_oid%%[[:space:]]}"
        remote_ref="${remote_ref##[[:space:]]}"; remote_ref="${remote_ref%%[[:space:]]}"

        _validate_row "$local_oid" "$local_ref" "$remote_oid" "$remote_ref"
        row_count=$((row_count + 1))

        # ---- Deleted ref (local = zeros): skip ---------------------------------
        if _is_zero_oid "$local_oid"; then
            echo "gitleaks: skipping deleted ref $remote_ref"
            deleted_count=$((deleted_count + 1))
            continue
        fi

        # ---- Existing ref (both non-zero): scan remote_oid..local_oid ----------
        if ! _is_zero_oid "$remote_oid"; then
            local local_commit remote_commit
            local_commit="$(_to_commit_oid "$local_oid")"
            remote_commit="$(_to_commit_oid "$remote_oid")"

            if [[ "$local_commit" == "$remote_commit" ]]; then
                echo "gitleaks: no new commits on $local_ref (local == remote)"
                continue
            fi

            echo "gitleaks: existing ref $local_ref: scanning $remote_commit..$local_commit"
            collected_ranges+=("$remote_commit..$local_commit")
            continue
        fi

        # ---- New ref (remote = zeros): query remote, scan local minus remote ---
        if _is_zero_oid "$remote_oid"; then
            local local_commit remote_tip
            local_commit="$(_to_commit_oid "$local_oid")"

            remote_tip="$(git ls-remote --refs "$remote_url" "$remote_ref" 2>/dev/null | awk '{print $1}')" || true

            if [[ -n "$remote_tip" ]]; then
                echo "gitleaks: new ref $local_ref with remote tip: scanning $remote_tip..$local_commit"
                collected_ranges+=("$remote_tip..$local_commit")
            else
                echo "gitleaks: new ref $local_ref has no remote counterpart"
                local remote_branches
                remote_branches="$(git for-each-ref --format='%(refname)' 'refs/remotes/origin/' 2>/dev/null || true)"

                if [[ -n "$remote_branches" ]]; then
                    local candidate_base=""
                    while IFS= read -r rb; do
                        local mb
                        mb="$(git merge-base "$local_commit" "$rb" 2>/dev/null)" || true
                        if [[ -n "$mb" ]]; then
                            if [[ -z "$candidate_base" ]] || git merge-base --is-ancestor "$candidate_base" "$mb" &>/dev/null; then
                                candidate_base="$mb"
                            fi
                        fi
                    done <<< "$remote_branches"

                    if [[ -n "$candidate_base" ]]; then
                        echo "gitleaks: new ref $local_ref: scanning $candidate_base..$local_commit"
                        collected_ranges+=("$candidate_base..$local_commit")
                    else
                        echo "gitleaks: new ref $local_ref: no common ancestor — scanning ref history"
                        collected_ranges+=("$local_commit")
                    fi
                else
                    echo "gitleaks: new ref $local_ref: no remote branches — scanning reachable commits"
                    collected_ranges+=("$local_commit")
                fi
            fi
            continue
        fi
    done

    if [[ "$row_count" -eq 0 ]]; then
        echo "gitleaks: no refs received on stdin"
        return 0
    fi

    if [[ "$deleted_count" -eq "$row_count" ]]; then
        echo "gitleaks: all refs are deletions — nothing to scan"
        return 0
    fi

    if [[ "${#collected_ranges[@]}" -eq 0 ]]; then
        echo "gitleaks: no commits to scan after processing all refs"
        return 0
    fi

    # Build the mathematical union: materialise all commits then scan.
    local commit_list
    commit_list="$(git rev-list "${collected_ranges[@]}" 2>/dev/null | sort -u)" || true

    if [[ -z "$commit_list" ]]; then
        echo "gitleaks: empty commit union — nothing to scan"
        return 0
    fi

    local oldest newest
    oldest="$(echo "$commit_list" | tail -n1)"
    newest="$(echo "$commit_list" | head -n1)"

    echo "gitleaks: scanning union of ${#collected_ranges[@]} ref range(s) ($(echo "$commit_list" | wc -l) unique commits)"
    _scan_range "${oldest}^..${newest}"
}

# ---------------------------------------------------------------------------
# ci-full mode: scan the full repository history.
# ---------------------------------------------------------------------------

_ci_full_scan() {
    echo "gitleaks: CI full-history scan"
    gitleaks detect \
        --source . \
        --verbose \
        --redact \
        --exit-code 10
}

# ---------------------------------------------------------------------------
# Range mode: scan OLD..NEW.
# ---------------------------------------------------------------------------

_range_scan_cmd() {
    local old_ref="$1" new_ref="$2"

    if ! git rev-parse --verify "$old_ref^{commit}" &>/dev/null; then
        _die "invalid old ref: $old_ref"
    fi
    if ! git rev-parse --verify "$new_ref^{commit}" &>/dev/null; then
        _die "invalid new ref: $new_ref"
    fi

    _scan_range "$old_ref..$new_ref"
}

# ---------------------------------------------------------------------------
# Local-range scan: determine the appropriate range from current git state.
# This is the fallback used by the backward-compat (no-mode) invocation.
# ---------------------------------------------------------------------------

_local_range_scan() {
    local branch
    branch="$(git rev-parse --abbrev-ref HEAD)"

    local range
    if [[ "$branch" == "HEAD" ]]; then
        range="HEAD"
    else
        local remote_branch="origin/$branch"
        if git rev-parse --verify "$remote_branch" &>/dev/null; then
            range="$remote_branch..HEAD"
        else
            local base="origin/main"
            git rev-parse --verify "$base" &>/dev/null || base="origin/master"
            if git rev-parse --verify "$base" &>/dev/null; then
                range="$base..HEAD"
            else
                range="HEAD"
            fi
        fi
    fi

    _scan_range "$range"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    if ! git rev-parse --git-dir &>/dev/null; then
        _die "not a git repository"
    fi

    local mode="${1:-}"
    shift || true

    case "$mode" in
        pre-push)
            local remote_name="${1:-}"
            local remote_url="${2:-}"
            shift 2 || true
            local extra="${1:-}"

            if [[ -z "$remote_name" || -z "$remote_url" || -n "$extra" ]]; then
                _die "usage: $0 pre-push REMOTE_NAME REMOTE_URL"
            fi

            _require_gitleaks
            _check_version
            _pre_push_scan "$remote_name" "$remote_url"
            ;;

        ci-full)
            local extra="${1:-}"
            if [[ -n "$extra" ]]; then
                _die "usage: $0 ci-full"
            fi
            _require_gitleaks
            _check_version
            _ci_full_scan
            ;;

        range)
            local old_ref="${1:-}"
            local new_ref="${2:-}"
            shift 2 || true
            local extra="${1:-}"

            if [[ -z "$old_ref" || -z "$new_ref" || -n "$extra" ]]; then
                _die "usage: $0 range OLD NEW"
            fi

            _require_gitleaks
            _check_version
            _range_scan_cmd "$old_ref" "$new_ref"
            ;;

        "")
            # Backward-compatible invocation (no explicit mode).
            # If CI_NO_SKIP is set, behave as ci-full.
            local ci_skip="${CI_NO_SKIP:-}"
            if [[ "$ci_skip" == "1" || "$ci_skip" == "true" ]]; then
                _require_gitleaks
                _check_version
                _ci_full_scan
                return
            fi

            _require_gitleaks
            _check_version

            # Try reading pre-push refspecs from stdin first.
            if [[ ! -t 0 ]]; then
                local remote_url
                remote_url="$(git remote get-url origin 2>/dev/null || true)"
                _pre_push_scan "origin" "$remote_url"
                return
            fi

            # Stdin is a terminal — fall back to local range scan.
            _local_range_scan
            ;;

        *)
            _die "unknown mode '$mode' (expected: pre-push, ci-full, or range)"
            ;;
    esac
}

main "$@"
