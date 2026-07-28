# Selected Ranks Remediation Plan

> Run ID: 20260726-201025 (primary build)
> Follow-up Run ID: 20260728-0002 (pre-existing debt + gate activation)
> Base SHA: 88595a4ac30bcfd9586f37e26aad2430b04bf84e
> Final SHA: e1d90350467d74dac870c447677419e9200816ab
> Source: `.claude/plans/quality-infrastructure-selected-remediation-plan.md`
> Scope: Ranks 16, 17, 21, 25, 26, 29 plus bounded Rank 10 and 18 prerequisites

## 1. Durability Contract

- Every task runs in a persistent linked worktree with a unique branch.
- Task agents checkpoint with `git commit --no-verify` (hooks are shared across
  worktrees; coordinator owns validation).
- Integration commits carry `X-Run-Id`, `X-Task-Id`, `X-Attempt` trailers.
- Event files under `quality/evidence/remediation/<run-id>/events/` are the
  authoritative execution journal.
- `state.json` is a generated projection, never authoritative.
- No pushes, PRs, workflow dispatches, or settings changes.

## 2. Task Graph

```
Wave 0: COORD-BOOTSTRAP (coordinator serial)
  |
  v
Wave 1: A1-SEMGREP | A2-OPENCODE | A3-MUTATION-POLICY  (3 parallel)
  |
  v
Wave 2: B1-ANALYSER-CONTRACTS | B2-PY-QUALITY | B3-PY-QUALITY  (3 parallel)
  |
  v
Wave 3: P1-POLICY-FOUNDATION | G1-GITLEAKS-PREREQ  (2 parallel)
  |
  v
Wave 4: D1-CI | D2-HOOKS  (2 parallel, after Make freeze)
  |
  v
Wave 5: E1-MUTATION-SCHEDULED | E2-SEMGREP-SCHEDULED | E3-SCORECARD  (3 parallel)
  |
  v
Wave 6: F1-POLICY-COMPLETE | F2-DOCS  (2 parallel)
  |
  v
Wave 7: FINAL-ACCEPTANCE (coordinator serial)
  |
  v
Wave 8: DELIVER (fast-forward local master, stop before push)
```

## 3. Path Leases

### Wave 1

| Task | Existing files | New paths |
|---|---|---|
| A1-SEMGREP | `.semgrep.yml`, `.semgrep-architecture.yml`, `.semgrepignore`, `quality/semgrep-policy.toml`, `scripts/semgrep_policy.py`, `tests/test_semgrep_policy.py`, `tests/fixtures/semgrep/test-rules.yml`, `tests/fixtures/semgrep/*.py` | — |
| A2-OPENCODE | `.opencode/plugins/*.ts`, `.opencode/scripts/check-config.ts`, `.opencode/tests/**/*.ts`, `.opencode/eslint.config.mjs`, `.opencode/vitest.config.ts` | — |
| A3-MUTATION-POLICY | `scripts/discover_mutate_diff_files.py` | `scripts/mutation_policy.py`, `tests/test_mutation_policy.py`, `tests/fixtures/mutation_policy/**`, `quality/schemas/mutation-report.json` |

### Wave 2

| Task | Existing files | New paths |
|---|---|---|
| B1-ANALYSER-CONTRACTS | `scripts/check_analyser_contracts.py`, `quality/analyser-contracts.toml`, `tests/test_analyser_contracts.py`, `tests/fixtures/analyser_contracts/**` | — |
| B2-PY-QUALITY | Exact script list provided in task prompt (partition 1) | Matching test files |
| B3-PY-QUALITY | Exact script list provided in task prompt (partition 2) | Matching test files |

### Wave 3

| Task | Existing files | New paths |
|---|---|---|
| P1-POLICY-FOUNDATION | — | `scripts/validate_workflow_policy.py`, `scripts/validate_make_policy.py`, `tests/test_workflow_policy.py`, `tests/test_make_policy.py`, `tests/fixtures/workflow_policy/**`, `tests/fixtures/make_policy/**` |
| G1-GITLEAKS-PREREQ | `scripts/gitleaks_check.sh` | `tests/test_gitleaks_prepush.py`, `tests/fixtures/gitleaks/**` |

### Wave 4

| Task | Existing files | New paths |
|---|---|---|
| D1-CI | `.github/workflows/ci.yml` | — |
| D2-HOOKS | `lefthook.yml` | — |

### Wave 5

| Task | Existing files | New paths |
|---|---|---|
| E1-MUTATION-SCHEDULED | `.github/workflows/mutation-scheduled.yml` | — |
| E2-SEMGREP-SCHEDULED | `.github/workflows/semgrep-advisory.yml` | `scripts/semgrep_advisory_report.py`, `tests/test_semgrep_advisory_report.py` |
| E3-SCORECARD | `.github/workflows/scorecard.yml` | — |

### Wave 6

| Task | Existing files | New paths |
|---|---|---|
| F1-POLICY-COMPLETE | `tests/test_workflow_configuration.py`, `tests/test_quality_pipeline_configuration.py`, `tests/test_help_doc_drift.py` | Additional adversarial fixtures |
| F2-DOCS | `README.md`, `QUALITY_GATES.md`, `CONTRIBUTING.md` | — |

## 4. Coordinator-Only Files

Makefile, pyproject.toml, uv.lock, quality/gates.conf, .opencode/package.json,
.opencode/package-lock.json, .opencode/tsconfig.json, opencode.jsonc,
.importlinter, quality/baselines/**, quality/evidence/**, .claude/plans/**

## 5. Frozen Target Names (created by coordinator before Wave 4)

```
analyser-contract-tests
opencode-check
opencode-audit
mutate-full-policy
semgrep
semgrep-advisory-local
semgrep-advisory-report
actionlint
ci-static
ci-test-coverage
ci-test-compat
ci-fuzz-status
ci-property
ci-package
ci
ci-trusted
```

## 6. Completion Criteria Per Rank

| Rank | Component complete | Activation |
|---|---|---|
| 17 | Wrapper classifies all states; credential rule tested; fixtures complete; Make wired | Local `make semgrep` passes |
| 16 | ESLint errors fixed (not downgraded); package scripts wired; analyser contracts redesigned | Local `make opencode-check` and `make analyser-contract-tests` pass |
| 10 (prereq) | Mutation policy wrapper reads mutmut metadata; classifies states; emits report | Local `make mutate-full-policy` passes on fixture data |
| 18 (prereq) | Pre-push stdin contract tested; modes validated | Local fixture push test passes |
| 21 | CI job graph rewritten; pre-push staged; canonical targets frozen | Local semantic validation passes; activation pending test PR |
| 25 | Concurrency, timeouts, permissions on every CI job | Local semantic validation passes |
| 26 | All three scheduled workflows have timeouts, concurrency, reports, SARIF | actionlint passes; activation pending manual and schedule events |
| 29 | Semantic validators parse YAML/Make; adversarial fixtures fail; docs match config | Local policy tests pass |

## 7. Follow-Up Run (20260728-0002) — Cyclic State Machine

Executed as a cyclic state machine with parallel agent dispatch, validation
gates, and repair loops per phase.

### Category A — Pre-Existing Debt (All Complete)

| Item | Gate | Phase | Status |
|------|------|-------|--------|
| A1 | CHECK_ARCH | P2 | true (4 baselined violations) |
| A2 | CHECK_COUPLING | P3 | true (--blocking flag added, MAX_FLAGGED=40) |
| A3 | CHECK_RATCHETS | P1 | true |
| A4 | CHECK_DEPTRY | P1 | true (tomli/grimp added to dev deps) |
| A5 | CHECK_IMPORT_LINTER | P3 | true (12 contracts, independence re-enabled) |
| A6 | CHECK_DYNAMIC_IMPORTS | P2 | true (0 violations) |
| A7 | function-local-import | P4 | 111 → 3 findings (97% reduction) |
| A8 | .opencode pins | P1 | 5 ranges → exact versions |

### Category B — Signed-Off Infrastructure Verification

| Item | Status | Blocker |
|------|--------|---------|
| B1 Scheduled mutation | Local validation complete | Requires `git push` + `workflow_dispatch` |
| B2 Scorecard OIDC/SARIF | Local validation complete (checklist written) | Requires `git push` + `workflow_dispatch` |
| B3 Safety credentials | Pending | Requires `git push` + repo secret verification |
| B4 macOS wheel smoke | Pending | Requires `git push` + CI observation |
| B5 Actionlint pinning | Complete | Verified at 1.7.12.24 via uvx |

### CSM Run (20260728-0100) — Items 2, 3, 5, 8, 9

| Phase | Work | Status |
|-------|------|--------|
| P2 | Move 52 function-local imports to top level (7 runner files) | ✅ 55→4 findings |
| P1 | Fix 95+ test mock patch targets (14 test files) | ✅ 2,267 tests pass |
| P3A | Full mutmut run (9,229 mutants, 4 children) | ✅ 5,150 killed (55.8%) |
| P3B | Scorecard local validation + checklist | ✅ |
| P3C | Gitleaks end-to-end verification + checklist | ✅ |
| P4 | Mutation baseline + docs | ✅ |
| P5 | Final local acceptance | Pending |
| P6 | Push + CI monitor + fix cycle | Pending |

### Final Acceptance (S_FINAL_ACCEPTANCE — Complete)

| Gate | Result |
|------|--------|
| `make check` (12/12 toggles) | Pass |
| `make ci` (2,267 tests, 93% coverage) | Pass |
| `make semgrep` | 0 findings |
| `make gitleaks-ci` (630 commits) | 0 leaks |
| `make ratchets` (83 identities, 4 arch) | Pass |
| `make opencode-check` (109 tests) | Pass |
| `make opencode-audit` | 0 vulnerabilities |
| `make import-linter` (12 contracts) | 0 broken |
| `make arch-check` (4 baselined) | Pass |
| `make coupling-check` (34/40 flagged) | Pass |
| `make mutate-full-policy` (9,229 mutants) | 55.8% kill rate |

### Remaining Work

P5 (final acceptance re-run) and P6 (push + CI cycle) remain.
B1-B4 require `git push` to validate.
