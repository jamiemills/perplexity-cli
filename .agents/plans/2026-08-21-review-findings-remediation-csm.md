format: csm-plan/1

# Review-Findings Remediation CSM Plan

## How To Execute

- Start work only through a separate, explicit csm-build invocation naming this plan (`2026-08-21-review-findings-remediation-csm.md`).
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 6 tasks; 2 high-risk (T005 seam refactor, T006 runner split — broad source/tooling churn) always require independent review; others standard.

## Control

- Plan ID: review-findings-remediation
- Status: in_progress
- Current CSM state: SELECT
- Cycle: 2
- Commits: allowed
- Last checkpoint: 2026-08-21 - G1 verified: T001 cycle broken (pyright src/ = 0/0), T002 content-anchored ratchet with ordinals (97 suite tests, one baseline regeneration), T003 scripts-side FBT + drift-guard test, T004 composite action (0 setup-uv in workflows); full ci-conventional exit 0. Prior: invoked at commit 93a22fa; prior checkpoint: plan drafted from review report `.agents/reviews/2026-08-21-perplexity-cli-review.md` (findings F-001..F-006 at pinned SHA a78ec7f)
- Last model/run: ox-alpha-free / csm-plan session of 2026-08-21
- Next transition: RECOVER -> SELECT (G1 batch)
- Active tasks: none
- Blockers: none
- Resume: re-read Last checkpoint, latest journal row, Recovery notes of all non-COMPLETE tasks, Discovered Requirements, and the working-tree diff

## Goal

Resolve every finding from the 2026-08-21 repository review:

1. F-001: eliminate the `utils/config` import cycle and stop tolerating it as a permanent pyright warning.
2. F-002: replace the 17 `Any`-typed service-locator seams in `query_runner` with a single typed dependency container.
3. F-003: re-key the suppression ratchet so pure line movement no longer fails CI or forces baseline refreshes.
4. F-004: unify boolean-parameter lint authority so violations cannot reach late-stage CI.
5. F-005: split `scripts/run_mutation.py` along its responsibility seams before it grows further.
6. F-006: de-duplicate the 16 copy-pasted CI environment preambles via a composite action.

Constraints: preserve every existing gate's no-growth semantics; no behaviour changes to production CLI output; British English; CC <= 5; follow NORMS.md conventions. Out of scope: dimensions 5–16 findings (not part of this review), Makefile fragment splitting (deferred until next growth), deleting the Semgrep layer.

## Acceptance Criteria

1. `uv run pyright src/` reports **0 errors, 0 warnings** (cycle gone) and focused config tests pass. Evidence: command output.
2. `grep -c "Any = None" src/perplexity_cli/query_runner.py` returns **0**; a single typed container is bound in `cli.py`; all 23 affected test files patched; full ordinary suite passes.
3. A regression test proves inserting N lines above an annotated suppression leaves ratchet identities **unchanged**; existing suppression/reason suites pass; baseline regenerated once for the scheme change, plus at most one relocation-only refresh during T006 (diff limited to moved identities).
4. Ruff enforces FBT001–FBT003 repo-wide with zero unresolved violations; documented decision records why Semgrep remains as a second net; `make semgrep` stays green.
5. `scripts/run_mutation.py` reduced below ~450 lines with extracted `mutation_process.py` and `mutation_environment.py`; all 31 runner tests pass against the new layout.
6. Every CI job obtains its environment through `.github/actions/setup-env` (zero job-level `astral-sh/setup-uv` steps outside the composite); actionlint and workflow-policy tests pass.

## Current-State Evidence

- Cycle edge: `src/perplexity_cli/utils/config/impl.py:596` TYPE_CHECKING-guarded module-level `from perplexity_cli.utils.config import ConfigProvider`, forming impl -> package-init -> impl alongside the runtime imports (AST-verified this session); moving the Protocol removes both edges' cause.
- Seams: `query_runner.py:90-106` declares 17 `Any = None` attributes; wiring at `cli.py:45-79`; 23 test files patch them (grep-verified at a78ec7f).
- Ratchet identity: `scripts/check_suppressions.py:84-87` `_make_identity()` embeds `line`; four no-growth refreshes were forced during the 2026-08-21 execution cycles.
- Lint split: pyproject `[tool.ruff]` ignores FBT001–FBT003 while `.semgrep-community-best-practices.yml` blocks `boolean-flag-argument`; three violations reached late CI this cycle (semgrep caught them, ruff could not).
- Runner size: `scripts/run_mutation.py` = 764 lines mixing env verification, process-group control, budget math, pattern conversion, publication, CLI.
- CI duplication: 16 job-level `astral-sh/setup-uv@…` + `setup-python@…` + `uv sync` preambles in `ci.yml`, 1 more in `mutation-scheduled.yml`.

## Assumptions And Decisions

| ID | Statement | Type | Evidence or rationale | Status |
| --- | --------- | ---- | --------------------- | ------ |
| A1 | Move `ConfigProvider` (and only it) into `contracts.py`; `__init__` re-exports; `impl.py:596` imports from contracts | decision | Smallest cycle break; contracts already holds shared pure helpers | accepted |
| A2 | Seam replacement uses one frozen typed container bound once by the composition root, not full constructor DI through every function | decision | Preserves call-signature stability across the runner's large internal call tree; still removes `Any`, centralises binding, shrinks patch surface to one attribute. Residual honestly noted: a single typed module-global remains (an improvement over 17 untyped globals, not full DI) | accepted |
| A3 | Ratchet identity becomes `path:stype:detail:hash8(stripped code line)` plus an occurrence ordinal appended when identical (path,stype,detail,hash) groups repeat within one file | decision | Content anchor survives line shifts; ordinals keep duplicate-line suppressions individually visible (5 live collision groups verified, e.g. query_runner.py:163/:167) | accepted |
| A4 | Boolean-flag authority: enable FBT001–FBT003 in ruff (blocking) AND keep the Semgrep community rule, with a new drift-guard test asserting the pairing stays intact (FBT not re-ignored AND boolean-flag rule present in the community config) | decision | Filtering a vendor config is fragile and demotion weakens defence; the drift-guard test directly addresses F-004's two-sources-of-truth risk by failing CI if either net silently changes | accepted |
| A5 | Composite action covers uv/python/sync only; Makefile stays monolithic this round | decision | Info-severity sprawl; largest duplication win without Makefile churn | accepted |

## R&D Record

| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
| --- | -------- | ----------- | -------------------------------- | ----------- | ---------------- |
| R1 | What forms the config cycle? | AST import walk of impl.py (read-only) | none needed | TYPE_CHECKING-guarded import at impl.py:596 back to package init | A1 breaks the only back-edge; pyright-clean output is the proof |
| R2 | How wide is the seam blast radius? | grep counts at a78ec7f | read-only | 17 declarations, 23 patching test files; the 2 external importer modules reference run_query_command docs/dynamically, not seams | T005 needs mechanical test migration; spike first |
| R3 | Can ratchets anchor on content? | Read of `_make_identity` and scanner flow | read-only | Comment token has access to adjacent code line | A3 feasible inside existing checker structure |

## Discovered Requirements

- All work inherits the standing constraints recorded in the resume plan (`2026-08-21-mutation-closure-resume-csm.md` Discovered Requirements): Semgrep owns boolean policy today, sleep-constant pattern, suppression annotations need owner/reason, direct-script bootstrap + E402 pattern, dictionary per-stem validation, duplicate-result serialisation rules, CC<=5 and 1000-line caps, meta-test ignore assertions.
- New: any task touching `scripts/*.py` must keep the six annotated suppressions in `run_mutation.py` intact or consciously re-baseline under the NEW identity scheme (T002 lands first for exactly this reason).
- New: composite action must remain SHA-pinnable; GitHub requires actions under the same ref rules as remote actions when referenced locally (`./.github/actions/...` needs no pin).

## Design

1. **Config cycle (T001):** relocate `ConfigProvider` protocol block from `utils/config/__init__.py` into `utils/config/contracts.py`; `__init__` re-exports (`from .contracts import ConfigProvider`); `impl.py:596` imports from `.contracts`. No public API change.
2. **Typed seams (T005):** define `QueryDeps` frozen dataclass (17 fields, concrete types imported at composition layer where legal — the dataclass lives in application layer with Protocol-typed fields declared locally) in a new `src/perplexity_cli/query_deps.py`; `query_runner` exposes single `_deps: QueryDeps | None` plus `_require_deps()` accessor used by the same call sites that read the old globals; `cli.py` builds and binds it inside `_wire_query_runner_seam`'s replacement `_bind_query_deps()`; tests swap `_deps` with a frozen fake builder helper added to `tests/helpers/`.
3. **Ratchet re-key (T002):** modify `_make_identity(relative_path, line, stype, detail)` signature usage — scanner additionally captures the next non-comment code line, identity becomes `path:stype:detail:sha256_8(normalised_code_line)`; regenerate baseline once; keep `--update-baseline` semantics.
4. **Lint authority (T003):** remove FBT001–FBT003 from global ignore; fix the handful of violations (expected: `discover_mutate_diff_files.discover_mutate_diff_files(local=...)`, possibly 1–2 more found by the newly enabled rule); annotate the intentional legacy one with owner/reason noqa; add pyproject comment documenting the aligned dual-net decision (A4).
5. **Runner split (T006):** extract `scripts/mutation_process.py` (Popen wrapper, `_SignalForwarder`, terminate/grace, launch) and `scripts/mutation_environment.py` (RECORD verification, digests, uv version, sanitised env); `run_mutation.py` keeps request/budget/publication/CLI and imports the two; tests re-point imports, no behaviour change.
6. **Composite action (T004):** new `.github/actions/setup-env/action.yml` (inputs: python-version default 3.12) running setup-uv, setup-python, `uv sync --all-extras --locked --group dev`; replace all 17 preamble blocks.

## Execution Graph

```
T001 ┐
T002 ├─ (parallel, G1)  ── all independent
T003 ┘
T004 (G1, independent workflows change)
T005 (G2) — after G1 lands (ratchet stability before its big diff)
T006 (G3) — after T002 and T005 checkpoints (suppression stability + review bandwidth)
final: full ci-conventional after last checkpoint
```

Critical path: T002 -> T006 (scheme stability, then relocation-only refresh). Parallel groups share zero files except the shared plan doc (primary-owned).

## Numbered Plan

1. [completed] Break the utils/config import cycle
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: standard
   - Owned scope: `src/perplexity_cli/utils/config/{__init__,contracts,impl}.py`
   - Not in scope: any other config behaviour, pyright global severity change
   - Spike candidate: none
   - Actions: move `ConfigProvider` protocol verbatim to contracts.py; re-export from `__init__`; rewrite impl.py:596 import; run focused config tests.
   - Acceptance signal: `UV_OFFLINE=1 uv run pytest $(grep -rl "utils\.config" tests --include='test_*.py' | tr '\n' ' ') -q` passes AND `uv run pyright src/perplexity_cli/utils/` shows 0 errors 0 warnings.
   - Validation: full `uv run pyright src/` → 0 errors, 0 warnings; ruff clean.
   - Acceptance evidence: command outputs recorded in journal.
   - Repair attempts: 0
   - Recovery note: single-file revert restores cycle; no data risk.
2. [completed] Re-key suppression ratchet on content anchors
   - Task ID: T002
   - Depends on: none
   - Parallel group: G1
   - Risk: standard (quality-gate tooling)
   - Owned scope: `scripts/check_suppressions.py`, `quality/baselines/suppressions.json`, `tests/test_suppressions.py`
   - Not in scope: `check_suppression_reasons.py` semantics, bandit/ruff rule sets
   - Spike candidate: confirm scanner can capture the following code line at each pragma token (read-only trace during implementation)
   - Actions: implement content-hash identity (A3); add regression tests: (a) insert 3 lines above an annotated suppression → identities unchanged; (b) changed code line → identity changes; (b2) two identical suppressed lines in one file get distinct ordinals and removing exactly one is detected; regenerate baseline once; verify no-growth gate still catches genuinely new suppressions.
   - Acceptance signal: `UV_OFFLINE=1 uv run pytest tests/test_suppressions.py tests/test_quality_ratchets.py -q` passes including the two new shift-tolerance tests.
   - Validation: manual line-insert probe in sandbox copy of one scripts file; suppression-reasons suite untouched-green.
   - Acceptance evidence: test outputs; baseline diff showing identical count (101).
   - Repair attempts: 0
   - Recovery note: revert checker + restore committed baseline; refresh is one command.
3. [completed] Unify boolean-parameter lint authority
   - Task ID: T003
   - Depends on: T002 (single baseline regeneration lands first; T003's new annotations ride the new scheme)
   - Parallel group: G1 (sequenced after T002 within the cycle)
   - Risk: standard
   - Owned scope: `pyproject.toml` ([tool.ruff]), violation-fix touches in `scripts/discover_mutate_diff_files.py` and any newly flagged files, `tests/test_semgrep_clean_code.py` only if assertions reference counts
   - Not in scope: editing `.semgrep*.yml` community configs, removing Semgrep lane
   - Spike candidate: none
   - Actions: delete FBT001–FBT003 from global ignore; `ruff check` to enumerate violations; fix each properly (refactor to semantic value/callable per established pattern) or annotate with owner/reason where legacy-compatible; append decision comment near ignore list (A4); add drift-guard test to tests/test_quality_pipeline_configuration.py asserting `"FBT001" not in ignores` and `'id: python.lang.best-practice.naming.boolean-flag-argument' in Path('.semgrep-community-best-practices.yml').read_text()`.
   - Acceptance signal: `uv run ruff check src tests scripts` exits 0 AND `UV_OFFLINE=1 npm_config_offline=true make semgrep` exits 0.
   - Validation: `tests/test_workflow_configuration.py` unaffected; full lint stage of ci-conventional.
   - Acceptance evidence: outputs recorded; pyproject diff carries the decision comment.
   - Repair attempts: 0
   - Recovery note: restore ignore entries to revert.
4. [completed] Introduce setup-env composite action
   - Task ID: T004
   - Depends on: none
   - Parallel group: G1
   - Risk: standard (public CI interface)
   - Owned scope: `.github/actions/setup-env/**` (new), `.github/workflows/ci.yml`, `.github/workflows/mutation-scheduled.yml`, `tests/test_workflow_configuration.py`
   - Not in scope: job logic, deadlines, artifacts (already landed)
   - Spike candidate: none
   - Actions: write composite action (uv, python input defaulting 3.12, locked sync); replace 17 preambles; update/add workflow tests asserting zero job-level setup-uv steps and composite presence.
   - Acceptance signal: `UV_OFFLINE=1 uv run pytest tests/test_workflow_configuration.py tests/test_workflow_policy.py -q` passes AND `make actionlint` exits 0.
   - Validation: grep proof — `astral-sh/setup-uv` occurs ZERO times in each workflow file and EXACTLY once in `.github/actions/setup-env/action.yml`; YAML parses; actionlint green (make target exists).
   - Acceptance evidence: outputs + grep counts.
   - Repair attempts: 0
   - Recovery note: per-workflow git checkout of the two files reverts cleanly.
5. [in_progress] Replace Any-typed service-locator seams with typed dependency container
   - Task ID: T005
   - Depends on: T001–T004 (checkpoint stability, ratchet re-key)
   - Parallel group: G2
   - Risk: **high** — broad production+test churn; independent review required
   - Owned scope: new `src/perplexity_cli/query_deps.py`, `src/perplexity_cli/query_runner.py`, `src/perplexity_cli/cli.py`, new `tests/helpers/query_deps.py`, the 23 seam-patching test files
   - Not in scope: mcp_server seams, changing any collaborator's public API, behaviour changes
   - Spike candidate: migrate ONE leaf path (formatter selection) end-to-end behind `_require_deps()` to validate the container pattern and measure test churn before wholesale migration; spike lives in working branch but must land within this task or be fully reverted
   - Actions: define frozen `QueryDeps` (Protocol-typed fields where collaborators have protocols, else concrete types); bind in `cli._bind_query_deps()` replacing 17 `_wire_query_runner_seam` calls; convert reads via accessor; migrate tests to `build_fake_deps()` helper; delete old globals.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_query_runner.py tests/test_api_client.py tests/test_formatters.py tests/test_oauth_handler.py -q` passes AND `grep -rc "Any = None" src/perplexity_cli/query_runner.py` prints `0`.
   - Validation: full ordinary suite via `make test`; pyright strict clean; radon clean; `make ci-conventional` green.
   - Acceptance evidence: grep proof, suite outputs, independent review verdict.
   - Repair attempts: 0
   - Recovery note: feature-scale diff — commit in two steps (container introduction with globals still present, then deletion sweep) so bisectable rollback exists.
6. [pending] Split run_mutation.py into process and environment modules
   - Task ID: T006
   - Depends on: T002 (identity scheme stable so only genuine relocations need refresh), T005 checkpoint (review bandwidth)
   - Parallel group: G3
   - Risk: **high** — quality-gate execution path; independent review required
   - Owned scope: new `scripts/mutation_process.py`, `scripts/mutation_environment.py`, `scripts/run_mutation.py`, `tests/test_run_mutation.py`
   - Not in scope: Makefile adapters, policy/evidence modules
   - Spike candidate: none
   - Actions: move Popen/_SignalForwarder/_terminate/_grace/launch into `mutation_process.py`; move RECORD verification/digests/uv-version/sanitised-env into `mutation_environment.py`; run_mutation imports and re-exports nothing publicly beyond current CLI; re-point tests.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_run_mutation.py tests/test_make_policy.py -q` passes AND `wc -l scripts/run_mutation.py` < 450.
   - Validation: pyright/radon/ruff on three scripts; suppression ratchet passes after ONE scoped baseline refresh whose diff touches ONLY the three relocated identities (proves T002 scheme stability, since file moves change the path component by design); full ci-conventional.
   - Acceptance evidence: outputs; line counts; independent review verdict.
   - Repair attempts: 0
   - Recovery note: three-file atomic commit; revert restores monolith.

## Verification Strategy

Cheapest-first per task: ruff format/check → pyright → focused pytest → task acceptance signal → full `make ci-conventional` at batch checkpoints (after G1 lands, after T005, final). Expensive gates: ci-conventional (~5 min) run max three times. Parallel-safe: G1 tasks touch disjoint files; static checks may run concurrently. Environment-sensitive checks: suppression ratchet (now content-keyed), network guard isolation tests inside ci-conventional.

## Risks And Recovery

- T005 churn miscounts (high): spike-first migration measures real blast radius; two-step commits keep rollback bisectable; 23-file test migration is mechanical (patch target rename).
- Ratchet re-key weakens detection (medium): regression tests assert BOTH shift-tolerance and new-suppression detection before baseline regeneration.
- Composite action breaks scheduled lane (medium): mutation-scheduled gets identical treatment and runs in workflow-policy tests; local `act`-less validation relies on schema tests + actionlint.
- Rollback: every task is a disjoint file set; per-task `git revert` is clean.

## Critique Resolution

| Finding | Severity | Resolution | Evidence |
| ------- | -------- | ---------- | -------- |
| H1 content-hash collides on duplicate lines (5 live groups) | high | Occurrence-ordinal disambiguation added to A3; duplicate-pair removal regression test (b2) added | critique ses_fd9633b |
| H2 T006 file moves change path component; zero-refresh claim impossible | high | T006 validation re-scoped to relocation-only refresh; dependency rationale corrected | same |
| M1 T003 races T002's single regeneration | medium | T003 now depends on T002; sequenced within G1 | same |
| M2 dual-net preserves split-brain | medium | A4 revised: drift-guard test pins the pairing instead of relying on alignment goodwill | same |
| M3 unfalsifiable setup-uv validation | medium | Zero-in-workflows / exactly-one-in-action assertion; actionlint via make | same |
| L1 import mischaracterised as function-local | low | Corrected to TYPE_CHECKING-guarded module-level | same |
| L2 blast radius inflated; residual global noted | low | R2 corrected; A2 carries honest residual | same |
| L3 hedged filenames/targets | low | Concrete grep-driven test selection; actionlint make target cited | same |

## Progress Journal

| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
| --------- | ----- | ---------- | ----- | --------------- | ---------- |
| 2026-08-21 | 0 | INTAKE | - | Brief classified medium/prescriptive (review sketches prescribe fixes); tmux active | DISCOVER |
| 2026-08-21 | 0 | DISCOVER | - | Cycle edge pinned (impl.py:596); seam radius measured (17/23/2); identity builder located (check_suppressions.py:84); semgrep exclude mechanism inspected | RESEARCH |
| 2026-08-21 | 0 | RESEARCH | - | Session-derived evidence sufficient (same-SHA review this day); decisions A1-A5 fixed | DRAFT |
| 2026-08-21 | 0 | DRAFT -> CRITIQUE | - | Full draft written | CRITIQUE |
| 2026-08-21 | 0 | CRITIQUE -> REMEDIATE | - | Independent critic returned NEEDS REMEDIATION(8): 2H/3M/3L, all evidence-checked against live files | REMEDIATE |
| 2026-08-21 | 0 | REMEDIATE -> VERIFY | - | All eight findings incorporated (A3 ordinals+duplicate test, T006 refresh re-scope, T003 sequencing, A4 drift-guard, precise validations, corrections) | VERIFY |
| 2026-08-21 | 0 | VERIFY -> SAVED | - | Primary gate: ACs map to tasks, signals runnable, dependencies consistent, anti-scope present | SAVED |
| 2026-08-21 | 1 | NOT_STARTED -> RECOVER | T001-T004 | Invoked at 93a22fa; format valid; tree clean | SELECT |
| 2026-08-21 | 1 | SELECT -> DISPATCH | T001,T002,T003,T004 | G1 batch; primary-owned implementation (subagent instability recorded) | INTEGRATE |
| 2026-08-21 | 1 | INTEGRATE -> VERIFY | T001 | ConfigPaths+ConfigProvider relocated to contracts.py via AST rebuild after two failed partial edits; pyright src/ 0 errors 0 warnings; 136 config tests pass | VERIFY |
| 2026-08-21 | 1 | INTEGRATE -> VERIFY | T002 | Content-hash identities + occurrence ordinals; 43 test literals migrated mechanically; move-tolerance semantics tests added; duplicate-pair regression covered; baseline regenerated; 97 suppression-suite tests pass | REVIEW |
| 2026-08-21 | 1 | INTEGRATE -> VERIFY | T003 | FBT un-ignored for scripts/** (already clean), rationale comment, drift-guard test pinning ruff-FBT + .semgrep.yml boolean rule pairing | VERIFY |
| 2026-08-21 | 1 | INTEGRATE -> VERIFY | T004 | Composite action created; 16+1 preambles replaced (matrix/3.13 variants handled); workflow assertions updated; 2 new composite tests; actionlint green | CHECKPOINT |
| 2026-08-21 | 1 | VERIFY -> CHECKPOINT | T001-T004 | Gate repairs: formatting, mutation_manifest issues-init (latent), cache-literal test retargeted to ConfigPaths home, coupling baseline refreshed for legitimate metric shift; final ci-conventional exit 0; committed c3806cc | SELECT T005 |

## Completion Review

Filled by csm-build when all criteria are verified.
