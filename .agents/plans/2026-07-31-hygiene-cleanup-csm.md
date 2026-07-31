# Hygiene Cleanup CSM Plan — Suppressions, Tests Audit, Semgrep, Docs, Test Failures

## Control
- Plan ID: hygiene-cleanup-2026-07-31
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Last checkpoint: `653876b` (final hardening cleanup complete, tag `hardening-final-complete`)
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Close out 5 remaining hygiene items with correct, evidence-based scope:
1. **Grandfathered suppressions**: format the 91 grandfathered `# noqa`/`# nosec`/`# nosemgrep` comments with `owner: X; reason: Y` (two-comment pattern only), leaving 9 test-fixture entries and 1 docstring false-positive untouched.
2. **tests/** per-file-ignores audit**: remove exactly 3 dead rules (F821, DOC, FURB) — the other 29 rules are live (they suppress 10,302 findings).
3. **click-echo findings**: fix the root cause — `.semgrep.yml` exclusion glob predates the `http_errors.py`→`http_errors/impl.py` package move; update glob so 9 baselined findings disappear (no suppressions added).
4. **Item 13**: mark COMPLETE — mechanism is deleted; remaining references are historical records only.
5. **Pre-existing test failures**: refresh stale `coupling-report.json` baseline (26→29) and make the command_runner config test hermetic (explicit `output_format="human"`).

Deliverables: reduced suppression baseline, clean per-file-ignores, zero click-echo baselined findings, item 13 closed, 2 test failures fixed.
Constraints: `make check` must pass after each task. No new suppressions added. No gate weakening. All `nosemgrep`/`nosec` formatting uses the two-comment pattern `# <suppression>  # owner: X; reason: Y` (single-comment `; owner:` breaks semgrep/bandit parsing — verified).
Exclusions: test fixtures in `test_suppression_reasons.py`/`test_suppressions.py` (9 entries — formatting them breaks meta-tests). The docstring false-positive at `scripts/check_suppression_reasons.py:3` is fixed by rewording (removed from scan — not grandfathered). The 2 `function-local-import` baselined findings stay (different rule, unrelated).

## Acceptance Criteria
1. `make suppression-reasons` reports grandfathered count reduced to exactly 9 (all remaining are test-fixture entries in `test_suppression_reasons.py`/`test_suppressions.py`), formatted count = 117 (126 − 9).
2. `"tests/**/*.py"` per-file-ignores contains 29 rules (F821, DOC, FURB removed). `make check` passes.
3. `quality/baselines/semgrep-architecture.json` contains only the 2 `function-local-import` fingerprints (0 click-echo). `make semgrep-architecture` passes.
4. `quality/remediation/outstanding-work.md:27` item 13 marked **COMPLETE** with date.
5. `tests/test_coupling_metrics.py::TestTrendCompare::test_trend_compare_against_self_is_unchanged` passes (baseline refreshed to 29/103, under MAX_FLAGGED=30).
6. `tests/test_command_runner.py::test_run_set_config_command_handles_configuration_error` passes under xdist (hermetic).
7. `make check` passes all 13 gates; `make test` has 0 failures attributable to this work.

## Current-State Evidence
- Suppression gate: `Suppression-reason enforcement passed: 126 suppression(s) total; 35 formatted, 91 grandfathered.` 91 = 39 noqa + 35 nosec + 17 nosemgrep. By dir: scripts/ 54, tests/ 37, src/ 0. **47 of 91 already carry owner/reason on the line above** (scripts/ nosec B404/B603, nosemgrep boolean-flag-argument) — merge work, not fresh writing.
- `pyproject.toml:127` `"tests/**/*.py"` = 32 rules. Synthetic-config audit (config minus tests ignores): 10,302 findings; 29 rules fire, **3 dead** (F821=0, DOC=not enabled, FURB=not enabled).
- `.semgrep.yml:525` excludes `"**/utils/http_errors.py"` (single file) — but handlers moved to `utils/http_errors/impl.py` in commit `2435f83`; 9 `click-echo-outside-presentation` fingerprints baselined in `semgrep-architecture.json` (lines 5-13). Verified: two-comment nosemgrep suppresses; single-comment `; owner:` does NOT.
- `outstanding-work.md:27` item 13 marked PARTIAL. `git grep` shows remaining `plan-gate` refs only in: `.agents/plans/*.md` (historical), `quality/evidence/.../0003-baseline-captured.json:50` (stale snapshot), `tests/test_removed_plan_gate.py` (the enforcement test itself), `tests/test_help_doc_drift.py:418,452` (comments), `outstanding-work.md:27`. No live claims in README/QUALITY_GATES/CONTRIBUTING/Makefile/lefthook/opencode.
- `tests/test_coupling_metrics.py:364` fails: baseline `coupling-report.json` (26 flagged, 97 modules, timestamp 2026-07-31T08:21:52, commit `1421b6f`) vs current 29 flagged / 103 modules. 3 added modules: `contracts.query`, `utils.http_errors.contracts`, `utils.logging.impl` — all from legitimate P2 refactors. 29 < MAX_FLAGGED=30 so refresh is safe.
- `tests/test_command_runner.py:102-113` fails under xdist: `run_set_config_command` resolves `output_format` from process-global Click context stack (`config.py:61-63`); a leaked `json=True` context makes the handler write JSON envelope to stdout + exit 7 instead of `[ERROR]` + exit 1. Passes standalone.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | Two-comment pattern only for nosemgrep/nosec formatting | Decision | Verified: `# nosemgrep: rule  # owner: X; reason: Y` suppresses; `; owner:` does not. Bandit NOSEC regex also requires it | Confirmed |
| A2 | 9 test-fixture suppressions stay grandfathered | Decision | Formatting flips them to passing inputs, breaking enforcement meta-tests | Confirmed |
| A3 | click-echo root fix = exclusion glob update, not inline suppressions | Decision | Glob predates file→package move; no code change needed | Confirmed |
| A4 | Coupling baseline refresh is safe (29 < 30) | Evidence | 3 added modules are legitimate refactor outputs; MAX_FLAGGED=30 | Confirmed |
| A5 | command_runner fix = explicit output_format="human" | Decision | Matches `_get_json_mode_from_ctx()` fallback; no Click context pin needed | Accepted |
| A6 | 47 "merge" suppressions reuse existing reason text | Evidence | Owner/reason already on line above, dash-style; merge inline + delete standalone line | Confirmed |
| A7 | Item 13 closes without editing historical evidence JSON | Decision | Historical snapshots stay as-is; only outstanding-work.md status changes | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | How many suppressions are grandfathered and why? | Replicated `check_suppression_reasons.py` classification; per-fingerprint source check | Read-only; git status clean | 91 grandfathered: 47 have prev-line justification (merge), ~34 need new text, 9 test fixtures, 1 docstring false-positive | T002 splits into merge vs new-text vs skip |
| R2 | Which tests per-file-ignores are dead? | Synthetic ruff config in /tmp/opencode minus tests ignores; `--statistics` | Temp file outside repo; repo untouched | 10,302 findings from 29 rules; exactly 3 dead (F821, DOC, FURB) | T001 removes exactly 3 codes |
| R3 | Does two-comment nosemgrep suppress click-echo? | Probe files vs `.semgrep.yml` rule; both formats | Read-only probes | Two-comment suppresses; `; owner:` does not | A1; T003 uses glob fix instead |
| R4 | What is stale in coupling baseline? | `scripts/check_coupling.py --trend-compare` live run | Read-only | 29 vs 26, +3 modules (contracts.query, http_errors.contracts, logging.impl), 103 vs 97 | T005 refreshes baseline |
| R5 | Why does command_runner test flake under xdist? | Standalone pass; simulated leaked Click context with json=True | Simulated in-memory only | JSON envelope to stdout + exit 7 vs expected [ERROR] + exit 1 | T006 passes output_format="human" |
| R6 | What plan-gate refs remain? | `git grep` plan-gate/plan_gate/quality-plan across tracked files | Read-only | Only historical/evidence/test-comment refs; no live claims | T004 marks item 13 COMPLETE |

## Design

5 independent workstreams, 1 big task (T002) with its own internal order:

- **T001 (S)**: Remove `F821`, `DOC`, `FURB` from `"tests/**/*.py"` per-file-ignores in `pyproject.toml`. Verify clean.
- **T002 (M, bulk)**: Format 91 grandfathered suppressions:
  1. Phase A — merge 47: inline the prev-line `# owner: ...; reason: ...` into the suppression line (two-comment pattern), delete the standalone comment line.
  2. Phase B — new text ~34: add `# <suppression>  # owner: quality-infrastructure; reason: <contextual>` using suggested mapping (subprocess B404/B603, boolean-flag-argument, E402-after-sys.path, D test exemptions, F401 optional-dep probes, getattr-with-string-literal).
  3. Reword `scripts/check_suppression_reasons.py:3` docstring to drop `# nosec` literal (stops false positive).
  4. Do NOT touch 9 fixture entries in `test_suppression_reasons.py`/`test_suppressions.py`.
  5. Run `make suppression-reasons` (verify formatted ↑, grandfathered ↓ to ≤12), `make semgrep`, `make bandit` (bandit NOSEC regex must parse).
  6. Run `uv run python scripts/check_suppression_reasons.py --update-baseline` LAST to refresh (also fixes 3 stale line numbers).
- **T003 (S)**: `.semgrep.yml:525` — change `- "**/utils/http_errors.py"` → `- "**/utils/http_errors/**"`. Run `check_semgrep_architecture.py --update-baseline` (drops 9 click-echo; 2 function-local-import remain). No suppressions added.
- **T004 (S)**: `outstanding-work.md:27` — PARTIAL → COMPLETE with date + note that remaining refs are historical records.
- **T005 (S)**: Refresh coupling baseline: `uv run python scripts/check_coupling.py --update-baseline` (or make target) → 29 flagged / 103 modules. Verify trend test passes.
- **T006 (S)**: `tests/test_command_runner.py:102-113` — pass `output_format="human"` to `run_set_config_command` call; verify under xdist.
- **T007 (S)**: Final integration: `make check` + `make test` + targeted tests. Checkpoint tag `hygiene-cleanup-complete`.

## Execution Graph
```
T001 (ignores) ──────────┐
T002 (91 suppressions) ──┤  all independent (disjoint files)
T003 (.semgrep.yml) ─────┼── T007 (verify) ── complete
T004 (item 13) ──────────┤
T005 (coupling) ─────────┤
T006 (test fix) ─────────┘
```

## File Collision Map
| File | Writers | Strategy |
|------|---------|----------|
| `pyproject.toml` | T001 only | Exclusive |
| `.semgrep.yml` + `semgrep-architecture.json` | T003 only | Exclusive |
| `suppression-reasons.json` + `scripts/*` + `tests/` (suppression-bearing files) | T002 only | Exclusive |
| `tests/test_command_runner.py` | T006 only; T002 must NOT touch it | Exclusive |
| `outstanding-work.md` | T004 only | Exclusive |
| `coupling-report.json` | T005 only | Exclusive; T005 serial after T002 (T002 edits check_coupling.py) |
| `quality/baselines/suppressions.json` | T002 (via --update-baseline) only | Exclusive |

## Numbered Plan

### 1. [pending] Remove dead rules from tests/** per-file-ignores
- Task ID: T001
- Depends on: none
- Parallel group: G1
- Owned scope: `pyproject.toml` ([tool.ruff.lint.per-file-ignores."tests/**/*.py"])
- Actions:
  1. Remove exactly `F821`, `DOC`, `FURB` from the `"tests/**/*.py"` rule list (29 remain). DOC/FURB aren't even in global select — safe. F821 fires 0 times on tests/.
  2. Run `uv run ruff check tests/ --statistics` → All checks passed.
  3. Run `make check`.
- Validation: `ruff check tests/` exits 0; grep pyproject.toml shows F821/DOC/FURB absent from tests entry
- Acceptance evidence: per-file-ignores has 29 rules; gates pass
- Recovery note: `git checkout pyproject.toml` restores

### 2. [pending] Format 91 grandfathered suppressions
- Task ID: T002
- Depends on: none
- Parallel group: G1
- Owned scope: all scripts/ + tests/ files bearing the 91 suppressions (NOT `tests/test_command_runner.py`, NOT `tests/test_suppression_reasons.py` fixtures lines 56,64,72,257,261, NOT `tests/test_suppressions.py` fixture lines 95,123,142,147), `scripts/check_suppression_reasons.py` (docstring only), `quality/baselines/suppression-reasons.json` (via script)
- Actions:
  1. **Merge 47**: for scripts/ entries where `# owner: ...; reason: ...` sits on the line above the suppression — move it inline after the suppression token using two-comment pattern, delete the standalone comment line. (Note: the dash-style `# owner: api-contract - <text>` comments in `src/` files are already-formatted lines, NOT in the merge set — do not touch them.)
  2. **New text ~34**: add two-comment annotations per suggested mapping (R1): `# nosec B404  # owner: quality-infrastructure; reason: <existing reason text>`; `# nosec B603  # owner: quality-infrastructure; reason: ...`; `# nosemgrep: boolean-flag-argument  # owner: quality-infrastructure; reason: ...`; `# noqa: E402  # owner: quality-infrastructure; reason: repo-relative import after sys.path setup`; `# noqa: D  # owner: quality-infrastructure; reason: test modules exempt from pydocstyle`; `# noqa: F401  # owner: quality-infrastructure; reason: optional dependency availability probe` (EXCEPT `tests/test_init_policy.py:258` which imports `perplexity_cli.formatting` for side-effect registration — reason: "side-effect import registers built-in formatters"); `# nosemgrep: getattr-with-string-literal  # owner: quality-infrastructure; reason: heterogeneous ast.AST nodes expose optional location attributes`.
  3. Reword `scripts/check_suppression_reasons.py:3` docstring: replace `` ``# nosec`` `` with `` ``nosec`` `` (drop `#` prefix) so the nosec regex stops matching the docstring.
  4. Do NOT modify the 9 fixture entries.
  5. Run `make suppression-reasons` — expect formatted ≥ 115, grandfathered ≤ 12 (9 fixtures + up to 3 stragglers).
  6. Run `make semgrep` (0 blocking) and `make bandit` (nosec parsing OK).
  7. Run `uv run python scripts/check_suppression_reasons.py --update-baseline` LAST.
  8. Run `make check`.
- Validation: `make suppression-reasons` shows grandfathered ≤ 12; `make semgrep` 0 blocking; `make bandit` clean; `make check` passes
- Acceptance evidence: baseline refreshed, formatted ≥ 115, all gates pass
- Recovery note: revert per-file with `git checkout <file>`; baseline regenerable via `--update-baseline`

### 3. [pending] Fix click-echo exclusion globs + refresh semgrep-architecture baseline
- Task ID: T003
- Depends on: none
- Parallel group: G1
- Owned scope: `.semgrep.yml` (lines ~427 and ~525), `quality/baselines/semgrep-architecture.json`
- Actions:
  1. Change `- "**/utils/http_errors.py"` → `- "**/utils/http_errors/**"` in BOTH occurrences: the `click-echo-outside-presentation` rule (~line 525) AND the `ad-hoc-http-status-classification` rule (~line 427). Both globs are stale after the file→package move and should track the package.
  2. Run `uv run python scripts/check_semgrep_architecture.py --update-baseline` — 9 click-echo fingerprints drop, 2 function-local-import remain.
  3. Run `make semgrep` + `make semgrep-architecture` + `make check`.
- Validation: `semgrep-architecture.json` has exactly 2 fingerprints; `make semgrep-architecture` passes
- Acceptance evidence: 0 click-echo baselined findings
- Recovery note: `git checkout .semgrep.yml` + regenerate baseline

### 4. [pending] Close out outstanding-work item 13
- Task ID: T004
- Depends on: none
- Parallel group: G1
- Owned scope: `quality/remediation/outstanding-work.md` (line 27 only)
- Actions:
  1. Edit item 13: `**PARTIAL: ...**` → `**COMPLETE (2026-07-31): mechanism deleted, stale mutmut ignore removed, no live documentation claims remain (remaining refs are historical records).**`
- Validation: item 13 status says COMPLETE with date
- Acceptance evidence: doc updated
- Recovery note: `git checkout quality/remediation/outstanding-work.md`

### 5. [pending] Refresh coupling baseline
- Task ID: T005
- Depends on: T002 (serial — T002 edits `scripts/check_coupling.py` lines 51-52; baseline refresh must run after)
- Parallel group: G1 (runs after T002 completes)
- Owned scope: `quality/baselines/coupling-report.json` (via script output redirect)
- Actions:
  1. NOTE: `check_coupling.py` has NO `--update-baseline` flag (verified: only `--json, --threshold, --max-flagged, --trend-compare, --blocking, --module`). The baseline is refreshed by redirecting JSON output — the output schema matches the baseline file exactly (`report_version: 1`):
     ```
     uv run python scripts/check_coupling.py --json > quality/baselines/coupling-report.json
     ```
  2. Verify 29 flagged / 103 modules recorded in the file.
  3. Run `uv run pytest tests/test_coupling_metrics.py::TestTrendCompare -v` — trend test passes.
  4. Run `make coupling-check` (NOT `check-coupling` — that target does not exist).
- Validation: trend test passes; `make coupling-check` passes (29 < MAX_FLAGGED=30)
- Acceptance evidence: baseline refreshed, trend test green
- Recovery note: baseline regenerable via redirect; 29 < MAX_FLAGGED=30 so no gate risk

### 6. [pending] Make command_runner config test hermetic
- Task ID: T006
- Depends on: none
- Parallel group: G1
- Owned scope: `tests/test_command_runner.py` (test at lines ~102-113)
- Actions:
  1. In `test_run_set_config_command_handles_configuration_error`, pass `output_format="human"` to the `run_set_config_command(...)` call so the error path uses the human handler regardless of leaked Click context.
  2. Run standalone: `uv run pytest tests/test_command_runner.py::test_run_set_config_command_handles_configuration_error -v`.
  3. Run under xdist 3×: `uv run pytest tests/test_command_runner.py -n 8 --dist loadfile -k test_run_set_config -q --count=3` (if pytest-repeat available) or run the full file with `-n 8` a few times.
  4. Run `make test` — confirm no regression.
- Validation: test passes standalone AND under xdist; `make test` clean
- Acceptance evidence: flake eliminated
- Recovery note: `git checkout tests/test_command_runner.py`

### 7. [pending] Final integration verification
- Task ID: T007
- Depends on: T001, T002, T003, T004, T005, T006
- Parallel group: none (serial final)
- Owned scope: none (verification only)
- Actions:
  1. `make check` — all 13 gates.
  2. `make test` — full suite; only known-ok skips remain.
  3. `uv run pytest tests/test_coupling_metrics.py tests/test_command_runner.py -q` — both fixed tests green.
  4. Note: `make semgrep` reports click-echo as advisory (non-blocking rule), so T007 relies on T003's `--update-baseline` output (2 fingerprints) as the real click-echo verification.
  5. Create tag: `git tag hygiene-cleanup-complete`.
- Validation: all gates + tests pass
- Acceptance evidence: tag exists, acceptance criteria 1-7 met
- Recovery note: tag enables resume

## Verification Strategy
- **Incremental**: per-task narrow checks (T001 ruff, T002 suppression-reasons+semgrep+bandit, T003 semgrep-architecture, T005 trend test, T006 xdist runs).
- **Integration**: T007 `make check` + `make test`.
- **Final**: tag `hygiene-cleanup-complete`.

## Risks And Recovery
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Wrong suppression format (single-comment `; owner:`) breaks semgrep/bandit | Medium | High | Two-comment pattern mandated (A1); `make semgrep` + `make bandit` in T002 validation |
| Formatting test-fixture suppressions breaks meta-tests | Medium | High | 9 fixture entries explicitly excluded (A2) |
| Baseline refresh order wrong (update-baseline before formatting) | Medium | Medium | --update-baseline runs LAST in T002 (step 7) |
| Coupling refresh pushes past MAX_FLAGGED=30 | Low | Low | 29 < 30 verified; only 3 legit modules added |
| xdist flake persists after output_format fix | Low | Medium | Root cause (Click context leak) addressed directly; validate with repeated xdist runs |
| E402 noqa on import lines after sys.path — semgrep getattr rule still fires | Low | Medium | Inline nosemgrep already present; verify with `make semgrep` |

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---------|----------|------------|----------|
| (Self-critique) Single-comment `; owner:` format proposed in earlier plan breaks semgrep | HIGH | Corrected: two-comment pattern only; T003 uses glob fix instead of inline annotations | R3 empirical probe |
| (Self-critique) "Format all 91" naive — fixtures break meta-tests | HIGH | 9 fixture entries excluded from scope (A2) | R1 classification |
| (Self-critique) tests/** ignores: assumed mostly dead like src/ | MEDIUM | Audit shows 29/32 live (10,302 findings suppressed); remove only 3 | R2 statistics |
| (Self-critique) Baseline refresh order could grandfather unformatted | MEDIUM | --update-baseline explicitly LAST in T002 | R1 caution note |
| H1: T005 refresh commands don't exist (`--update-baseline` flag absent, `make check-coupling` not a target) | HIGH | Corrected: baseline refreshed via `--json >` redirect (schema matches exactly); validation uses `make coupling-check` | Critic verified output schema matches baseline; last refreshed `290b2af` |
| M1: second stale glob at `.semgrep.yml:427` (`ad-hoc-http-status-classification` rule) | MEDIUM | Corrected: T003 updates BOTH globs (~427 and ~525) | Critic semgrep probe: glob fix yields exactly 2 fingerprints |
| M2: T005 races T002 (both involve check_coupling.py) | MEDIUM | Corrected: T005 depends on T002 (serial) | Collision map updated |
| L1: AC1 math (12 vs actual 9) | LOW | Corrected: AC1 says exactly 9 grandfathered / 117 formatted | Docstring reworded (removed from scan), fixtures only remaining |
| L2: Goal contradicts exclusion (docstring "untouched" vs reworded) | LOW | Corrected: exclusions text now says docstring fixed by rewording, not grandfathered | — |
| L3: dash-style normalisation is no-op (dash style in src/ already-formatted lines) | LOW | Corrected: merge step says do not touch src/ dash-style lines | Critic verified 47 merge entries already `;`-separated |
| L4: F401 mapping wrong for test_init_policy.py:258 (side-effect import) | LOW | Corrected: mapping notes the registration-import exception | test_init_policy.py:258 inline comment |
| L5: "13 gates" vs 14 prereqs (module-coverage unconditional) | LOW | Accepted as-is (cosmetic, inherited) | Makefile:496-498 |
| L6: `make semgrep` can't verify click-echo outcome (advisory) | LOW | Noted in T007 — real check is T003 step 2 output | semgrep_policy.py registration |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|-----------|-------|------------|-------|-----------------|------------|
| 2026-07-31 | 0 | INTAKE | none | 5 hygiene items scoped from prior completion review | DISCOVER |
| 2026-07-31 | 0 | DISCOVER→RESEARCH | none | 3 parallel tracks: suppressions (R1), tests ignores (R2), click-echo/item13/tests (R3-R6) | RESEARCH |
| 2026-07-31 | 0 | RESEARCH→DRAFT | none | Draft written: 7 tasks, 5 workstreams, disjoint file ownership | DRAFT |
| 2026-07-31 | 0 | DRAFT→CRITIQUE | none | 1 HIGH (T005 refresh cmd), 2 MEDIUM (427 glob, T002/T005 race), 6 LOW — all remediated | REMEDIATE |
| 2026-07-31 | 0 | REMEDIATE→VERIFY | none | T005 rewritten (--json redirect, coupling-check), T003 covers both globs, T005 serial after T002, text fixes L1-L4 | SAVED |

## Completion Review
<filled by csm-build when all criteria are verified>
