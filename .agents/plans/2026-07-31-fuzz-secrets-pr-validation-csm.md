# Fuzz Authority + Secrets Isolation + PR Job Validation CSM Plan

## Control
- Plan ID: fuzz-secrets-pr-validation
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Last checkpoint: `6a87133` (atheris dep added, local only)
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Close 4 remaining items:
1. **Push atheris commit** (`6a87133`) to origin — triggers CI that now installs atheris and genuinely runs the 17 fuzz tests.
2. **P0 rank 4 — fuzz authority**: remove `continue-on-error` from `fuzz-status` job, replace silent `skipif` guards with fail-if-unavailable, update stale "non-authoritative" comment.
3. **P0 rank 2 — secrets isolation (in-repo half)**: restrict authenticated `safety` job to `push: master` only (removes SAFETY_API_KEY exposure on same-repo PRs), add credential-free `pip-audit` job to the PR lane, update the policy test that pins the current `if:` condition.
4. **Validate PR-only CI jobs** (`diff-coverage`, `mutation-diff`) via a real PR — the only way to exercise them (workflow_dispatch does NOT run them; verified).

Deliverables: master pushed; fuzz-status blocking; safety push-only + pip-audit in PR CI; PR opened showing both jobs green (or documented repair).
Constraints: No gate weakening. `make check` passes after each task. All changes must keep the workflow-configuration policy tests green (they pin CI structure).
Exclusions: GitHub-admin halves of rank 2 (protected environment binding) and rank 3/1/5/6 — out of scope. `mutation-scheduled.yml` (weekly full mutation, credential-free) unchanged.

## Acceptance Criteria
1. `origin/master` contains the atheris commit — CI run on that push shows fuzz-status running 17 tests (visible in job log) AND test-macos green (atheris platform-gated).
2. `.github/workflows/ci.yml` fuzz-status job has NO `continue-on-error`; `tests/test_fuzz.py` has NO `skipif(not _HAS_ATHERIS)` guards — missing atheris now FAILS the fuzz harness path (raise ImportError in `_run_harness`, scoped so macOS standard suite and the 4 enforcement tests survive); `Makefile:520` comment says authoritative.
3. `safety` job `if:` restricted to `push` (master) only; new credential-free `pip-audit` job (timeout-minutes: 10) runs on PRs and pushes; `tests/test_workflow_configuration.py` updated and passing.
4. Validation PR shows `diff-coverage` (10-min timeout) and `mutation-diff` (45-min) jobs green with real SHA payloads; any timeout/defect repaired and re-validated.
5. `quality/remediation/p0-assessment.md` ranks 2 and 4 updated to reflect completion; `make check` passes.

## Current-State Evidence
- `6a87133` (atheris dep) committed locally; `origin/master` at `de11896` — 1 commit behind. `git status` clean.
- fuzz-status job: `continue-on-error: true` at `ci.yml:151`; runs `make ci-fuzz-status` (`ci.yml:168`).
- `Makefile:520`: `ci-fuzz-status: test-fuzz ## CI fuzz status (non-authoritative until rank 4)`.
- `tests/test_fuzz.py`: `_HAS_ATHERIS = importlib.util.find_spec("atheris") is not None` (line 28); 6 `@pytest.mark.skipif(not _HAS_ATHERIS, ...)` decorators (lines 60, 87, 110, 125, 144, 171); 17 fuzz tests + 4 non-fuzz enforcement tests. With atheris installed: 17 passed in 13.21s (verified).
- CI `uv sync --all-extras --locked --group dev` (`ci.yml:165`) — atheris in dev group will install.
- `safety` job (`ci.yml:254-280`): `if: github.event_name != 'pull_request' || (head.repo.full_name == github.repository && actor != 'dependabot[bot]')` — TRUE on same-repo PRs → SAFETY_API_KEY exposed to mutable PR branches (`ci.yml:279`).
- `pip-audit` Makefile target exists (`Makefile:262-263`) but in NO workflow.
- `tests/test_workflow_configuration.py:103-117` `test_trusted_safety_job_excludes_forks_and_dependabot` asserts current `if:` substrings + `make safety-gate` in recipe — MUST be updated when restricting.
- `diff-coverage` job (`ci.yml:304-330`, timeout 10 min): runs its own `make test-coverage-report` then `make diff-coverage BASE_SHA=... TESTED_SHA=...`. `TESTED_SHA` unused by Makefile target (`Makefile:352-364`); diff-cover compares `compare_branch...HEAD`.
- `mutation-diff` job (`ci.yml:332-355`, timeout 45 min): `make mutate-diff BASE_SHA=... TESTED_SHA=...`; skips cleanly (exit 0) on doc-only PRs; exit 0 even with surviving mutants (diagnostic, not kill-gate — policy enforced by `mutation-scheduled.yml`).
- `on:` triggers (`ci.yml:3-8`): push/master, pull_request, workflow_dispatch. Both jobs gate `if: github.event_name == 'pull_request'` — dispatch won't exercise them.
- No branch protection, no rulesets, no required checks — validation PR can be opened and closed freely.
- `gh 2.45.0`, authed as jamiemills with `workflow` scope. Repo public.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | Fuzz authority = remove continue-on-error + fail-if-unavailable | Decision | p0-assessment.md:91-95 lists exactly these; skip path silently exits 0 today | Accepted |
| A2 | Fail-if-unavailable via `raise ImportError` INSIDE `_run_harness` (test_fuzz.py:37-51), NOT module-level importorskip | Evidence | `pytest.importorskip` raises Skipped (exit 0) — not a failure. Module-level abort would kill the 4 enforcement tests + macOS standard suite. `_run_harness` is only invoked by fuzz-marked tests | Confirmed |
| A3 | Safety restricted to `push` only; pip-audit covers PR lane | Decision | p0-assessment.md:47-49; removes secret from mutable branches; pip-audit is credential-free | Accepted |
| A4 | PR validation uses trivial src change (docstring tweak) in a small file | Decision | exit_codes.py (~36 mutants) keeps mutation-diff fast; no behavioural change | Accepted |
| A5 | diff-coverage 10-min timeout is a risk; watch and repair if needed | Evidence | test-coverage job gets 15 min for superset; diff-coverage runs full suite + diff-cover in 10. Also `-x` fail-fast means any flaky test fails the job | Accepted |
| A6 | p0-assessment rank 2/4 updates go in respective tasks (serial, different sections) | Decision | T002 edits rank 4 section; T003 edits rank 2 section; both after T001 | Accepted |
| A7 | atheris platform-gated to linux/x86_64 | Evidence | uv.lock has atheris wheels ONLY for manylinux x86_64, no sdist; `uv sync --python-platform macos` hard-fails | Confirmed |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | Do fuzz tests run now with atheris? | `uv run pytest tests/test_fuzz.py -q -m fuzz` | Read-only | 17 passed in 13.21s, none skipped | T002 removes skipif; CI will run them |
| R2 | Does CI install atheris? | Read ci.yml:165 sync step + uv.lock | Read-only | `--group dev` includes atheris>=3.1.0 (pyproject:208, uv.lock) | T001 push validates in CI |
| R3 | What's the safety job exposure? | Read ci.yml:254-280 | Read-only | Same-repo PR branches get SAFETY_API_KEY | T003 restricts to push |
| R4 | Can workflow_dispatch run PR-only jobs? | Read ci.yml on: triggers + job if: | Read-only | dispatch runs everything EXCEPT the two `pull_request`-gated jobs | T004 requires real PR |
| R5 | What pins safety job structure? | Read tests/test_workflow_configuration.py:103-117 | Read-only | Asserts current if: substrings + make safety-gate recipe | T003 must update test in lockstep |
| R6 | Does mutation-diff fail on surviving mutants? | Read mutmut __main__.py run path | Read-only | exit 0 unless clean-test failure; diagnostic only | T004 asserts job COMPLETES, not mutant kills |
| R7 | diff-coverage timeout risk? | Compare ci.yml timeouts | Read-only | 10 min (diff) vs 15 min (test-coverage) for superset work | Watch in T004; repair if timeout |
| R8 | Does atheris install on macOS/aarch64? | `uv sync --dry-run --python-platform macos` | Read-only | Hard-fails: atheris has only manylinux x86_64 wheels, no sdist | T001 platform-gates the dep |
| R9 | Does importorskip fail or skip? | Read pytest docs/source for importorskip | Read-only | Raises Skipped (exit 0) — NOT a failure | A2: use pytest.fail inside _run_harness |
| R10 | Does pip-audit currently find vulnerabilities? | `uv run pip-audit . --dry-run` | Read-only | "38 packages… No known vulnerabilities found" | New job won't fail PRs today |

## Design

### Workstream 1 — Push (T001, standalone)
Push `master` (atheris commit). First push triggers docs-check plugin (block once, retry — no CLI surface changed). The resulting CI run validates atheris install + 17 fuzz tests executing (visible in job log).

### Workstream 2 — Fuzz authority (T002)
- `ci.yml:151`: delete `continue-on-error: true`.
- `tests/test_fuzz.py`: replace 6 `skipif` decorators with module-level `pytest.importorskip("atheris")` after imports; delete `_HAS_ATHERIS` helper (now unused).
- `Makefile:520`: drop ` (non-authoritative until rank 4)`.
- `quality/remediation/p0-assessment.md` rank 4 section: mark complete with date + evidence.

### Workstream 3 — Secrets isolation (T003, serial after T002 — same file)
- `ci.yml` safety job `if:` → `github.event_name == 'push'` (master only; workflow_dispatch excluded — dispatch is human-triggered but can run any branch, so exclude for strictness; safety-gate still available via `make ci-trusted` in publish-to-pypi on tags).
- Add `pip-audit` job: `runs-on: ubuntu-latest`, timeout 10, `if: github.event_name != 'pull_request_target'` (runs on push + PR), steps: checkout, uv, python 3.12, `uv sync --all-extras --locked --group dev`, `make pip-audit`. No secrets.
- `tests/test_workflow_configuration.py:103-117`: update to assert new `if:` (push-only) and that pip-audit job exists with `make pip-audit` recipe.
- `quality/remediation/p0-assessment.md` rank 2 section: mark in-repo half complete; note admin half (protected env) remains.

### Workstream 4 — PR validation (T004, after T003 pushed)
1. Branch `ci/validate-pr-only-jobs` from master.
2. Trivial change: docstring tweak in `src/perplexity_cli/exit_codes.py` (smallest mutant count, ~36).
3. Commit + push branch; `gh pr create` with descriptive title/body.
4. `gh pr checks --watch` — assert:
   - `diff-coverage` runs, produces coverage.xml, diff-cover passes ≥90 within 10 min.
   - `mutation-diff` runs discover script with real base/head SHAs, mutates only exit_codes, completes ≤45 min.
   - `fuzz-status` runs (blocking now) — 17 tests visible.
   - `pip-audit` runs credential-free.
5. If diff-coverage times out → repair (bump timeout to 15, or needs:+artifact reuse of test-coverage job) → re-push PR → re-watch.
6. If mutation-diff fails → capture log, repair, re-run.
7. Optional second doc-only PR to confirm graceful no-op path (mutation-diff skips, diff-coverage trivially passes).
8. Close PRs, delete branch.

### Workstream 5 — Final (T005)
`make check`, full suite, update plan, tag `fuzz-secrets-pr-complete`.

## Execution Graph
```
T001 (push atheris) ──> T002 (fuzz) ──> T003 (secrets; serial: same ci.yml) ──> T004 (PR validation) ──> T005 (final)
```
Strictly serial: T002/T003 both edit ci.yml (different sections but same file — no parallel writes). T004 needs T003 pushed so the PR branch's workflow file includes all changes.

## File Collision Map
| File | Writers | Strategy |
|------|---------|----------|
| `.github/workflows/ci.yml` | T002 (fuzz-status), T003 (safety + pip-audit) | Serial: T002 then T003 |
| `tests/test_fuzz.py` | T002 only | Exclusive |
| `Makefile` | T002 only | Exclusive |
| `tests/test_workflow_configuration.py` | T003 only | Exclusive |
| `quality/remediation/p0-assessment.md` | T002 (rank 4), T003 (rank 2) | Serial (different sections) |
| `src/perplexity_cli/exit_codes.py` | T004 only (trivial docstring) | Exclusive |

## Numbered Plan

### 1. [pending] Platform-gate atheris + push master
- Task ID: T001
- Depends on: none
- Parallel group: serial
- Owned scope: `pyproject.toml` (atheris dep line 208), `uv.lock`, git push
- Actions:
  1. CRITICAL: atheris 3.1.0 has wheels ONLY for manylinux x86_64 (no sdist) — `uv sync --python-platform macos` hard-fails (verified). Change pyproject.toml:208 to:
     `"atheris>=3.1.0; sys_platform == 'linux' and platform_machine == 'x86_64'",`
  2. `uv lock` — regenerate lockfile with platform marker.
  3. Verify: `uv sync --all-extras --group dev` (linux OK); `uv sync --dry-run --python-platform macos` succeeds (atheris skipped, no error).
  4. Commit: `deps: platform-gate atheris to linux/x86_64 (no macos/aarch64 wheels)`.
  5. `git push origin master` — first attempt blocked by pre-push-docs-check opencode plugin (expected — verify no commands/ or README changes, retry; plugin allows second attempt).
  6. Watch CI: `gh run watch <id> --exit-status` — confirm fuzz-status shows 17 tests running AND test-macos green.
- Validation: push succeeds; CI green incl. macOS; fuzz-status log shows 17 passed (not skipped)
- Acceptance evidence: `origin/master` updated; CI run link showing both
- Recovery note: if macOS still fails, revert platform marker; evidence captured for repair

### 2. [pending] Make fuzz authority blocking
- Task ID: T002
- Depends on: T001
- Parallel group: serial
- Owned scope: `.github/workflows/ci.yml` (fuzz-status job only), `tests/test_fuzz.py`, `Makefile:520`, `quality/remediation/p0-assessment.md` (rank 4 section)
- Actions:
  1. `ci.yml:151`: remove `continue-on-error: true` line from fuzz-status job.
  2. `tests/test_fuzz.py`:
     - Delete `_HAS_ATHERIS = importlib.util.find_spec(...)` (line 28) AND `import importlib.util` (line 19) — otherwise F401 fails `make lint`.
     - Delete all 6 `@pytest.mark.skipif(not _HAS_ATHERIS, ...)` decorators (lines 60, 87, 110, 125, 144, 171).
     - Add at top of `_run_harness` (lines 37-51), BEFORE the subprocess call:
       ```python
       if importlib.util.find_spec("atheris") is None:
           raise ImportError("atheris required — run 'uv sync --all-extras --group dev'")
       ```
       Wait — that needs importlib.util; instead use a module-level `_HAS_ATHERIS`-style flag... NO. Simplest: keep the module-level check but make it FAIL:
       ```python
       if importlib.util.find_spec("atheris") is None:
           pytest.fail("atheris not installed — run 'uv sync --all-extras --group dev'")
       ```
       placed INSIDE `_run_harness` before the subprocess spawn. `pytest.fail` → real failure (exit 1). The 4 enforcement tests (lines 193-262) only AST-parse calls to `_run_harness` — never invoke it — so they pass everywhere, including macOS standard suite. Keep `import importlib.util`.
  3. `Makefile:520`: `ci-fuzz-status: test-fuzz ## CI fuzz status (authoritative)`.
  4. p0-assessment.md rank 4: mark complete (date, evidence: 17/17 run, blocking job, atheris platform-gated).
  5. Run `uv run pytest tests/test_fuzz.py -q -m fuzz` (17 passed), `make check`.
  6. Commit: `T002: make fuzz-status blocking — atheris required, no continue-on-error`.
- Validation: `grep -n 'continue-on-error' ci.yml` near fuzz-status → absent; `grep -n 'skipif' tests/test_fuzz.py` → absent; `make check` passes
- Acceptance evidence: AC2 met
- Recovery note: `git checkout` individual files to revert

### 3. [pending] Restrict safety job + add pip-audit
- Task ID: T003
- Depends on: T002
- Parallel group: serial
- Owned scope: `.github/workflows/ci.yml` (safety job + new pip-audit job), `tests/test_workflow_configuration.py`, `quality/remediation/p0-assessment.md` (rank 2 section)
- Actions:
  1. `ci.yml` safety job `if:` (lines 258-261) → `if: github.event_name == 'push'`.
  2. Add `pip-audit` job after safety: name `pip-audit`, ubuntu-latest, `timeout-minutes: 10` (REQUIRED — `test_ci_jobs_have_timeouts` at test_workflow_configuration.py:144-150 fails any job without it), no `if:` (omit — runs push + PR; no pull_request_target trigger exists in this repo), steps: checkout, setup-uv, setup-python 3.12, `uv sync --all-extras --locked --group dev`, `make pip-audit`. No env secrets.
  3. `tests/test_workflow_configuration.py:103-117`: rewrite `test_trusted_safety_job_excludes_forks_and_dependabot` → `test_safety_job_runs_only_on_push`. Exactly 3 assertions change: `!= 'pull_request'` (line 109), `head.repo.full_name == github.repository` (line 110), `actor != 'dependabot[bot]'` (line 111) → replace with `github.event_name == 'push'`. KEEP: no `RUN_SAFETY_FOR_DEPENDABOT` (line 112), `make safety-gate` in recipe (line 116), no `pull_request_target` (line 117). Add `test_pip_audit_job_is_credential_free`: pip-audit job exists, `make pip-audit` in recipe, `timeout-minutes` present, no `env:` secrets in job.
  4. p0-assessment.md rank 2: mark in-repo half complete; note admin half (protected env binding) remains.
  5. Run `uv run pytest tests/test_workflow_configuration.py -v`, `make check`.
  6. Commit: `T003: safety job push-only, add credential-free pip-audit to PR CI`.
- Validation: workflow-configuration tests pass; `grep -n 'SAFETY_API_KEY' ci.yml` shows only publish-to-pypi.yml usage; `make check` passes
- Acceptance evidence: AC3 met
- Recovery note: revert ci.yml + test file together (test pins workflow structure)

### 4. [pending] Validate PR-only jobs via real PR
- Task ID: T004
- Depends on: T003 (pushed to origin)
- Parallel group: serial
- Owned scope: git branch `ci/validate-pr-only-jobs`, `src/perplexity_cli/exit_codes.py` (trivial docstring tweak only)
- Actions:
  1. Push T003 to origin first (T001's push pattern; docs-check retry).
  2. `git checkout -b ci/validate-pr-only-jobs`; tweak one docstring in `exit_codes.py` (no behaviour change); commit `ci: exercise PR-only diff-coverage and mutation-diff jobs`; `git push -u origin ci/validate-pr-only-jobs`.
  3. `gh pr create --title "ci: validate PR-only jobs" --body "Trivial change to exercise diff-coverage and mutation-diff in real GitHub Actions."`
  4. `gh pr checks --watch` — observe all checks:
     - diff-coverage: must run + pass (watch 10-min timeout)
     - mutation-diff: must run + complete (mutates exit_codes only)
     - fuzz-status: blocking, 17 tests
     - pip-audit: credential-free run
     - all other standard jobs green
  5. If diff-coverage times out: bump `timeout-minutes` to 15 in ci.yml, commit, re-push, re-watch.
  6. If mutation-diff fails: capture log; repair (likely test-collection issue); re-push.
  7. Optional: doc-only PR (README touch) to confirm graceful no-op.
  8. Close PR(s); delete remote + local branch.
- Validation: `gh pr checks` shows both jobs green (or documented repair cycle)
- Acceptance evidence: AC4 met — screenshots/logs of both jobs
- Recovery note: PR can be closed/rebranched freely (no protection)

### 5. [pending] Final verification + checkpoint
- Task ID: T005
- Depends on: T004
- Parallel group: serial
- Owned scope: none (verification)
- Actions:
  1. `make check` — all gates.
  2. Full suite: `uv run pytest tests/ --dist=loadfile -n auto -m "not property and not hermetic_integration and not real_api and not manual and not real_user_config and not fuzz"` — 0 failures.
  3. `make test-fuzz` — 17 passed.
  4. Verify `origin/master` up to date; `git status` clean.
  5. Update plan to COMPLETE; tag `fuzz-secrets-pr-complete`.
- Validation: all above green
- Acceptance evidence: AC5 met; tag exists
- Recovery note: tag enables resume

## Verification Strategy
- **Incremental**: T002 → fuzz tests + make check; T003 → workflow-config tests + make check; T004 → gh pr checks.
- **Integration**: T005 make check + full suite + test-fuzz.
- **Final**: real PR evidence (both PR-only jobs green) is the acceptance proof.

## Risks And Recovery
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| atheris breaks macOS/aarch64 CI (no wheels) | Certain | High | T001 platform-gates to linux/x86_64 + regenerates lock BEFORE push (verified via --python-platform macos dry-run) |
| diff-coverage 10-min timeout (full suite + diff-cover) | Medium | Medium | Watch in T004; repair = bump to 15 or needs:+artifact. Note: `-x` fail-fast also fails the job on any flaky test |
| pip-audit finds a vulnerability → PR fails | Medium | Medium | That's the point (authoritative); currently clean (R10); repair = version floor per convention |
| Safety push-only breaks CI expectation | Low | Low | publish-to-pypi still runs make ci-trusted on tags; pip-audit covers PR lane |
| test_workflow_configuration pins break | Low | Medium | T003 updates test in same commit (exactly 3 assertions change) |
| Enforcement tests break on macOS (module-level abort) | Medium | High | A2: pytest.fail scoped INSIDE `_run_harness` — enforcement tests never invoke it |
| mutation-diff slow on larger PRs | Low | Low | 45-min timeout; diagnostic only (survivors don't fail) |

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---------|----------|------------|----------|
| (Self-critique) T002/T003 both edit ci.yml in "parallel" | HIGH | Corrected: strictly serial (T003 depends on T002) — same file | Collision map |
| (Self-critique) workflow_dispatch could validate PR jobs? | HIGH | Disproved: both jobs gate `if: pull_request`; dispatch skips them | R4 |
| H1: atheris Linux-only — test-macos CI will hard-fail on push | HIGH | T001 now platform-gates `atheris>=3.1.0; sys_platform == 'linux' and platform_machine == 'x86_64'` + regenerates lock BEFORE push | R8 verified via --python-platform macos dry-run |
| H2: importorskip = Skipped (exit 0), not failure | HIGH | A2: `pytest.fail(...)` inside `_run_harness` — genuine failure | R9 |
| H3: module-level abort kills 4 enforcement tests + macOS standard suite | HIGH | Scope the check inside `_run_harness` (only fuzz tests invoke it; enforcement tests only AST-parse) | test_fuzz.py:193-262 |
| H4: deleting `_HAS_ATHERIS` leaves unused `import importlib.util` → lint fails | HIGH | Keep `import importlib.util` (used by the new pytest.fail guard) | T002 action 2 |
| M1: "pre-push-docs-check plugin" claimed not to exist | MEDIUM | Plugin EXISTS at `.opencode/plugins/pre-push-docs-check.ts` (opencode plugin, not lefthook) — blocked push twice this session; T001 keeps the retry expectation | Session evidence |
| M2: exactly 3 of 6 workflow-config assertions change | MEDIUM | T003 action 3 enumerates which lines change vs stay | test_workflow_configuration.py:103-117 |
| M3: pip-audit currently clean | MEDIUM | Verified R10 — no PR failures today | `uv run pip-audit . --dry-run` |
| M4: gh pr checks --watch exits non-zero on failure | MEDIUM | T004 uses exit code, not eyeballing | gh 2.45 --help |
| L2: diff-coverage `-x` fail-fast exposure | LOW | Added to risk table | Makefile:322-326 |
| L3: pip-audit `if:` omit | LOW | Job has no `if:` (no pull_request_target trigger in repo) | ci.yml on: block |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|-----------|-------|------------|-------|-----------------|------------|
| 2026-07-31 | 0 | INTAKE | none | 4 workstreams scoped: push, fuzz, secrets, PR validation | DISCOVER |
| 2026-07-31 | 0 | DISCOVER→RESEARCH | none | 2 tracks: fuzz+secrets (A1-A7/B1-B7), PR validation (full job YAML + approach) | RESEARCH |
| 2026-07-31 | 0 | RESEARCH→DRAFT | none | Draft: 5 tasks, strictly serial (ci.yml single-writer) | DRAFT |
| 2026-07-31 | 0 | DRAFT→CRITIQUE | none | 4 HIGH (macOS wheels, importorskip=skip, module-abort kills enforcement, unused import) + MEDIUMs — all remediated | REMEDIATE |
| 2026-07-31 | 0 | REMEDIATE→VERIFY | none | T001 platform-gates atheris; T002 uses pytest.fail in _run_harness; T003 enumerates exact test changes; risks updated | VERIFY |
| 2026-07-31 | 0 | VERIFY→SAVED | none | Primary review: AC1-5 map to T001-T005; serial ci.yml single-writer; recovery notes present; evidence-based | SAVED |

## Completion Review
<filled by csm-build when all criteria are verified>
