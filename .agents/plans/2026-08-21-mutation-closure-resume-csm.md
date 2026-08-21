format: csm-plan/1

# Mutation Closure Resume CSM Plan

## How To Execute

- Start work only through a separate, explicit csm-build invocation naming this plan (`2026-08-21-mutation-closure-resume-csm.md`); this planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 20 tasks (T003-T022); 13 high-risk (T003, T004, T005, T006, T007, T008, T010, T011, T014, T015, T019, T020, T022) always require independent review. Remediation tasks inherit risk from production/test churn at scale.

## Control

- Plan ID: mutation-closure-resume
- Status: in_progress
- Current CSM state: CHECKPOINT
- Cycle: 0
- Commits: allowed
- Last checkpoint: 2026-08-21 - T003 verified: 176-test acceptance signal passes; full ci-conventional exit 0; independent review returned 7 findings, all repaired (F1 empty-diff dead lane, F2 injection guards, F3 offline env, F4 signal forwarding, F5 RECORD matrix+version derivation, F6 strict package prefix, F7 sentinel/test gaps); suppression baseline refreshed to 101 identities
- Last model/run: ox-alpha-free / csm-build session of 2026-08-21
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none
- Resume: re-read Last checkpoint, latest journal row, Recovery notes of all non-COMPLETE tasks, Discovered Requirements, and the working-tree diff

## Goal

Complete the repository's full-tree mutation debt closure by resuming the interrupted execution of the superseded plan `2026-08-15-full-tree-mutation-debt-closure-csm.md`:

1. Finish T003: adopt the already-implemented canonical fresh-run orchestrator (`scripts/run_mutation.py`, currently uncommitted) through Makefile adapters and its test matrices, eliminating every raw-Mutmut bypass.
2. Land T004-T006: mandatory CI mutation evidence, authoritative full-tree baseline/manifests, and complete triage classification.
3. Execute remediation waves T007-T021 exactly as composed in the superseded plan (same task IDs, module ownership, dependency graph, and acceptance signals).
4. Prove closure twice with cache-free local full-tree runs (T022).

Constraints inherited unchanged: findings block; no score thresholds or waivers; exclusions limited to independently proven non-executable abstract/Protocol declarations; fail-closed on skipped/not-checked/interrupted/no-tests/stale/empty/malformed evidence; sanitised credential-free sandboxes; no live Perplexity/S3/browser access; push/dispatch requires separate user authorisation.

Exclusions inherited: release hardening/GitHub governance, deferred F007 live-API repair, parked WARP work, unrelated analyser contracts, broad refactoring without a demonstrated mutant distinction.

## Acceptance Criteria

1. No Make target invokes raw `mutmut run`; every mutation lane routes through the canonical runner and policy with schema-valid reports. Evidence: make-policy contract tests plus grep audit.
2. CI PR-diff lane blocks on mutation findings/incomplete evidence; scheduled lane publishes complete v2 report artefacts; documentation matches behaviour. Evidence: workflow-policy tests, doc tests.
3. One immutable candidate SHA carries baseline ledger, per-module ownership manifests, triage classification, timeout triple-kill records, and any structural-exclusion manifest. Evidence: `make mutation-baseline`/`mutation-manifest-check` exits 0 on the frozen candidate.
4. Zero survived/timeout/suspicious/executable no-tests mutants remain across all 105 configured modules (count sourced from the superseded plan's exhaustive ownership ledger of `pyproject.toml [tool.mutmut] paths_to_mutate = ["src/perplexity_cli/"]`; superseded plan §Current-State/Design). Evidence: two independent clean full runs (T022) with identical generated/result/environment digests.
5. Every changed test/helper keeps CC <= 5 and files <= 1,000 lines; ledger discipline continues for any newly protected assertion. Evidence: validators in focused suites.

## Current-State Evidence

- HEAD `40fb64b`, branch ahead 3; worktree clean except five enumerated T003 carry-over paths (git status 2026-08-21).
- Carry-over diff: `.agents/plans/2026-08-15...csm.md` (+19/-11 journal), `pyproject.toml` (2 meta-test ignores), `tests/test_quality_pipeline_configuration.py` (+2 assertions; 27 pass), `scripts/mutation_policy.py` (`_MUTMUT_PREFIX` -> public `MUTMUT_PREFIX`), new `scripts/run_mutation.py` (~700 lines).
- `run_mutation.py` static state: Ruff clean, Pyright strict clean, Semgrep zero findings, all functions CC <= 5, `--help` smoke passes; RECORD verification probe verified 15/15 installed Mutmut 3.5.0 files against dist-info hashes.
- Raw bypasses remain: `Makefile:287-288` (`mutate`), `290-293` (`mutate-full-policy` calls compatibility CLI that now always fails closed), `298-302` (`mutate-module` passes filesystem path), `304-319` (`mutate-diff` swallows discovery exit codes via mapfile process substitution; prefix-spilling patterns; broken `__init__` mapping). Defaults at `Makefile:375-376`: `BASE_SHA ?= origin/main`, `TESTED_SHA ?= HEAD`.
- Branch is `master...origin/master`; the `origin/main` default is inconsistent with the actual remote head and must be verified/repaired in T003.
- Superseded plan remains the detailed source for wave composition: task bodies for T004-T022 at lines 281-564, tier table at 569-581, dependency spine at 218-229.

## Assumptions And Decisions

| ID | Statement | Type | Evidence or rationale | Status |
| --- | --------- | ---- | --------------------- | ------ |
| A1 | This plan supersedes the 2026-08-15 plan for all remaining execution; the old file is marked paused and referenced as wave-composition detail | decision | Two active plans would create selection ambiguity in csm-build | accepted |
| A2 | Manifest-consuming tier targets move out of T003 into the tasks that produce their artifacts | decision | Integration review finding: contract-testing manifest consumers is impossible before schemas exist (T005/T006 outputs) | accepted |
| A3 | T004 additionally owns the pre-push deadline wiring inside `lefthook.yml` (that stanza only) | decision | Integration review gap #10: otherwise no owner derives an outer budget for pre-push | accepted |
| A4 | Uncommitted T003 carry-over is finished and committed inside new-plan T003, never discarded or reset | decision | Preserves verified in-flight work; recovery package discipline from cycle 1 applies | accepted |
| A5 | `BASE_SHA ?= origin/main` default is wrong for this repository and gets corrected during T003 adapter work | inference | Remote tracking branch is `origin/master` (git status) | open - verify in T003 |
| A6 | Remediation waves T007-T021 keep their original IDs, module ownership, dependency edges, and acceptance signals verbatim | decision | Those definitions were planned, critiqued twice, and verified READY in the superseded plan | accepted |

## R&D Record

| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
| --- | -------- | ----------- | -------------------------------- | ----------- | ---------------- |
| R1 | Does installed Mutmut match its RECORD? | Python importlib.metadata hash probe (2026-08-21) | Read-only; no writes | 15/15 files verified sha256-clean, version 3.5.0 | Runner's environment verification is implementable as designed |
| R2 | What does the locked CLI accept? | Installed source inspection `__main__.py:1094-1183` | Read-only | Positional fnmatch mutant-name patterns; `__init__` normalised by removing `.__init__.` | Boundary-safe patterns end in `.x*`; package pattern drops `.__init__` |
| R3 | Which Make bugs must T003 fix? | Integration review agent read-only audit | none | Four critical bypass/parsing defects enumerated above | T003 acceptance includes exact target-contract tests |

## Discovered Requirements

(carry-forward from superseded-plan cycles 0-1, binding on all tasks)

- Repository Semgrep (not Ruff FBT, which is ignored) is authoritative for boolean-parameter policy in scripts; use semantic kinds/callable invariants, never boolean flag parameters (cycle-1 repair history).
- `time.sleep(<typed value>)` trips community rule `arbitrary-sleep`; route constants through a function call if a grace sleep is required.
- Any new/moved suppression needs `owner:`/`reason:` annotation and a no-growth ratchet refresh; identity includes line number.
- Direct-script execution requires the repo-root bootstrap + annotated E402 pattern (established in `mutation_policy.py`, reused in `run_mutation.py`).
- Mutant dictionaries validate per owning stem; alias/shadow resolution must be statement-order aware and scope-safe.
- Duplicate actionable results serialise as unique detail examples while preserving occurrence counts; tool-error reports must never crash publication.
- Test functions/helpers stay CC <= 5; changed test files <= 1,000 lines; security assertions use unique sentinels covering every supplied secret.
- Meta-tests excluded from Mutmut collection must also appear in `test_quality_pipeline_configuration` assertions.

## Design

Unchanged in substance from the superseded plan (fresh-run orchestrator, fail-closed policy lanes, manifest ownership ledger, append-only amendments, dependency-ordered waves). Amendments:

1. T003 delivers only: Makefile execution adapters (`mutate`, `mutate-full-policy`, new `mutate-selected`, repaired `mutate-module`, repaired `mutate-diff`), removal of raw bypasses, `tests/test_run_mutation.py` matrices, make-policy/config-test additions, and commit of the carry-over. Manifest/tier/final targets are re-owned per A2.
2. T005 owns `quality/mutation-source-ledger.json`-style primary artifacts plus `mutation-baseline` and `mutation-manifest-check` targets whose schemas it defines.
3. T006 owns the triage/task manifest schemas plus `mutation-triage-check`, `mutation-task-static`, `mutation-task-tests`, `mutate-key`, `mutate-task-policy`.
4. T022 owns `mutation-final-policy` implementing the two-run protocol.
5. Wave composition, module ownership, and per-wave acceptance signals for T007-T021 are carried verbatim from the superseded plan §Numbered Plan items 7-21 and its Execution Graph; this plan does not duplicate their full bodies but each task entry below names its owned modules and acceptance signal so it is executable standalone.

## Execution Graph

```
T003 -> T004 -> T005 -> T006 -> {T007..T021 dependency-ordered waves}
T007+T008+T009+T010+T011+T012 foundation/API/token/formatting/OAuth/config
T007+T010+T013+T014 persistence/scraper chains
T007+T009+T011+T016 auth consumers
T007+T008+T010+T015 endpoint/upload/streaming
T008+T009+T010+T015 -> T019 MCP;  ...+T013+T015 -> T020 query orchestration
T009+T011 -> T017 auth command runner;  T014 -> T018 export command runner
T012+T016+T017+T018+T019+T020 -> T021 CLI remainder
all clean -> T022 (serial, two full runs)
```

Parallel groups share no owned source/test files within one group; T003-T006 form a serial chain through distinct groups (G1-G4) because they sequentially extend the same Makefile mutation section. Mutation sandboxes never share metadata.

## Numbered Plan

1. [completed] Adopt the canonical runner through Make adapters and land the carry-over
   - Task ID: T003
   - Depends on: none
   - Parallel group: G1
   - Risk: high - replaces all mutation execution entry points; stale/partial evidence could pass gates
   - Owned scope: `Makefile` lines ~281-330 (mutation section + PHONY), `tests/test_make_policy.py`, `tests/test_run_mutation.py` (new), carry-over files `scripts/run_mutation.py`, `scripts/mutation_policy.py` (prefix rename only), `pyproject.toml`, `tests/test_quality_pipeline_configuration.py`, superseded-plan journal close-out
   - Not in scope: CI workflows/docs (T004), manifest/tier targets (A2), deleting existing `mutants` paths, survivor remediation
   - Spike candidate: verify `origin/main` vs `origin/master` remote default (read-only git)
   - Actions: replace `mutate`/`mutate-full-policy` recipes with runner full-scope invocations writing `build/reports/mutation-report.json`; add `mutate-selected` (PATTERNS var, repeated `--pattern` flags); repair `mutate-module` to emit boundary-safe `perplexity_cli.$(MODULE).x*` with argument validation; rewrite `mutate-diff` to capture discovery JSON into mktemp file, propagate exit 2, route exit 1 through `--allow-empty-diff` not-applicable, exit 0 through `--manifest-path`; fix `BASE_SHA ?=` default after verification; add missing-variable guards; extend make-policy tests (target existence, phony, no raw `uv run mutmut run` outside comments, argument expansion, exit propagation) and config-policy assertions; author `tests/test_run_mutation.py` matrices (stale-workspace refusal incl. symlink/broken symlink sentinels unchanged, full/selected/manifest validation, empty-scope tool error, caps 19800/2100, deadline reserves refusal, process-group TERM->grace->KILL with schema-valid failure report, RECORD tamper/missing/extra detection, pattern conversion incl. `__init__`/prefix-spill negatives, exit-code propagation 0/1/2)
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_run_mutation.py tests/test_make_policy.py tests/test_quality_pipeline_configuration.py tests/test_mutation_policy.py tests/test_mutation_evidence.py -q` passes, then `UV_OFFLINE=1 npm_config_offline=true make ci-conventional` exits 0
   - Validation: ruff format/check + pyright on touched scripts; `make -n` expansions for each adapter; grep proves no `uv run mutmut run` recipe remains; carry-over diff reviewed before staging; hook-adjusted staged patch hash recorded pre/post commit
   - Acceptance evidence: command matrix outputs, sentinel-preservation proof, committed SHAs/tree hashes, independent security-focused review verdict
   - Completed evidence: acceptance signal 176 passed; ci-conventional exit 0; semgrep zero findings; pyright strict clean; radon CC<=5; injection probes exit 2 without side effects; suppression ratchet 101 identities; review verdict NEEDS REMEDIATION(7) -> all seven findings fixed and regression-tested
   - Repair attempts: 1
   - Recovery note: carry-over files are preserved verbatim under `/tmp/opencode` recovery convention before any edit; partial Makefile edits revert only within owned section
2. [completed] Make CI mutation evidence mandatory and correct documentation
   - Task ID: T004
   - Depends on: T003
   - Parallel group: G2
   - Risk: high - public CI interface change
   - Owned scope: `.github/workflows/ci.yml`, `.github/workflows/mutation-scheduled.yml`, `QUALITY_GATES.md` (mutation sections), `tests/test_workflow_configuration.py`, `tests/test_quality_gates_documentation.py`, `lefthook.yml` (pre-push mutation stanza only), `.gitignore` comment corrections if needed
   - Not in scope: scheduled dispatch execution (RF001 optional follow-up), runner internals, remediation
   - Spike candidate: none
   - Actions: PR lane calls `make mutate-diff` with job-start epoch exported as outer deadline; scheduled lane calls canonical full target within 360-minute budget passing deadline epoch; both upload the v2 report artifact with `if-no-files-found: error`; summaries expose scope/completeness/no_tests/skipped; pre-push stanza derives a safe local deadline budget; QUALITY_GATES mutation sections rewritten for v2 schema/fresh-run semantics; stale `.mutmut-cache` claims removed
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_workflow_configuration.py tests/test_quality_gates_documentation.py -q && UV_OFFLINE=1 npm_config_offline=true make ci-conventional`
   - Validation: actionlint, workflow YAML parse, SHA-pinned actions preserved, read-only permissions preserved
   - Acceptance evidence: test output, rendered workflow diffs, doc-test pass
   - Completed evidence: 70 workflow/doc tests + full ci-conventional exit 0; both lanes pass MUTATION_DEADLINE_EPOCH (350/42-min budgets); scheduled artifact now if-no-files-found:error; summary exposes scope/completeness/no_tests; QUALITY_GATES stale claims corrected (.mutmut-cache, origin/master, canonical exit semantics); independent review NEEDS REMEDIATION(1) -> fixed plus polish (garbled doubles, 350-min headroom, tab cosmetic)
   - Repair attempts: 1
   - Recovery note: workflows revert cleanly via owned-file checkout; never hand-edit runners to appease CI
3. [pending] Produce the authoritative full-tree baseline and freeze the burn-down ledger
   - Task ID: T005
   - Depends on: T004
   - Parallel group: G3
   - Risk: high - every later proof keys off these artifacts
   - Owned scope: baseline artifacts under `quality/baselines/mutation-*`, primary source-ledger and per-module keyset manifests, `Makefile` targets `mutation-baseline` + `mutation-manifest-check` (added per A2), `scripts/run_mutation.py --candidate-sha` integration checks, new manifest-schema tests
   - Not in scope: triage classification (T006), survivor fixes, CI changes
   - Spike candidate: prove fresh-run determinism of generated keysets on one module before freezing all 105
   - Actions: define ledger/manifest JSON schemas with digests; freeze candidate SHA/tree/lock; run one fresh full mutation from immutable candidate; generate per-module ownership ensuring every generated key owned exactly once with no spill/gap/duplicate; implement `mutation-baseline CANDIDATE_SHA=` and `mutation-manifest-check` with AST-driven enumeration reconciliation
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutation-manifest-check` exits 0 on the frozen candidate; focused schema/ledger tests pass
   - Validation: keyset union equals independently enumerated total; digests stable across two manifest regenerations
   - Acceptance evidence: baseline report path/hashes, ledger coverage matrix, independent review
   - Repair attempts: 0
   - Recovery note: baseline restarts from new candidate on any mismatch; never patch ledgers in place
4. [pending] Classify every actionable candidate and enable per-task verification tiers
   - Task ID: T006
   - Depends on: T005
   - Parallel group: G4
   - Risk: high - misclassification corrupts remediation targeting
   - Owned scope: triage artifacts (`quality/baselines/mutation-triage*` or equivalent), structural-exclusion manifest format if needed, `Makefile` targets `mutation-triage-check`, `mutation-task-static`, `mutation-task-tests`, `mutate-key`, `mutate-task-policy` (re-owned per A2), their schema/contract tests
   - Not in scope: fixing survivors (T007+), wave composition changes
   - Spike candidate: single-key fresh selected run reproduces baseline category for one survived and one historical-timeout mutant
   - Actions: overlay-classify every survived/timeout/suspicious/no-tests record (fixable vs structural-exclusion vs documented-equivalent pending review); enforce sole-owner retention from baseline; timeout candidates demand three consecutive serial post-repair kills later; implement tier targets with killed-only semantics for `mutate-key`, complete-clean-evidence semantics for `mutate-task-policy`
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutation-triage-check TASK=T007 && UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_mutation_triage.py -q` both exit 0; triage covers 100% of actionable baseline rows (verified by the check target itself)
   - Validation: no unresolved row; exclusion candidates each satisfy abstract/Protocol non-executable proof template
   - Acceptance evidence: triage totals reconciled to baseline digests; independent review
   - Repair attempts: 0
   - Recovery note: triage is append-only amendable; amendments chain-hash back to baseline
5. [pending] Close utility and security foundation survivors outside the current ten groups
   - Task ID: T007
   - Depends on: T006
   - Parallel group: W1
   - Risk: high
6. [pending] Close API transport and retry survivors
   - Task ID: T008
   - Depends on: T006
   - Parallel group: W1
   - Risk: high
7. [pending] Close token persistence survivors
   - Task ID: T009
   - Depends on: T006
   - Parallel group: W1
   - Risk: standard
8. [pending] Close formatting package survivors without freezing presentation trivia
   - Task ID: T010
   - Depends on: T006
   - Parallel group: W1
   - Risk: high
9. [pending] Close OAuth and CDP boundary survivors
   - Task ID: T011
   - Depends on: T006
   - Parallel group: W1
   - Risk: high
10. [pending] Close configuration runner survivors
    - Task ID: T012
    - Depends on: T006
    - Parallel group: W1
    - Risk: standard
11. [pending] Close configuration, local-file, and thread-persistence survivors
    - Task ID: T013
    - Depends on: T007, T010
    - Parallel group: W2
    - Risk: standard
12. [pending] Close thread scraper survivors
    - Task ID: T014
    - Depends on: T007, T010
    - Parallel group: W2
    - Risk: high
13. [pending] Close endpoint, upload, streaming, and HTTP-error survivors
    - Task ID: T015
    - Depends on: T007, T008, T010
    - Parallel group: W2
    - Risk: high
14. [pending] Close authentication consumers, models, services, and status survivors
    - Task ID: T016
    - Depends on: T007, T009, T011
    - Parallel group: W2
    - Risk: standard
15. [pending] Close auth command runner survivors
    - Task ID: T017
    - Depends on: T009, T011
    - Parallel group: W2
    - Risk: standard
16. [pending] Close export command runner survivors
    - Task ID: T018
    - Depends on: T014
    - Parallel group: W3
    - Risk: standard
17. [pending] Close MCP boundary survivors
    - Task ID: T019
    - Depends on: T008, T009, T010, T015
    - Parallel group: W3
    - Risk: high
18. [pending] Close query orchestration survivors
    - Task ID: T020
    - Depends on: T008, T009, T010, T013, T015
    - Parallel group: W3
    - Risk: high
19. [pending] Close remaining CLI, output, help, command, and presentation survivors
    - Task ID: T021
    - Depends on: T012, T016, T017, T018, T019, T020
    - Parallel group: W4
    - Risk: standard

Common Remediation Block (inherited verbatim by every task above; full bodies remain in superseded plan §Numbered Plan items 7-21):
    - Owned scope per task: the named modules' sources/tests plus their amendment entries; no cross-module edits
    - Not in scope: tooling changes (route to REPAIR), waiver mechanisms, presentation-wording assertions
    - Actions: per key - reproduce distinction, prefer behavioural test over public boundary, else simplify production/dead code, else approved exclusion; historical timeouts require 3 consecutive serial kills in separate fresh trees; maintain CC<=5/file-cap/ledger discipline
    - Acceptance signal per task: `UV_OFFLINE=1 npm_config_offline=true make mutation-task-static TASK=Txxx && UV_OFFLINE=1 npm_config_offline=true make mutation-task-tests TASK=Txxx && UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=Txxx` all exit 0, followed by `make ci-conventional` at wave boundaries
    - Validation: amendment chain verifies; no baseline key unaccounted
    - Acceptance evidence: per-task clean report digest, amendment hashes, independent review verdict for high-risk tasks
    - Repair attempts: 0
    - Recovery note: failed key reverts to its own amendment; task-level commits isolated

20. [pending] Prove local full-tree closure twice and complete the plan
   - Task ID: T022
   - Depends on: T007-T021 all clean
   - Parallel group: final (serial)
   - Risk: high - completion gate
   - Owned scope: `mutation-final-policy` target implementation, final-run evidence records, Completion Review
   - Not in scope: any code change between runs (invalidates evidence)
   - Spike candidate: none
   - Actions: implement two-run protocol (separate sandbox roots, digest comparison of generated/result/environment, zero actionable/unsafe categories, `ci-conventional` between-freeze guarantee); execute twice from one candidate; fill Completion Review
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutation-final-policy CANDIDATE_SHA=<40-hex>` exits 0 with both schema-valid clean reports archived and digest-identical keysets
   - Validation: runtime within caps; protected-state comparison unchanged
   - Acceptance evidence: both reports, digests, runtimes, final conventional output, independent completion review
   - Repair attempts: 0
   - Recovery note: any post-run-1 change forces new candidate SHA and both runs restart

## Verification Strategy

Cheapest-first per task: ruff format/check -> pyright/radon -> focused pytest -> make target contracts -> full `ci-conventional` at checkpoints/wave boundaries. Fast per-task gates are the tier commands; expensive batch gates are `ci-conventional` (runs ordinary+integration+fuzz+package suites) and the two T022 full runs (hours-scale, serial, offline-cache warm required for pinned uvx tools). Known sensitive checks: suppression ratchets (line-number identities), semgrep boolean/sleep rules, network guard isolation. Parallelism: static and focused suites may run concurrently across tasks; mutation processes never share sandboxes.

## Risks And Recovery

- Stale workspace/false clean (high): runner refuses pre-existing `mutants/`; baselines keyed to immutable SHA; recovery = fresh sandbox same SHA.
- Manifest consumer drift (medium): schemas defined by producing task (T005/T006) with contract tests in the same task; consumers fail closed on schema_version mismatch.
- Environment hangs during long agents (observed): csm-build keeps batches small, journals after every transition, and uses the established `/tmp/opencode` recovery-package discipline before risky edits.
- Suppression/ratchet churn: annotate immediately; refresh baseline as no-growth movement with journal note.
- Equivalent-mutant temptation: prohibited; route to production simplification or documented-equivalent review per triage.
- Rollback: task-scoped commits only; failing wave reverts within owned files; earlier accepted reports remain advisory until T022.

## Critique Resolution

| Finding | Severity | Resolution | Evidence |
| ------- | -------- | ---------- | -------- |
| C1 Risk summary miscounted tasks/high-risk | high | Recounted to 20 tasks, 13 high-risk | How To Execute |
| C2 Dropped dependency edges T009+T011->T017, T014->T018 | high | Restored in Execution Graph verbatim from superseded plan lines 218-222 | Execution Graph |
| C3 T003-T006 all labelled G1 despite serial chain and Makefile overlap | medium | Distinct serial groups G1-G4 assigned | Numbered Plan |
| C4 Merged slot carried 15 task IDs, breaking atomic-entry template and counts | medium | Expanded to explicit per-task entries 5-19 plus Common Remediation Block | Numbered Plan |
| C5 T006 acceptance signal not one runnable command | medium | Named exact two-command signal incl. new tests/test_mutation_triage.py | T006 entry |
| C6 Duplicate owned-scope path in T003 | low | Deduplicated | T003 entry |
| C7 Status ready while still draft/critique pending | low | Critique table filled before SAVED rename | this table |
| C8 "105 modules" uncited | low | Cited superseded-plan ownership ledger sourced from pyproject paths_to_mutate | Acceptance Criteria 4 |

## Progress Journal

| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
| --------- | ----- | ---------- | ----- | --------------- | ---------- |
| 2026-08-21 | 0 | INTAKE | - | Resume brief classified large/prescriptive; depth moderate because superseded plan supplies validated design | DISCOVER |
| 2026-08-21 | 0 | DISCOVER | - | Baseline captured: HEAD 40fb64b; five carry-over paths enumerated; raw Make bypasses confirmed at Makefile:287-319; origin/main default inconsistency found; superseded task inventory extracted | RESEARCH |
| 2026-08-21 | 0 | RESEARCH | - | Prior-cycle evidence reused (R1-R3): RECORD probe, locked CLI grammar, four critical Make defects; no new experiments required | DRAFT |
| 2026-08-21 | 0 | DRAFT | - | Full resume plan drafted with A1-A6 amendments absorbing uncommitted T003 carry-over | CRITIQUE |
| 2026-08-21 | 0 | CRITIQUE | - | Two subagent dispatches returned empty (environment instability, journaled); third fresh agent returned 8 findings (5 blocking), verdict NEEDS REMEDIATION | REMEDIATE |
| 2026-08-21 | 0 | REMEDIATE | - | All 8 findings resolved (C1-C8); no design changes required | VERIFY |
| 2026-08-21 | 0 | VERIFY | - | Primary re-checked counts (20/13), graph edges, group labels, per-task atomicity, acceptance-signal exactness, AC citations; passed | SAVED |
| 2026-08-21 | 1 | NOT_STARTED -> RECOVER | T003 | csm-build invoked on this plan at commit 115fd74; carry-over diff matched enumeration; format marker valid | VALIDATE |
| 2026-08-21 | 1 | VALIDATE -> SELECT | T003 | 139 baseline tests pass; spike confirmed remote HEAD origin/master so BASE_SHA default fix justified | DISPATCH |
| 2026-08-21 | 1 | SELECT -> DISPATCH | T003 | Sole ready task; primary-owned implementation due to shared Makefile/carry-over integration and repeated subagent instability (journaled) | INTEGRATE |
| 2026-08-21 | 1 | DISPATCH -> INTEGRATE | T003 | Runner+Makefile+tests written by primary; early test run exposed empty-diff selection defect fixed before first gate | VERIFY |
| 2026-08-21 | 1 | INTEGRATE -> VERIFY | T003 | Acceptance signal 169 then 176 passed; first ci-conventional caught formatter-duplicated return (semgrep) - removed | REVIEW |
| 2026-08-21 | 1 | VERIFY -> REVIEW | T003 | Second full ci-conventional exit 0; independent reviewer dispatched | REPAIR |
| 2026-08-21 | 1 | REVIEW -> REPAIR | T003 | Verdict NEEDS REMEDIATION(7): F1-F7 all genuine defects/gaps | VERIFY |
| 2026-08-21 | 1 | REPAIR -> VERIFY | T003 | All findings fixed: manifest empty-lane routed, Make guards enforced (probe exits 2, no side effect), UV_OFFLINE forced, signal forwarders installed, RECORD matrix tested incl self-entry listing bug fix, strict package prefix, broken-symlink sentinel | CHECKPOINT |
| 2026-08-21 | 1 | VERIFY -> CHECKPOINT | T003 | Third ci-conventional exit 0 after no-growth suppression refresh; commit follows | SELECT T004 |
| 2026-08-21 | 2 | CHECKPOINT -> SELECT | T004 | T003 committed 6bf4593; T004 sole ready | DISPATCH |
| 2026-08-21 | 2 | SELECT -> DISPATCH | T004 | Primary-owned implementation (workflow/docs text edits with policy-test oracle); deadline passthrough added to Make, epochs wired in both lanes, artifacts mandatory, docs corrected | INTEGRATE |
| 2026-08-21 | 2 | INTEGRATE -> VERIFY | T004 | 87 workflow/doc/policy tests pass; first ci-conventional exit 0 | REVIEW |
| 2026-08-21 | 2 | VERIFY -> REVIEW | T004 | Independent review NEEDS REMEDIATION(1): doc contradicts error-artifact; plus garbled text, headroom, tab polish | REPAIR |
| 2026-08-21 | 2 | REPAIR -> CHECKPOINT | T004 | All four findings fixed; 70 suite tests and final ci-conventional exit 0; commit follows | SELECT T005 |

## Completion Review

Filled by csm-build when all criteria are verified.
