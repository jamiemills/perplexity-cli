format: csm-plan/1

# Mutation Closure Execution CSM Plan

## How To Execute

- Start work only through a separate, explicit csm-build invocation naming this plan.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 5 tasks; 2 high-risk (T006 triage, T022 final proof) require independent review.

## Control

- Plan ID: mutation-closure-execution
- Status: in_progress
- Current CSM state: RECOVER
- Cycle: 0
- Commits: allowed
- Last checkpoint: 2026-08-22 - plan created for the 5 remaining mutation-closure items
- Last model/run: ox-alpha-free / csm-plan session of 2026-08-22
- Next transition: RECOVER -> SELECT -> DISPATCH T001 baseline run
- Active tasks: none
- Blockers: none
- Resume: re-read Last checkpoint, latest journal row, Recovery notes, Discovered Requirements, working-tree diff

## Goal

Complete the repository's full-tree mutation debt closure by executing the 5 remaining phases:

1. Run the authoritative full-tree baseline mutation.
2. Classify every actionable finding (triage).
3. Remediate all survivors across dependency-ordered waves.
4. Prove closure with two independent clean full-tree runs.
5. Optionally corroborate via remote workflow dispatch.

## Acceptance Criteria

1. Baseline report exists at `build/reports/mutation-baseline/<sha>/mutation-report.json` with schema-valid v2 output and per-module keyset manifest.
2. Every actionable baseline record classified with disposition; `make mutation-triage-check` exits 0.
3. Zero survived/timeout/suspicious/executable no-tests mutants across all 105 modules.
4. Two independent clean full-tree runs with identical generated/result/environment digests; `make mutation-final-policy CANDIDATE_SHA=<sha>` exits 0.
5. `make ci-conventional` passes at every wave boundary.

## Current-State Evidence

- All tooling landed: canonical runner (`scripts/run_mutation.py` 535 lines), policy (`scripts/mutation_policy.py`), evidence (`scripts/mutation_evidence.py`), manifests (`scripts/mutation_manifest.py`), process (`scripts/mutation_process.py`), environment (`scripts/mutation_environment.py`).
- Make targets: `mutation-baseline`, `mutation-manifest-check`, `mutate-full-policy`, `mutate-selected`, `mutate-module`, `mutate-diff`.
- CI lanes wired with deadline epochs and mandatory artifacts.
- 79 focused runner tests + 94 mutation policy/evidence tests + 8 manifest tests all pass.
- Full `ci-conventional` exit 0 at commit `74b3c97` (3,195 tests, 95.2% coverage).
- Last known mutation counts (from planning-time data): ~9,620 mutants, ~6,057 killed, ~3,452 survived, ~27 timed out, ~84 skipped.
- No `mutants/` directory exists (clean workspace confirmed).

## Assumptions And Decisions

| ID | Statement | Type | Evidence or rationale | Status |
| --- | --------- | ---- | --------------------- | ------ |
| A1 | The baseline run is the critical path; everything downstream keys off its artifacts | decision | T006-T022 all require baseline keysets/manifests | accepted |
| A2 | Remediation waves proceed in dependency order per the superseded plan's Execution Graph, with parallel groups sharing no owned files | decision | Superseded plan §Execution Graph lines 218-229 | accepted |
| A3 | Historical timeout mutants require 3 consecutive serial post-repair kills in separate fresh trees | decision | Superseded plan Tier 3 contract | accepted |
| A4 | The two final runs (T022) are serial, from one immutable candidate SHA, with no code changes between run 1 and run 2 | decision | Superseded plan T022 recovery note | accepted |

## Discovered Requirements

- All standing constraints from the resume plan apply: CC<=5, file caps, ledger discipline, sanitised sandboxes, no live API access.
- `mutation-manifest-check` must pass before any remediation wave starts.
- `mutation-task-static` + `mutation-task-tests` + `mutate-task-policy` per task before wave closure.
- `make ci-conventional` at every wave boundary.
- Suppression annotations need owner:/reason:; ratchet is content-anchored.

## Design

Sequential pipeline: baseline → triage → waves → final proof. The triage step produces the per-task manifests that the tier targets consume. Waves are grouped by the dependency graph from the superseded plan.

## Execution Graph

```
T001 baseline -> T002 triage -> {T003a: waves 1-4} -> {T003b: waves 5-8} -> {T003c: waves 9-11} -> T004 final proof
                                                                                                    -> T005 optional remote (parallel with T004)
```

## Numbered Plan

1. [pending] Run the authoritative full-tree baseline mutation
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: high - all downstream proofs key off this artifact
   - Owned scope: `build/reports/mutation-baseline/<sha>/` artifacts, `quality/baselines/mutation-baseline/` manifests
   - Not in scope: triage, remediation, CI changes
   - Spike candidate: none
   - Actions: run `make mutation-baseline CANDIDATE_SHA=$(git rev-parse HEAD)`; verify report is schema-valid; verify `make mutation-manifest-check BASELINE_SHA=$(git rev-parse HEAD)` exits 0
   - Acceptance signal: `make mutation-manifest-check BASELINE_SHA=$(git rev-parse HEAD)` exits 0
   - Validation: report has non-zero total_mutants; keysets manifest covers all modules; digests stable
   - Acceptance evidence: baseline report path/hashes, manifest-check output, runtime
   - Repair attempts: 0
   - Recovery note: baseline restarts from new candidate on any mismatch; never patch ledgers in place
2. [pending] Classify every actionable finding and produce task manifests
   - Task ID: T002
   - Depends on: T001
   - Parallel group: G1
   - Risk: high - misclassification corrupts remediation targeting
   - Owned scope: triage artifacts, per-task manifests, structural-exclusion manifest if needed
   - Not in scope: fixing survivors
   - Spike candidate: verify one survived and one timeout mutant reproduce their baseline category in a fresh selected run
   - Actions: overlay-classify every actionable baseline record; produce per-task manifests for T007-T021 waves; implement `mutation-triage-check`; validate structural exclusions
   - Acceptance signal: `make mutation-triage-check` exits 0; triage covers 100% of actionable rows
   - Validation: no unresolved row; exclusion candidates satisfy proof template
   - Acceptance evidence: triage totals reconciled to baseline digests
   - Repair attempts: 0
   - Recovery note: triage is append-only amendable; amendments chain-hash back to baseline
3. [pending] Execute remediation waves T007-T021
   - Task ID: T003
   - Depends on: T002
   - Parallel group: G1
   - Risk: high - production/test churn at scale
   - Owned scope: all 105 production modules' survivor fixes, per-wave commits
   - Not in scope: tooling changes, waiver mechanisms
   - Spike candidate: none
   - Actions: for each wave, per key - reproduce distinction, write behavioural test over public boundary, or simplify production/dead code, or approved exclusion; historical timeouts require 3 consecutive serial kills
   - Acceptance signal: per-wave `mutation-task-static && mutation-task-tests && mutate-task-policy` all exit 0, then `make ci-conventional`
   - Validation: amendment chain verifies; no baseline key unaccounted
   - Acceptance evidence: per-task clean report digest, amendment hashes
   - Repair attempts: 0
   - Recovery note: failed key reverts to its own amendment; task-level commits isolated
4. [pending] Prove local full-tree closure twice
   - Task ID: T004
   - Depends on: T003
   - Parallel group: final (serial)
   - Risk: high - completion gate
   - Owned scope: `mutation-final-policy` target, final-run evidence, Completion Review
   - Not in scope: any code change between runs
   - Spike candidate: none
   - Actions: implement two-run protocol; execute twice from one candidate SHA; verify digest identity
   - Acceptance signal: `make mutation-final-policy CANDIDATE_SHA=<40-hex>` exits 0 with both reports clean and digest-identical
   - Validation: runtime within caps; protected state unchanged
   - Acceptance evidence: both reports, digests, runtimes, final conventional output
   - Repair attempts: 0
   - Recovery note: any change after run 1 forces new candidate and restart
5. [pending] Optional remote workflow dispatch for corroboration
   - Task ID: T005
   - Depends on: T004
   - Parallel group: parallel with T004 completion
   - Risk: standard
   - Owned scope: GitHub Actions dispatch trigger, remote run monitoring
   - Not in scope: local evidence (already complete)
   - Spike candidate: none
   - Actions: push final candidate; dispatch scheduled mutation workflow; watch to completion; validate artifacts
   - Acceptance signal: remote workflow run exits 0 with report artifact uploaded
   - Validation: remote report digests match local
   - Acceptance evidence: remote run URL, artifact hashes
   - Repair attempts: 0
   - Recovery note: remote failure does not revoke local completion; opens repair work against the recorded candidate

## Verification Strategy

Baseline and triage are verified by their own Make targets. Waves are verified per-task by tier commands and at boundaries by `ci-conventional`. Final proof is verified by the two-run protocol. All checks are deterministic and offline.

## Risks And Recovery

- Baseline runtime exceeds expectations (high): runner has 19,800s cap; if exceeded, split into selected-scope batches per module.
- Survivor count higher than expected (medium): triage may reveal equivalent mutants requiring production simplification; budget extra time.
- Test flakiness under mutation (medium): each mutant runs the full ordinary suite; flaky tests produce false survivors; isolate and fix before proceeding.
- Rollback: task-scoped commits; failing wave reverts within owned files.

## Critique Resolution

| Finding | Severity | Resolution | Evidence |
| ------- | -------- | ---------- | -------- |
| (primary-led; plan is a direct execution of the already-validated superseded plan's remaining tasks) | - | - | - |

## Progress Journal

| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
| --------- | ----- | ---------- | ----- | --------------- | ---------- |
| 2026-08-22 | 0 | INTAKE | - | 5 remaining items identified; plan drafted from superseded plan's validated design | DRAFT |
| 2026-08-22 | 0 | DRAFT -> SAVED | - | Primary-led critique (plan executes already-validated superseded plan tasks); verified | SAVED |

## Completion Review

Filled by csm-build when all criteria are verified.
