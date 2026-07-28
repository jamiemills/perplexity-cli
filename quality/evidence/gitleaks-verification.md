# Gitleaks End-to-End Verification Checklist

> Run ID: 20260728-0100
> Task ID: P3C-GITLEAKS
> Script: `scripts/gitleaks_check.sh`
> Scope: Local pre-push validation and post-push verification of gitleaks
> secret detection across all modes (pre-push, ci-full, range).

## 1. Local Pre-Push Validation (completed)

- [x] `make gitleaks-ci` passes: 650 commits scanned, 0 leaks found.
- [x] `uv run pytest tests/test_gitleaks_prepush.py tests/test_gitleaks.py
      tests/test_gitleaks_integration.py -q --tb=short` — 83 passed.
- [x] `lefthook.yml` pre-push `gitleaks-detect` job sets `use_stdin: true` and
      runs `scripts/gitleaks_check.sh pre-push "{1}" "{2}"`.
- [x] No other pre-push job sets `use_stdin` (gitleaks is the sole stdin
      consumer).
- [x] `.gitleaksignore` contains the exact revoked fingerprint:
      `b05b560e8816cb87513d96fb654934426db68dcc:.claudeCode/PHASE2_TEST_REPORT.md:generic-api-key:34`.
- [x] `scripts/gitleaks_check.sh` enforces gitleaks version `8.30.1` exactly.
- [x] Script handles all four modes: `pre-push`, `ci-full`, `range`, and
      default (auto-detect via `CI_NO_SKIP` / stdin / local range).

## 2. Post-Push Verification

Run these steps after the commit lands on the default branch.

### 2.1 CI full-history scan

- [ ] Push a commit and confirm the CI pipeline triggers.
- [ ] The gitleaks CI step runs `CI_NO_SKIP=1 scripts/gitleaks_check.sh ci-full`.
- [ ] Output reports `no leaks found` with exit code 0.
- [ ] Scan covers the full commit history (not just the diff).

### 2.2 Pre-push hook (local)

- [ ] `git push` triggers the lefthook pre-push pipeline.
- [ ] `gitleaks-detect` is the first job and receives stdin (remote name +
      URL as `{1}` `{2}`).
- [ ] For an existing branch: only commits in `local..remote` difference are
      scanned.
- [ ] For a new branch: advertised remote commits are fetched via `git
      ls-remote` and excluded from the scan set.
- [ ] Deleted refs (zero local OID) are skipped with a log message.
- [ ] Exit code 10 blocks the push when leaks are found.

### 2.3 Range mode

- [ ] `scripts/gitleaks_check.sh range HEAD~3 HEAD` scans exactly 3 commits.
- [ ] Invalid refs produce a clear error and non-zero exit.

### 2.4 Version guard

- [ ] Running with a gitleaks version other than 8.30.1 produces:
      `unsupported gitleaks version '<ver>' (requires exactly 8.30.1)`.
- [ ] Missing gitleaks binary produces: `gitleaks is required but not installed`.

### 2.5 Allowlist integrity

- [ ] The `.gitleaksignore` fingerprint matches a revoked token only.
- [ ] No new entries are added without a corresponding revocation confirmation.
- [ ] `make gitleaks-ci` still reports 0 leaks with the allowlist in place.

## 3. Rollback / Failure Notes

- If gitleaks reports a false positive, add the fingerprint to `.gitleaksignore`
  with a comment documenting the revocation date and owner.
- If the version guard blocks a legitimate upgrade, update
  `REQUIRED_GITLEAKS_VERSION` in `scripts/gitleaks_check.sh` and re-run the
  full test suite.
- The pre-push hook is advisory locally; CI (`gitleaks-ci`) is the authoritative
  gate. A broken local hook does not block merges if CI passes.
