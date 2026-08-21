# Full-Tree Mutation Debt Closure CSM Plan

## How To Execute
- Start work only through a separate, explicit `csm-build` invocation naming this plan; the planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 22 tasks: 15 high-risk and 7 standard-risk. T002, T003, T005-T009, T011, T013-T016, T019, T020, and T022 always require independent review. This list contains every high-risk task.

## Control
- Plan ID: full-tree-mutation-debt-closure
- Status: paused
- Superseded for execution by `.agents/plans/2026-08-21-mutation-closure-resume-csm.md` (T001/T002 completed here; T003 carry-over absorbed there). Retained as the detailed source for wave composition T007-T021, the tier table, and cycle 0-1 evidence.
- Current CSM state: DISPATCH
- Cycle: 1
- Commits: allowed
- Last checkpoint: 2026-08-15 - SELECT confirmed T003 is the sole dependency-ready task and added review-discovered meta-test exclusions to its ownership.
- Next transition: DISPATCH R&D probes -> DISPATCH T003 implementation with verified Mutmut/Make contracts
- Active tasks: T003
- Blockers: none

## Goal
Close the repository's mutation-testing debt with authoritative, reproducible evidence rather than a score threshold. The work will:

1. Preserve, review, organise, and checkpoint the current 10-file mutation-test wave.
2. Make full, module, and diff mutation lanes fail closed on findings, incomplete evidence, stale state, empty scope, and uncovered executable mutants.
3. Establish a fresh full-tree baseline from an immutable candidate revision.
4. Eliminate every survived, timeout, suspicious, and executable no-tests mutant through maintainable behavioural tests, justified production simplification, dead-code removal, or narrowly reviewed exclusion of non-executable structural declarations.
5. Confirm closure with two independent cache-free local full-tree runs. Remote workflow dispatch is optional corroboration after completion.

Constraints:
- Preserve the canonical policy that findings are blocking. Do not introduce mutation-score thresholds or a general waiver registry.
- `no tests`, raw skipped, selected/full `not checked`, empty scope, stale evidence, interrupted runs, and malformed/unknown states must be separately visible and blocking in full, module, selected, diff, pre-push, PR, and scheduled lanes.
- A mutation exclusion is allowed only for an exact declaration body independently proven to be both an abstract-method or Protocol declaration and non-executable in production. Broad function, class, module, pattern, behavioural-code, dead-code, equivalent-mutant, or convenience exclusions are prohibited.
- Prefer public behavioural contracts. Private-helper tests require a recorded reason that no practical public boundary exposes the behaviour.
- Never add exact human-facing wording assertions unless wording is a documented machine, security, or operational contract.
- Keep changed test helpers and tests at cyclomatic complexity <= 5. No new test file may exceed 1,000 lines; any existing changed test file above 1,000 lines must shrink when touched.
- Mutation execution must use isolated, sanitised sandboxes with no credentials or live API variables. No real Perplexity, S3, browser-login, or user-configuration access.
- Future push or GitHub workflow dispatch requires separate explicit user authorisation, but its absence does not block local completion.

Exclusions:
- Release hardening, branch protection, CODEOWNERS, deployment environments, and other GitHub governance.
- Deferred F007 live-API repair.
- Parked Google-login/WARP work.
- Activating unrelated analyser contracts.
- Broad production refactoring that does not remove a demonstrated mutation distinction or genuine design smell.

## Acceptance Criteria
1. The current mutation-test wave is preserved, independently reviewed, organised so no changed test file exceeds 1,000 lines, and passes `UV_OFFLINE=1 npm_config_offline=true make ci-conventional`.
2. The canonical mutation report records declared scope, selected patterns, source revision, result-input fingerprint, independently enumerated generated/selected/result counts, missing/extra/duplicate keys, completeness, mutant-keyset digest, all distinct result categories including `no_tests` and raw skipped, environment identity, and mutation-run outcome. Raw skipped or any unaccounted state prevents `status: clean`.
3. Full, module, and diff targets all route through the canonical policy, use valid mutant-name patterns, distinguish discovery errors from genuine skips, and return non-zero for findings, no-tests, incomplete, stale, empty, interrupted, or malformed evidence.
4. A fresh cache-free full-tree baseline is produced from an immutable committed candidate. Generated keys are independently enumerated from generated Python, every generated key has exactly one result, there are no missing/extra/duplicate keys, `not_checked = 0`, category totals reconcile, all 105 candidate source modules have exactly one primary task owner, and task manifests form an exact disjoint partition of the generated keyset.
5. Every baseline timeout is reproduced serially and resolved to three consecutive killed outcomes; every executable no-tests key gains stable test association and is killed. Only user-authorised, independently reviewed, exact abstract/Protocol non-executable declarations may receive a narrow tracked `pragma: no mutate` exclusion recorded in `quality/mutation-exclusions.toml`.
6. Every fresh-baseline survived or suspicious key is eliminated. Each remediation wave records its before/after keyset, exact killed keys, equivalent/design-smell disposition, focused tests, elapsed time, and independent review result.
7. Two independent full-tree runs from the same accepted Git SHA/tree and path-independent environment identity begin without any `mutants` path and finish with identical generated-keyset and normalised-result hashes. Environment identity includes `uv.lock`, Python implementation/full version/cache tag/platform, uv version, installed-distribution inventory digest, verified installed Mutmut distribution-content digest, and locked Mutmut wheel filename/SHA-256. Each report has zero survived, timeout, suspicious, no-tests, skipped, and not-checked outcomes and `status: clean`.
8. Final ordinary quality remains green: `UV_OFFLINE=1 npm_config_offline=true make ci-conventional` passes, no credential is logged, no live/manual test runs, and no mutation-only test freezes incidental implementation detail.
9. The mutation scheduled workflow and documentation describe the actual Mutmut 3 state directory (`mutants/`), scope/denominator semantics, fresh-run rule, controlled inner timeouts, report guarantees, and fail-closed behaviour. Remote dispatch is optional follow-up evidence and is not required for completion.

## Current-State Evidence
- Protected baseline: `HEAD eed5f81a6a955f83667f51793cdb42cef1da3e4e`; branch `master...origin/master`; staged diff empty; 10 unstaged test files with 1,608 insertions and 14 deletions.
- Planning observation only: before this planning invocation, 521 focused tests and `UV_OFFLINE=1 npm_config_offline=true make ci-conventional` passed. This informs T001 but is not closure evidence; csm-build must rerun it.
- Latest canonical scheduled report: `/tmp/opencode/mutation-31303477652/mutation-report.json` records Mutmut 3.5.0, 9,620 total, 6,057 killed, 3,452 survived, 27 timeout, 84 skipped, 0 suspicious, and 0 not-checked.
- Planning observation only: retained `/tmp/opencode` selected metadata contains 3,558 killed, 1,474 survived, 21 timeout, 40 no-tests, and 4,527 not checked, but later slices reran only subsets and some current tests differ. T005 must not use these counts as scope authority.
- The current ten target groups contain 5,093 generated mutants; the earlier 5,053 checked denominator omitted 40 no-tests keys.
- Forty no-tests keys comprise 21 base `Formatter` declarations, 3 query `_Formatter` protocol declarations, and 16 executable `_handle_broken_pipe` mutants.
- The 10 target groups account for 2,105 historical survivor records; the full-tree report contains a further 1,374 actionable records across 49 modules outside those groups.
- `[tool.mutmut]` mutates all `src/perplexity_cli/` and selects tests through the exclusions at `pyproject.toml:177-181`; `do_not_mutate` is empty.
- The current policy treats only survived/timeout/suspicious as actionable and maps `no tests` to informational skipped at `scripts/mutation_policy.py:59-81`; empty results can currently report clean.
- `make mutate-module` passes a filesystem path even though Mutmut 3 expects mutant-name patterns (`Makefile:298-303`). `make mutate-diff` loses discovery subprocess failures through process substitution and raw selected Mutmut outcomes are not policy-classified (`Makefile:304-319`).
- Mutmut 3.5 persists generated state under `mutants/`, while live documentation still contains `.mutmut-cache` claims.
- Mutmut 3.5 skips previously completed keys and only collects statistics for newly discovered node IDs; a changed existing test does not make retained metadata authoritative. Canonical closure therefore requires a missing `mutants/` directory before each full run.
- Current changed test files include `tests/test_api_client.py` (1,127 lines) and `tests/test_oauth_handler.py` (1,036 lines); repository size/complexity gates do not cover tests.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|---|---|---|---|---|
| A001 | Scope is mutation work only | user-dictated | User selected "Mutation work only" | accepted |
| A002 | Completion means full-tree canonical clean, not only the current ten modules | decision | Ten groups cover about 53% of generated mutants; scheduled automation is full-tree | accepted |
| A003 | No mutation-score threshold or general waiver registry will be added | existing policy | `QUALITY_GATES.md` documents all actionable mutants as blocking | accepted |
| A004 | No-tests, incomplete, stale, empty, interrupted, raw skipped, and malformed evidence blocks every mutation lane | user-dictated | User selected "Block all lanes" | accepted |
| A005 | Exact non-executable abstract/Protocol declarations may receive narrow tracked exclusions after independent proof | user-dictated | User selected "Allow narrow exclusions". This is blanket authority when every mechanical eligibility, proof, manifest and independent-review condition in this plan passes; no per-record user prompt is required. Behavioural and broad exclusions remain prohibited | accepted |
| A006 | Canonical closure runs are always cache-free; incremental metadata is advisory only | decision | Mutmut 3.5 retains stale associations/outcomes across changed existing tests | accepted |
| A007 | Two independent full runs are required for final closure | decision | Detects stale metadata, partial selection, and non-deterministic timeout outcomes | accepted |
| A008 | Current test changes are protected user work and are checkpointed before broad remediation | observation | Ten unstaged files existed at planning intake | accepted |
| A009 | Full-run counts in this plan are historical until T005 creates a fresh baseline | observation | Retained selected stores are partial and current tests differ | accepted |
| A010 | GitHub push/workflow dispatch is a later explicit-authorisation gate | repository policy | Planning/build commits do not imply push permission | accepted |
| A011 | Two independent local full runs complete the plan; remote workflow proof is optional | user-dictated | User selected "Local proof completes" | accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|---|---|---|---|---|---|
| R001 | What is the current protected state? | `GIT_OPTIONAL_LOCKS=0 git status`, `git rev-parse`, `git diff --stat/check` | Read-only; before/after unchanged | HEAD `eed5f81`; ten unstaged test files, 1,608 additions/14 deletions | T001 owns and preserves current work |
| R002 | Are retained selected counts authoritative? | Read existing `/tmp/opencode/pxcli-mutmut-*` metadata and compare test hashes | Planning observation from read-only inspection; raw transcript is not durable closure evidence | Some current tests differ; final slice reran only three groups | T005 must run fresh full baseline |
| R003 | How does Mutmut 3.5 reuse state? | Read installed Mutmut 3.5 source and metadata | Planning observation from read-only inspection; csm-build revalidates locked CLI behaviour | State is `mutants/`; changed existing tests do not refresh all associations/outcomes | A006; T003 fresh-run enforcement |
| R004 | What debt is hidden by current policy? | Compare metadata status codes with `mutation_policy.py` and schema | Read-only | 40 no-tests keys are folded into skipped; empty/incomplete can be clean | T002 strengthens report and policy |
| R005 | Why do mutation targets provide weak evidence? | Audit Makefile, policy wrapper, CI workflow and tests | Read-only; repo unchanged | Selected lane is non-blocking, module syntax invalid, discovery errors can false-skip, reports lack provenance/completeness | T002-T004 |
| R006 | What are timeout semantics and hotspots? | Read report, Mutmut timeout code, stats and source | Read-only | Historical 27 timeouts cluster in scraper, OAuth, formatting, retry/rate limit, upload, and API; retained durations indicate deterministic non-termination | T006 serial 3-run triage |
| R007 | How should survivors be decomposed? | Parse report/metadata by module/function and inspect dependencies | Planning observation only; T005 generates authoritative manifests | 1,474 records across current target groups plus 1,374 outside groups; security and dependency waves identified | T007-T021 graph |
| R008 | What test-quality risks exist? | Static review of the 1,608-line diff and quality gates | Read-only; no tests run during planning | 100 added tests, high private/mock coupling, two files >1,000; test complexity/size not gated | T001 and per-wave maintainability rules |
| R009 | Can remote evidence be required without push authority? | User decision plus workflow inspection | Read-only | Local proof completes; remote dispatch is optional and separately authorised | T022 is local-only; RF001 is optional |

## Discovered Requirements
- `NORMS.md` is authentic csm-scan output dated 2026-08-04 (11 days old at execution). Apply absolute imports, snake_case naming, strict typing, architecture-layer boundaries, loopback-only test networking, repository marker exclusions, and conventional/task-prefixed commits to every dispatch.
- T001's protected intake revision is the parent `eed5f81` of the plan-only HEAD `04b8f0e`; the live plan journal is an expected controller edit, not an out-of-scope user change.
- Suppression identity includes source line. Moving an already approved suppression requires a no-growth baseline refresh after owner/reason validation; it is not permission to add or broaden a suppression.
- Mutation evidence tests must include the real `mutants/src/...` layout and exact locked CLI (`results --all True`); hand-authored grammar fixtures alone are insufficient.
- Test review ledgers require an independently derived candidate inventory and reviewer identity distinct from the implementer; a fixed row count is not completeness evidence.
- Changed test functions/helpers are held to CC <=5 even though repository-wide Radon excludes tests; task static validation must enforce this explicitly.
- Preserving the current direct-script Make contract requires one annotated E402 suppression after repository-root bootstrap; this reviewed quality-infrastructure exception is tracked separately from mutation exclusions.
- Repository Semgrep, not Ruff, is authoritative for boolean-parameter policy in scripts; T002 now uses semantic declaration kinds and callable invariants rather than boolean parameters.
- Tool-error reports must serialise duplicate actionable/unsafe evidence as unique detail examples while preserving occurrence counts and duplicate keys in evidence.
- Structural exclusion eligibility must resolve exact supported `Protocol` and `abstractmethod` imports/aliases; suffix-like names are ineligible.
- T003 must add `tests/test_mutation_evidence.py` and `tests/test_mutation_test_review_ledger.py` to Mutmut's meta-test ignore set before any canonical run.
- Structural exclusion alias tracking must conservatively invalidate any binding inside preceding compound statements while excluding nested function/class/comprehension scopes.
- Generated dictionary validation must bind each key to its owning dictionary stem; a globally equal but swapped key multiset is invalid.
- A future csm-build must begin by recording `HEAD`, branch, staged/unstaged status, and hashes of the ten current test files before editing.
- Do not use `.mutmut-cache` as Mutmut 3 evidence. `mutants/`, its `*.meta`, and `mutmut-stats.json` are the generated state.
- Canonical full runs must use an immutable committed SHA exported into a newly verified `/tmp/opencode` sandbox. They must not copy a live dirty worktree.
- Each sandbox must use sanitised `HOME`, `TMPDIR`, all XDG paths, `UV_CACHE_DIR`, `PYTHONDONTWRITEBYTECODE=1`, no inherited credentials/proxies/live-test variables, and locked Python 3.12/Mutmut 3.5 dependencies.
- Authoritative runs use a pre-verified read-only interpreter environment prepared before evidence capture. No dependency sync, cache warming, package installation, or online fallback occurs inside a run sandbox. If no environment matching `uv.lock` and the locked Mutmut wheel is available, transition BLOCKED before mutation starts.
- Assert `os.path.lexists("mutants")` is false immediately before each canonical run. The runner refuses any existing file, directory, symlink, or broken symlink and never deletes, renames, merges, or reuses it.
- Preserve raw `mutmut results --all` text, report JSON, source/test/config hashes, command line, environment manifest, keyset digest, and normalised result digest for every baseline/final run.
- Generated-key completeness is enumerated independently from generated Python AST, never inferred from the same metadata/result mapping. Selected patterns are applied independently to generated and result collections before exact multiset comparison.
- A selected report must filter to its declared patterns and prove every matching generated key is represented exactly once. Non-selected `not checked` keys do not invalidate a selected report; any selected `not checked` key does.
- Discovery exit 1 is the only valid no-source-change skip. Discovery/tool errors must fail closed.
- Raw Mutmut exit status is not survivor policy. Every full/module/selected/diff target invokes canonical classification. `mutate-results` and `mutate-browse` are inspection-only and never closure authority.
- Full mutation requests at most 19,800 seconds inside the 360-minute workflow budget; selected/PR mutation requests at most 2,100 seconds inside 45 minutes. The workflow records job-start epoch and passes an outer deadline. Before launching, the runner subtracts elapsed setup time, a 120-second report-finalisation bound, and a 600-second full/300-second selected publication reserve; it refuses to start when the remaining budget is insufficient. On timeout it terminates the process group, allows five seconds, then kills remaining children.
- Timeout reruns are serial (`--max-children 1`) and use distinct metadata trees; concurrent mutation processes may not share a sandbox.
- Mutation-specific tests must fail against the intended mutant and pass against original code. Names such as `MutationKillers` are not acceptance evidence.
- Exact log/prose assertions are allowed only for redaction, credential absence, public JSON/NDJSON/schema, exit codes, or documented operational contracts.
- Per wave, record focused-test runtime and mutation runtime. A wave must fit the existing 45-minute selected-lane budget; the final full run must fit the 360-minute workflow budget with time left to publish evidence.
- Any new `pragma: no mutate` requires exact mutant keys/source lines, declaration kind, proof of abstract/Protocol non-executability, owner, reason, reviewer, `quality/mutation-exclusions.toml` entry, and suppression-reason/ratchet validation. Concrete or broad exclusions are prohibited.
- If current test files are split, preserve pytest markers, fixtures, import isolation, and Mutmut test discovery.

## Design
The closure uses an evidence-first burn-down rather than continuing to add broad tests from stale results.

### Canonical mutation authority
`scripts/mutation_policy.py` remains the report/classification authority. It gains explicit full/selected scope, repeated patterns, provenance, completeness, checked counts, keyset digest, run outcome, and a separate actionable `no_tests` category. It returns clean only for non-empty, complete, current evidence with no actionable or no-tests entries.

| Concern | Sole authority | Supporting record |
|---|---|---|
| Outcome classification and exit semantics | `scripts/mutation_policy.py` plus focused tests | Generated mutation report |
| Evidence shape and required fields | `quality/schemas/mutation-report.json` plus producer/schema tests | Schema-valid report |
| Freshness, provenance, completeness, timeout, and orchestration | `scripts/run_mutation.py` plus runner tests | Environment/run manifest and report |
| Reusable local invocation recipes | `Makefile` plus Make-policy tests | Recorded command and exit |
| CI topology and budgets | `.github/workflows/*.yml` plus workflow-policy tests | Optional remote corroboration |
| Execution/recovery status | Primary csm-build controller | Control, Journal, Completion Review |

Markdown status never decides mutation outcomes. Subagents return evidence; only the primary csm-build controller updates Control and task status.

A small typed `scripts/run_mutation.py` CLI owns canonical execution. It accepts full/selected scope, repeated patterns or a frozen task manifest, report path, and required timeout. It refuses any pre-existing `mutants` path without modifying it, starts Mutmut in a process group, applies the lane-specific inner timeout, and emits a schema-valid non-clean report after controlled failure/timeout. Configuration with more than four fields uses a frozen slotted dataclass. It has no cleanup/force flag.

Every execution emits one outcome:
- `clean`, exit 0: non-empty applicable scope; current, complete evidence; exact generated/result key equality; zero survived, timeout, suspicious, no-tests, skipped, and selected not-checked.
- `findings`, exit 1: survived, timeout, suspicious, or no-tests.
- `tool-error`, exit 2: empty applicable scope, incomplete/stale evidence, raw skipped, interrupted/segfault/unknown/malformed result, discovery/tool failure, duplicate/missing/extra key, or count mismatch.
- `not-applicable`, exit 0: diff discovery succeeded and found no mutable source change. This is a recorded skip, never clean closure evidence.

Make targets become thin adapters:
- `make mutate-full-policy`: full, fresh, blocking report.
- `make mutate-module MODULE=api.client`: converts to an exact validated Mutmut pattern and runs selected canonical policy.
- `make mutate-task-policy TASK=T008`: validates T005's frozen task manifest, then runs its exact selected keyset.
- `make mutation-task-static TASK=T008`, `mutation-task-tests`, `mutate-key`, `mutation-wave-policy`, `mutation-manifest-check`, and `mutation-final-policy` provide the tiered task/evidence commands.
- `make mutate-diff`: preserves discovery exit status, maps exact source names to Mutmut patterns (including `__init__.py`), and runs selected blocking policy.
- `make mutate` routes to the full canonical runner. No user-facing execution lane bypasses canonical classification.

### Evidence model
Generated-key completeness is independently verified from generated Python, not inferred from `*.meta`, `mutmut-stats.json`, or a second results invocation. A pure AST verifier accepts only strict numeric mutant definitions matching locked Mutmut's generated-name grammar, explicitly rejects `__mutmut_orig`, trampolines, aliases and malformed suffixes, normalises package/class/nested/async/dunder keys, and cross-checks the definitions against the generated mutant dictionaries. It then compares that multiset with parsed raw result lines. Full scope requires non-empty one-to-one equality. Selected scope applies patterns independently to both collections. Missing, extra, duplicate or dictionary-disagreement keys make evidence incomplete.

Every report binds results to Git SHA/tree, tracked inputs, `pyproject.toml`, `uv.lock`, scope/patterns, generated/selected/result counts, missing/extra/duplicate lists, completeness, generated-keyset/result digests, and a path-independent environment identity. The environment record includes Python implementation/full version/cache tag/platform, uv version, installed-distribution inventory digest, locked wheel identity, and verified installed Mutmut content. Verification reads every hash-bearing `RECORD` entry, hashes the actual installed bytes, rejects missing/extra/mismatched files, then digests the verified actual-file inventory; the separate `RECORD` and locked wheel digests remain supporting fields. Locked wheel: `mutmut-3.5.0-py3-none-any.whl`, SHA-256 `f19f2dd2e977eb9dc17255d8cb11e24fbfc3191620fba3108cac25779c9d78c9`.

### Burn-down model
T005 produces the only authoritative starting ledger. Subsequent tasks own disjoint source/test surfaces and run selected fresh mutation policy for their declared patterns. A task is complete only when its selected report is complete and clean, focused ordinary tests pass, maintainability constraints pass review, and before/after key evidence is journalled.

T005 stores generated manifests under `build/reports/mutation-baseline/<candidate-sha>/`: immutable `source-ledger.json`, `mutant-ledger.jsonl`, baseline manifests/keys for T006-T021, and an append-only `amendments/` directory. The baseline primary manifests are pairwise disjoint and their union equals the baseline generated keyset. T006 is a status overlay whose entries retain their primary owner.

Each primary task and the primary controller jointly own append-only amendments for that task. A source change that adds, renumbers or removes keys records old-to-new mappings, source/test hashes, reason, reviewer and current expected-generated set. Removed sites may be dispositioned as reviewed behavioural simplification, demonstrated dead/unneeded code removal, or an approved structural exclusion. Every new key remains assigned to the same primary module owner. Amendments never rewrite/delete baseline records; they invalidate earlier selected evidence. `mutation-manifest-check` validates the complete amendment chain and full partition after every source change. Task closure compares generated results with the amended current expected set and rejects silent key appearance/disappearance.

The primary source ledger covers every currently tracked module under `paths_to_mutate` exactly once. Braces below are documentation shorthand only; T005 stores literal paths.

| Primary task | Modules | Exhaustive source ownership |
|---|---:|---|
| T007 | 27 | `__init__.py`, `_types.py`, `config/{__init__,defaults,models}.py`, `contracts/{__init__,query}.py`, `ports/__init__.py`, `session_log.py`, `utils/__init__.py`, `utils/{async_bridge,atomic_write,cookies,encryption,exceptions,file_permissions,http_headers,rate_limiter,rate_limiter_models,retry,session_factory,session_token,upstream_contracts,version}.py`, `utils/logging/{__init__,contracts,impl}.py` |
| T008 | 1 | `api/client.py` |
| T009 | 1 | `auth/token_manager.py` |
| T010 | 8 | `formatting/{__init__,base,context,json,markdown,plain,registry,rich}.py` |
| T011 | 1 | `auth/oauth_handler.py` |
| T012 | 1 | `runners/config.py` |
| T013 | 12 | `utils/config/{__init__,contracts,impl}.py`, `utils/file_handler.py`, `utils/style_manager.py`, `threads/{__init__,cache_manager,date_parser,exporter,models,pagination,utils}.py` |
| T014 | 1 | `threads/scraper.py` |
| T015 | 12 | `api/{__init__,contracts,endpoints,models,rest_client}.py`, `attachments/{__init__,upload_manager}.py`, `query_streaming.py`, `utils/attachment_models.py`, `utils/http_errors/{__init__,contracts,impl}.py` |
| T016 | 10 | `auth/{__init__,models,utils}.py`, `models/{__init__,model_config}.py`, `services/{__init__,model_service,ports}.py`, `runners/{models,status}.py` |
| T017 | 1 | `runners/auth.py` |
| T018 | 1 | `runners/export.py` |
| T019 | 1 | `mcp_server.py` |
| T020 | 1 | `query_runner.py` |
| T021 | 27 | `cli.py`, `command_runner.py`, `completion_commands.py`, `envelope.py`, `error_handler.py`, `exit_codes.py`, `help_json.py`, `ndjson.py`, `commands/{__init__,_ctx,_examples,_help_refs,_help_sections,_runner_adapter,_schemas,auth_cmds,config_cmds,doctor_cmds,models_cmds,query_cmd,schema_cmd,skill_cmds,style_cmds,threads_cmds}.py`, `runners/{__init__,_utils,skill}.py` |
| Total | 105 | Exact current configured source inventory |

T005 compares this ledger with the candidate filesystem and generated keyspace. Missing/new/duplicate module ownership, an unmatched key, a pattern that spills into another task, or a task manifest whose union differs from the full generated set is blocking. Zero-mutant files remain owned and recorded.

Dependency order is foundations -> persistence/transports -> consumers/commands -> query/CLI -> two full runs. Counts in task descriptions are historical planning weights, not acceptance thresholds.

### Timeout and no-tests handling
T006 classifies infrastructure-like statuses before survivor waves without editing primary-owned source/tests. Each timeout gets clean-test stability (5/5), test-association evidence and three serial pre-repair mutant runs. Each primary task then implements its T006-assigned repairs: executable no-tests gain stable association and are killed; deterministic timeouts gain the smallest behavioural repair; approved non-executable declarations receive only the exact reviewed exclusion. Historical timeout keys remain open in the overlay until the primary owner records three consecutive fresh serial post-repair killed executions in separate metadata trees. A primary task cannot close until those proofs exist, its timeout/suspicious/no-tests/skipped/not-checked counts are zero, and every removed baseline key has an authorised amendment disposition.

## Execution Graph
```text
G1: T001 current-test checkpoint || T002 report-policy authority
             T002 -> T003 canonical runner/Make targets -> T004 CI/docs
T001 + T003 + T004 -> T005 fresh full baseline -> T006 status triage/exclusion decisions

After T006:
  T007 utility/security foundations || T010 formatting || T012 config runner
  T007 -> (T008 API client || T009 token persistence || T013 persistence/files/threads)
  T009 -> T011 OAuth/CDP
  T007 + T013 -> T014 scraper
  T007 + T008 -> T015 transport/upload/streaming
  T009 + T011 + T013 + T015 -> T016 auth consumers/models/status

Dependent command layer:
  T009 + T011 -> T017 auth runner
  T014 -> T018 export runner
  T008 + T009 + T010 + T015 -> T019 MCP
  T008 + T009 + T010 + T013 + T015 -> T020 query runner
  T012 + T016 + T017 + T018 + T019 + T020 -> T021 CLI/output/help remainder

T007-T021 all clean -> T022 two local full runs + final conventional evidence
```

Planning dependency spine: T002 -> T003 -> T004 -> T005 -> T006, followed by several equal-depth chains into T021 and T022. Representative longest dependency-depth chains include T007 -> T009 -> T011 -> T016, T007 -> T008 -> T015 -> T020, and T007 -> T013 -> T014 -> T018. These are not duration-weighted critical paths; csm-build recalculates scheduling from observed runtimes.

Parallel tasks share no owned source or test files inside the same group. Mutation commands may run concurrently only in distinct sandboxes with bounded CPU; final full runs are serial.

## Numbered Plan
1. [completed] Preserve, organise, and checkpoint the current mutation-test wave
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: standard
   - Owned scope: the ten explicitly named intake test files; new capability-specific split files; `quality/remediation/mutation-test-review.json`; `quality/remediation/mutation-test-node-map.json`; `quality/remediation/mutation-test-independent-review.json`; `tests/test_mutation_test_review_ledger.py`; primary plan journal updates
   - Not in scope: production code, mutation policy, adding more survivor tests, changing test semantics merely to reduce line count
   - Spike candidate: Prove that moving tests preserves node IDs/markers needed by Mutmut where practical; run collect-only before and after in an isolated copy if node stability is uncertain.
   - Actions: In RECOVER require intake HEAD `eed5f81`, empty index, no untracked/out-of-scope changes, and exact hashes of all ten paths; create a mode-0700 `/tmp/opencode` recovery package containing full-index binary patch, file copies, hashes, status and revisions; block on mismatch without staging/resetting. Classify every added private-helper and exact-wording assertion in the durable review ledger as retain/rewrite/move/remove with public-boundary attempt, exactness reason, mutant/behaviour, evidence and independent reviewer. Split files above 1,000 lines. Stage only an enumerated pathspec; review staged diff; run the complete pre-commit hook as a preflight; review hook-adjusted staged blobs; commit normally with hooks enabled; verify committed paths/blobs/patch equal the reviewed post-preflight index.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_mutation_test_review_ledger.py -q && UV_OFFLINE=1 npm_config_offline=true make ci-conventional` exits 0.
   - Validation: Collect-only node/marker comparison; changed-file focused tests; Ruff format/check; suppression reasons; no ledger row unresolved; no changed test file >1,000 lines; post-hook staged diff and final commit patch/blob manifests match exactly.
   - Acceptance evidence: Intake/recovery patch hashes, explicit path list, review ledger, pre/post-hook staged patch hashes/blob IDs, collected nodes/markers, focused count/runtime, full gate, independent verdict, commit SHA/tree.
   - Completed evidence: protected intake patch `032f27e...`; 521-to-521 node/marker bijection; 108 specific reviewed candidates; durable independent-review artifact; every changed test/helper CC<=5 and file <=1,000 lines; 521 behavioural, 14 ledger, and 627 combined focused tests pass; full conventional gate passes; final independent verdict READY. Commit SHA/tree is recorded by the checkpoint journal after hooks.
   - Repair attempts: 2
   - Recovery note: Any hash, concurrent-edit, hook, staged-path, or committed-blob mismatch preserves status/unstaged/staged patches under the recovery package and transitions BLOCKED. Never reset, checkout, amend, or overwrite unmatched user edits; use a separately reviewed forward correction after a committed mismatch.

2. [completed] Make mutation reports complete, scoped, provenance-bound, and no-tests aware
   - Task ID: T002
   - Depends on: none
   - Parallel group: G1
   - Risk: high - canonical quality-policy and evidence-schema change
   - Owned scope: `scripts/mutation_policy.py`, new pure `scripts/mutation_evidence.py`, `quality/schemas/mutation-report.json`, `tests/test_mutation_policy.py`, new `tests/test_mutation_evidence.py`, report/generated-source fixtures
   - Not in scope: running Mutmut, Make targets, CI workflows, score thresholds, general waivers
   - Spike candidate: Verify locked Mutmut's exact `results --all` boolean syntax and all raw statuses through an isolated synthetic CLI contract before changing parsing.
   - Actions: Add full/selected scope and repeated patterns; independently enumerate only strict numeric generated mutant definitions and cross-check generated dictionaries; reject originals/trampolines/aliases/malformed mappings; report provenance, distinct raw statuses, run outcome, counts/missing/extra/duplicates, completeness, environment/keyset/result digests, and `no_tests`; keep raw skipped distinct and incomplete; fail closed on all user-approved blocking states; validate exact structural exclusion manifest separately from generated results.
   - Acceptance signal: `UV_OFFLINE=1 uv run pytest tests/test_mutation_policy.py tests/test_mutation_evidence.py -q` passes strict numeric key, original/trampoline/alias rejection, generated-dictionary disagreement, nested/async/dunder/class/package-init normalisation, completeness/duplicate, skipped/no-tests/interrupted/unknown, selected/full and schema cases.
   - Validation: Ruff format/lint and strict Pyright pass; locked real-generated fixtures cover Mutmut 3.5 grammar; schema fixtures reconcile sums and reject extra/missing provenance.
   - Acceptance evidence: Schema diff, exit-code matrix, fixture matrix, exact Mutmut CLI result, test output, independent policy review.
   - Completed evidence: schema v2 and semantic validator; exact locked CLI/direct-script contracts; strict real-layout/generated-dictionary enumeration; scope/provenance/environment/completeness/status/no-tests/duplicate/exclusion evidence; exact alias/shadow and per-dictionary ownership checks; 94 focused tests, Ruff, Pyright, Semgrep, suppression ratchets and full conventional gate pass; final independent verdict READY. Commit SHA/tree is recorded by the next checkpoint journal entry.
   - Repair attempts: 4
   - Recovery note: Keep parser/report commits separate. If schema and producer diverge, recover from the last passing fixture matrix before wiring execution.

3. [in_progress] Add a fresh canonical mutation runner and repair Make targets
   - Task ID: T003
   - Depends on: T002
   - Parallel group: G2
   - Risk: high - stale or partial evidence could falsely pass quality gates
   - Owned scope: new `scripts/run_mutation.py`, `Makefile` mutation/manifest/tier targets, `pyproject.toml` Mutmut meta-test ignores, `scripts/discover_mutate_diff_files.py` only if exact mapping requires it, new `tests/test_run_mutation.py`, focused Make/discovery/configuration-policy tests
   - Not in scope: CI workflows, survivor remediation, deleting/renaming/reusing any existing `mutants` path, cache restore, package installation inside run sandboxes
   - Spike candidate: In an isolated copy, prove module/package/`__init__.py` pattern matching and the locked `mutmut results --all` invocation; prove raw survivor runs exit independently of policy.
   - Actions: Implement typed orchestration; refuse any pre-existing `mutants` path via `lexists`; require full/selected/manifest scope; verify the pre-provisioned interpreter by hashing actual installed files against Mutmut `RECORD` plus lock/wheel/environment identity; derive allowable run time from outer deadline after reserving 120 seconds for report finalisation and 600/300 seconds for publication; cap requested full/selected runs at 19,800/2,100 seconds; control the process group; always emit non-clean report after controlled failure. Implement and contract-test every required Make target: `mutation-baseline`, `mutation-manifest-check`, `mutation-triage-check`, `mutation-task-static`, `mutation-task-tests`, `mutate-key`, `mutate-task-policy`, `mutation-wave-policy`, `mutation-final-policy`, plus canonical full/module/selected/diff/mutate adapters. Add `tests/test_mutation_evidence.py` and `tests/test_mutation_test_review_ledger.py` to Mutmut's meta-test ignore set and configuration-policy assertions before any canonical run.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_mutation_policy.py tests/test_mutation_evidence.py tests/test_run_mutation.py tests/test_mutate_diff_files.py tests/test_make_policy.py -q` passes path-refusal, actual installed-file tampering/RECORD/wheel identity, outer-deadline reserve, timeout/process-group/report, all Make target, pattern, discovery and outcome matrices.
   - Validation: Ruff/format/Pyright pass; no `shell=True`; existing file/dir/symlink/broken-symlink sentinels remain unchanged; no cleanup flag exists; exact module/package patterns have no prefix spill; every required Make target has argument, report and exit-code contract tests.
   - Acceptance evidence: Command/exit matrix, generated path-safety proof, selected key matching examples, report-on-failure fixture, independent security review.
   - Repair attempts: 0
   - Recovery note: Runner and Make wiring must be separate commits. If Make integration fails, invoke the tested runner CLI directly while repairing only the adapter.

4. [pending] Make CI mutation evidence mandatory and correct mutation documentation
   - Task ID: T004
   - Depends on: T003
   - Parallel group: G2
   - Risk: standard
   - Owned scope: `.github/workflows/mutation-scheduled.yml`, mutation-diff job in `.github/workflows/ci.yml`, workflow-policy tests, `QUALITY_GATES.md`, mutation documentation tests, `.gitignore` comments if needed
   - Not in scope: dispatching workflows, branch protection, changing schedules, general GitHub governance
   - Spike candidate: none
   - Actions: Route scheduled, PR, pre-push, full, module and diff execution through canonical reports under the user-approved fail-closed matrix; record job-start epoch and pass outer deadline; request at most 19,800-second scheduled and 2,100-second PR inner runs while enforcing 600/300-second publication reserves plus the report bound; require artefacts with `if-no-files-found: error`; show scope/completeness/no-tests/skipped in summaries; replace `.mutmut-cache` and raw-exit claims; document fresh-run and selected denominator semantics.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true uv run pytest tests/test_workflow_configuration.py tests/test_quality_gates_documentation.py tests/test_mutation_policy.py tests/test_run_mutation.py -q && UV_OFFLINE=1 make actionlint` exits 0.
   - Validation: `make workflow-policy`; documentation drift tests; inspect workflow permissions remain read-only; all actions stay SHA-pinned.
   - Acceptance evidence: Workflow topology result, actionlint result, required-report assertions, documentation search proving no live stale cache/exit claims.
   - Repair attempts: 0
   - Recovery note: Workflow and docs share semantics but not implementation. Revert only the failing adapter commit; retain tested policy/runner commits.

5. [pending] Produce the authoritative fresh full-tree baseline and freeze the burn-down ledger
   - Task ID: T005
   - Depends on: T001, T003, T004
   - Parallel group: G3
   - Risk: high - expensive evidence run and task-scope authority
   - Owned scope: isolated `/tmp/opencode` run sandbox; ignored `build/reports/mutation-baseline/<candidate-sha>/` source/mutant/task manifests; primary csm-build journal updates
   - Not in scope: source/test remediation, reusing retained metadata, live network/services, changing policy after seeing counts
   - Spike candidate: Verify a pre-provisioned read-only Python 3.12 environment against `uv.lock`, installed-distribution inventory, Mutmut `RECORD`, and locked wheel hash; if unavailable or inconsistent, stop BLOCKED before creating evidence.
   - Actions: Commit an immutable candidate; export it into a fresh sanitised sandbox; invoke the verified interpreter directly without sync/install/cache warming; assert no `mutants` path via `lexists`; run full canonical policy; independently enumerate generated keys; preserve report/manifests; generate exhaustive 105-module primary ownership, exact task patterns/tests/keys, and T006 status-overlay manifests; reject gaps, duplicates, prefix spill or union mismatch; record durable hashes/counts/commands in the journal.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true sh -c 'set +e; make mutation-baseline CANDIDATE_SHA="$1"; rc=$?; set -e; test "$rc" -eq 0 -o "$rc" -eq 1; make mutation-manifest-check' sh '<40-hex>'` exits 0. Exit 1 is accepted only as an authoritative findings baseline, never clean evidence.
   - Validation: Reclassify raw evidence without rerunning and obtain identical digest; protected-state before/after matches; no credentials/live/manual nodes; generated/results multisets match; task manifest union equals full keyset.
   - Acceptance evidence: Candidate SHA/tree, environment manifest, command/exit, report path/hash, keyset/result digests, totals by status/module/function, runtime, protected-state comparison.
   - Repair attempts: 0
   - Recovery note: A partial or missing report is not a baseline. Preserve it for diagnosis when useful, abandon the entire sandbox, and create a new sibling from the same candidate; never delete `mutants/` in place to manufacture freshness.

6. [pending] Classify every timeout, suspicious, no-tests, and structural-exclusion candidate
   - Task ID: T006
   - Depends on: T005
   - Parallel group: G4
   - Risk: high - async, retry, file-descriptor, cancellation, and mutation-exclusion behaviour
   - Owned scope: T005's `T006` status-overlay manifest; new `quality/mutation-triage.json`; new `quality/mutation-exclusions.toml`; manifest/triage validation tests; primary controller journal
   - Not in scope: editing primary-owned source/tests, resolving ordinary survivors, broad/behavioural/dead-code/equivalent exclusions, real sleeps/network/browser/S3
   - Spike candidate: For each key, identify associated tests and run clean tests 5/5 plus the exact mutant 3/3 serially in separate isolated metadata trees before classifying it.
   - Actions: For each overlay key record primary task, exact source/mutant, associated tests/timing, 5/5 clean-test result, 3/3 serial mutant result, and classification: deterministic timeout, flaky/resource, over-associated, executable uncovered, dead code, product defect, or non-executable abstract/Protocol declaration. User-authorised exclusion records require exact declaration/non-executability proof and independent reviewer. Primary tasks later implement repairs and prove kills.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutation-triage-check TASK=T006` exits 0 with every overlay key classified exactly once, every proposed exclusion eligible/reviewed, and no unresolved classification.
   - Validation: `make mutation-task-static TASK=T006` and `make mutation-task-tests TASK=T006`; timeout clean tests 5/5 and exact mutants 3/3 are recorded; exclusion manifest/schema tests pass.
   - Acceptance evidence: Complete per-key classification ledger, associations/timings/repetitions, approved exclusion records/reviewers, manifest hash, independent review.
   - Repair attempts: 0
   - Recovery note: Work one hotspot in an isolated sandbox at a time and write only classification evidence. Primary source/test repairs resume under T007-T021; never share Mutmut metadata across agents.

7. [pending] Close utility and security foundation survivors outside the current ten groups
   - Task ID: T007
   - Depends on: T006
   - Parallel group: G5
   - Risk: high - encryption, atomic writes, permissions, logging, retries, headers, and session behaviour
   - Owned scope: exact T007 source/test/pattern/key manifest frozen by T005; 27 primary modules in the exhaustive source ledger above
   - Not in scope: API client, token manager, OAuth handler, file handler/config implementation, broad rewrites, exact non-security log prose
   - Spike candidate: Reconcile the historical 240 actionable records with T005; drop any module already clean before dispatch.
   - Actions: Prioritise credential confidentiality, atomic preservation, retry bounds, permission checks, parser contracts, and resource cleanup; add dedicated behavioural owners where missing; simplify production only for demonstrated design smells.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T007` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T007` and `make mutation-task-tests TASK=T007`; security redaction negatives; selected runtime <= 2,100 seconds; independent security review.
   - Acceptance evidence: Baseline keys, killed/dispositioned keys, test/runtime delta, clean report hash, independent security review.
   - Repair attempts: 0
   - Recovery note: Partition by non-overlapping module/test owner and commit independently; integrate before one combined selected run.

8. [pending] Close API transport and retry survivors
   - Task ID: T008
   - Depends on: T006, T007
   - Parallel group: G6
   - Risk: high - authentication statuses, retries, transport lifecycle, and credential-safe diagnostics
   - Owned scope: `src/perplexity_cli/api/client.py`, its capability-split tests from T001
   - Not in scope: endpoints/rest client, query orchestration, exact diagnostic punctuation, live HTTP
   - Spike candidate: Refresh the historical 183-survivor cluster against T005 and classify RetryHandler before transport adapters.
   - Actions: Prove status taxonomy, retry exhaustion/delays, exception causes, response/header validation, cookies/token non-leakage, context-manager cleanup, and no retry after yield; avoid private-state assertions where public stream behaviour suffices.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T008` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T008` and `make mutation-task-tests TASK=T008`; no secret values in logs; independent security review.
   - Acceptance evidence: Before/after key list, security contracts, focused runtime, report hash, review verdict.
   - Repair attempts: 0
   - Recovery note: Commit RetryHandler and transport-adapter subclusters separately; rerun only exact failed keys after repairs, then one fresh module run.

9. [pending] Close token persistence survivors
   - Task ID: T009
   - Depends on: T006, T007
   - Parallel group: G6
   - Risk: high - credential encryption, file permissions, atomicity, and cookie validation
   - Owned scope: `src/perplexity_cli/auth/token_manager.py`, its capability-split tests from T001
   - Not in scope: OAuth/browser flow, auth command runner, logging secrets, token-format migration
   - Spike candidate: Refresh the historical 116 survivors and separate equivalent debug-message mutations from persistence/security distinctions.
   - Actions: Prove encrypted record schema, atomic failure preservation, mode verification, malformed data/cookies, token age boundary, cleanup, exception chaining, and credential-safe logging; simplify duplicate branches when that removes meaningless mutants.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T009` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T009` and `make mutation-task-tests TASK=T009`; POSIX/guarded-Windows security assertions; independent review.
   - Acceptance evidence: Key ledger, filesystem/security contracts, report hash, runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Preserve token fixtures and never read the real token path. Commit persistence, cookies, and diagnostics subclusters separately.

10. [pending] Close formatting package survivors without freezing presentation trivia
   - Task ID: T010
   - Depends on: T006
   - Parallel group: G5
   - Risk: standard
   - Owned scope: exact T010 source/test/pattern/key manifest frozen by T005; eight formatting modules in the exhaustive ledger and capability-specific tests
   - Not in scope: MCP/query rendering, terminal library internals, exact ANSI/border/style assertions unless public contract, broad mutation exclusions
   - Spike candidate: Pilot JSON/plain/Markdown/registry first and independently classify likely equivalent Rich presentation mutants before adding assertions.
   - Actions: First implement T006-assigned formatting timeout/no-tests repairs and any approved exact declaration exclusions. Preserve machine JSON contracts exactly; assert semantic Markdown/plain/Rich content/order; cover registry resolution, block parsing termination, fallback behaviour, citation/reference rules, and direct rendering side effects; refactor repeated render paths only when behaviour remains explicit.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T010` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T010` and `make mutation-task-tests TASK=T010`; no border-glyph/ANSI incidental coupling; independent maintainability review.
   - Acceptance evidence: Machine-vs-presentation contract ledger, key dispositions, clean report hash, file sizes/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Keep leaf formatter and Rich commits separate. If Rich equivalent classification blocks, stop for explicit review rather than adding brittle assertions.

11. [pending] Close OAuth and CDP boundary survivors
   - Task ID: T011
   - Depends on: T006, T009
   - Parallel group: G7
   - Risk: high - authentication, token extraction, WebSocket correlation, timeout, and cleanup
   - Owned scope: `src/perplexity_cli/auth/oauth_handler.py`, capability-specific OAuth tests from T001
   - Not in scope: real Chrome, Google login, WARP, live credentials, auth command runner
   - Spike candidate: Refresh the historical 143 survivors; serially prove CDP receive/correlation tests have no leaked tasks and deterministic fake time.
   - Actions: Prove message schema/error handling, command ID correlation, lock release, cancellation, exact timeout boundaries, local-storage/cookie precedence, cleanup on every exit, and safe synchronous bridge.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T011` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T011` and `make mutation-task-tests TASK=T011`; repeated strict-asyncio/no-browser checks; independent security review.
   - Acceptance evidence: Key list, async leak/cancellation evidence, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Partition CDP client, token extraction, polling, and top-level flow commits. Resume from the last clean subcluster.

12. [pending] Close configuration runner survivors
   - Task ID: T012
   - Depends on: T006
   - Parallel group: G5
   - Risk: standard
   - Owned scope: `src/perplexity_cli/runners/config.py`, `tests/test_config_runners.py`
   - Not in scope: config storage implementation, style manager internals, exact human prose outside documented guidance
   - Spike candidate: Refresh the historical 108 survivors; identify JSON/schema contracts separately from human presentation.
   - Actions: Prove context normalisation, env override ordering, JSON/schema output, style/config error routing, toggle changes, and no unintended writes; use semantic assertions for human output.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T012` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T012` and `make mutation-task-tests TASK=T012`; isolated config paths; maintainability review.
   - Acceptance evidence: Key ledger, output-contract classification, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Preserve isolated config fixtures; commit context, output, and command-routing clusters separately.

13. [pending] Close configuration, local-file, and thread-persistence survivors
   - Task ID: T013
   - Depends on: T006, T007
   - Parallel group: G8
   - Risk: high - encrypted cache, atomic persistence, file inclusion, CSV safety, and pagination
   - Owned scope: exact T013 source/test/pattern/key manifest frozen by T005; 12 modules in the exhaustive ledger; dedicated test paths fixed before dispatch
   - Not in scope: scraper, export command runner, live filesystem outside temp fixtures, current scraper/export test ownership
   - Spike candidate: Reconcile the historical 379 survivors and create dedicated owners for thread models/pagination rather than growing scraper tests.
   - Actions: Prove config merging, path isolation, attachment filtering, style persistence, encrypted cache format/permissions/coverage, date boundaries, CSV formula neutralisation, thread schema, pagination offsets/signatures/progress, and cache conversions.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T013` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T013` and `make mutation-task-tests TASK=T013`; temp-only filesystem audit; independent security review.
   - Acceptance evidence: Pattern manifest, key dispositions, temp-path proof, clean report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Freeze non-overlapping internal test/source submanifests before parallel dispatch; otherwise execute serially. Integrate commits before the combined task run.

14. [pending] Close thread scraper survivors
   - Task ID: T014
   - Depends on: T006, T007, T013
   - Parallel group: G9
   - Risk: high - pagination termination, cache preservation, upstream validation, rate limiting, and errors
   - Owned scope: `src/perplexity_cli/threads/scraper.py`, `tests/test_scraper_coverage.py`, `tests/test_scraper_cache_filter.py`
   - Not in scope: cache/pagination source already owned by T013, export command runner, live Perplexity API
   - Spike candidate: T005 must refresh the stale historical 162-survivor count against current scraper tests before dispatch.
   - Actions: Prove response protocol/schema, exact request payload/context, pagination progress and repeated-page termination, date cut-offs, typed error preservation, rate-limit interaction, cache hit/merge/save, cancellation, and resource cleanup.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T014` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T014` and `make mutation-task-tests TASK=T014`; serial/xdist, no-network/no-real-sleep; independent review.
   - Acceptance evidence: Refreshed baseline, key list, termination/error contracts, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Commit response helpers, API loop, cache orchestration, and public scrape clusters separately. Never reuse pre-T005 stale metadata.

15. [pending] Close endpoint, upload, streaming, and HTTP-error survivors
   - Task ID: T015
   - Depends on: T006, T007, T008
   - Parallel group: G8
   - Risk: high - upload credentials, cancellation, streaming termination, and HTTP taxonomy
   - Owned scope: exact T015 source/test/pattern/key manifest frozen by T005; 12 modules in the exhaustive ledger; dedicated test paths fixed before dispatch
   - Not in scope: API client, query runner, MCP, live uploads/HTTP, current target test files
   - Spike candidate: Reconcile the historical 332 actionable records and verify upload cancellation timeout status from T006 before survivor work.
   - Actions: Prove endpoint final-message collection, REST headers/JSON/errors, typed model extraction, upload URL/bijection/S3 validation/cancellation, streaming state/NDJSON/references/error routing, and HTTP/network classification.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T015` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T015` and `make mutation-task-tests TASK=T015`; no network/credentials and async cleanup; independent security review.
   - Acceptance evidence: Pattern/key ledger, request/response security contracts, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Freeze non-overlapping endpoint/rest, upload, streaming, and HTTP-error source/test submanifests before parallel dispatch; otherwise execute serially.

16. [pending] Close authentication consumers, models, services, and status survivors
   - Task ID: T016
   - Depends on: T009, T011, T013, T015
   - Parallel group: G10
   - Risk: high - optional authentication, subscription/status reporting, and credential diagnostics
   - Owned scope: exact T016 source/test/pattern/key manifest frozen by T005; ten modules in the exhaustive ledger; dedicated test paths fixed before dispatch
   - Not in scope: token/OAuth internals, auth command runner, API endpoints, exact human status prose except security guidance
   - Spike candidate: Reconcile the historical 261 survivors and split security status contracts from table/presentation mutants.
   - Actions: Prove optional/required token semantics, model filtering/search/service requests, list error handling, subscription detection, token verification/age/mtime, doctor-security JSON/text, and secret-safe output.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T016` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T016` and `make mutation-task-tests TASK=T016`; redaction/no-real-config assertions; independent security review.
   - Acceptance evidence: Pattern/key ledger, security/presentation classification, clean report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Commit auth utility, model stack, and status runner separately; combine only after each focused suite is green.

17. [pending] Close auth command runner survivors
   - Task ID: T017
   - Depends on: T009, T011
   - Parallel group: G11
   - Risk: standard
   - Owned scope: `src/perplexity_cli/runners/auth.py`, `tests/test_auth_runner.py`
   - Not in scope: token persistence, OAuth implementation, exact troubleshooting punctuation, real login/logout
   - Spike candidate: Refresh the historical 94 survivors and separate JSON/exit/security contracts from human guidance.
   - Actions: Prove context flags, success persistence, timeout/OS error routing, credential-path redaction, logout states, JSON schema, keyboard interruption, and troubleshooting content semantically.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T017` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T017` and `make mutation-task-tests TASK=T017`; no real token/browser; maintainability review.
   - Acceptance evidence: Key ledger, output classification, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Keep authentication and logout clusters separate; preserve all security redaction assertions.

18. [pending] Close export command runner survivors
   - Task ID: T018
   - Depends on: T014
   - Parallel group: G11
   - Risk: standard
   - Owned scope: `src/perplexity_cli/runners/export.py`, `tests/test_export_runner.py`
   - Not in scope: scraper/cache/CSV implementation, live export, exact human progress wording
   - Spike candidate: Refresh the historical 166 survivors after scraper contracts stabilise.
   - Actions: Prove request preparation, auth/cache/rate-limit paths, date/output validation, scrape/export orchestration, JSON/schema and CSV side-effect ordering, exact significant collaborator arguments, and error taxonomy.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T018` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T018` and `make mutation-task-tests TASK=T018`; temp-only output; maintainability review.
   - Acceptance evidence: Key ledger, side-effect ordering contracts, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Commit validation, output, and orchestration clusters separately; rerun focused suite after each.

19. [pending] Close MCP boundary survivors
   - Task ID: T019
   - Depends on: T008, T009, T010, T015
   - Parallel group: G11
   - Risk: high - public tool schemas, authentication forwarding, and server configuration
   - Owned scope: `src/perplexity_cli/mcp_server.py`, `tests/test_mcp_server.py`, `tests/test_mcp_protocol.py` only where public protocol evidence is required
   - Not in scope: query implementation, live MCP daemon/network, additive metadata restrictions not required by protocol
   - Spike candidate: Refresh the historical 100 survivors and inspect `_parse_args`/tool registration mutants against public protocol semantics.
   - Actions: Prove argument/config forwarding, tool schemas, quick/deep mode mapping, auth/search propagation, result/reference JSON, renderer dispatch, progress, friendly errors, and server startup delegation.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T019` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T019` and `make mutation-task-tests TASK=T019`; no daemon remains; independent public-interface review.
   - Acceptance evidence: Key ledger, protocol contracts, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Partition parse/config, query/render, registration/tool, and main clusters. Use bounded protocol fixtures only.

20. [pending] Close query orchestration survivors
   - Task ID: T020
   - Depends on: T008, T009, T010, T013, T015
   - Parallel group: G12
   - Risk: high - attachments, credentials, output schema, error/exit handling, and orchestration
   - Owned scope: `src/perplexity_cli/query_runner.py`, `tests/test_query_runner.py` and capability-specific split files from T001
   - Not in scope: API/upload/formatting implementations, live query, private protocol declaration exclusions already owned by T006
   - Spike candidate: T005 must refresh the stale historical 161 survivors against current tests; do not assign old individual keys before that refresh.
   - Actions: First implement T006-assigned query timeout/no-tests repairs and any approved exact Protocol declaration exclusions. Prove stdin/context/environment handling, style/final query, request overrides, attachment detection/auth/upload, API dispatch/model/search options, rendering/JSON envelope/trace, error and keyboard/broken-pipe exits, and redacted debug context.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T020` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T020` and `make mutation-task-tests TASK=T020`; no real files/network/config; independent security/interface review.
   - Acceptance evidence: Refreshed key ledger, credential/output/error contracts, report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Exclusive ownership of query test files for the task. Commit input/attachment/output/error/orchestration clusters separately.

21. [pending] Close remaining CLI, output, help, command, and presentation survivors
   - Task ID: T021
   - Depends on: T012, T016, T017, T018, T019, T020
   - Parallel group: G13
   - Risk: standard
   - Owned scope: exact T021 source/test/pattern/key manifest frozen by T005; 27 modules in the exhaustive ledger; dedicated test paths fixed before dispatch
   - Not in scope: underlying runners/services, exact terminal decoration, changing public JSON/NDJSON/help schemas
   - Spike candidate: Reconcile the historical 162 survivors and establish dedicated owners for command context and runner adapters.
   - Actions: Prove composition wiring, command registration/context conversion, help/schema content, adapter forwarding, envelope/NDJSON machine contracts, exit/error semantics, and packaged skill loading; use semantic presentation assertions where output is human-only.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T021` exits 0 with the validated amended current keyset, complete baseline dispositions, and a clean report.
   - Validation: `make mutation-task-static TASK=T021` and `make mutation-task-tests TASK=T021`; package contract where relevant; maintainability review.
   - Acceptance evidence: Pattern/key ledger, machine-vs-human output classification, clean report hash/runtime, review verdict.
   - Repair attempts: 0
   - Recovery note: Freeze non-overlapping CLI/commands, machine-output, and help/presentation source/test submanifests before parallel dispatch; otherwise execute serially.

22. [pending] Prove local full-tree closure twice and complete the plan
   - Task ID: T022
   - Depends on: T007, T008, T009, T010, T011, T012, T013, T014, T015, T016, T017, T018, T019, T020, T021
   - Parallel group: G14
   - Risk: high - final quality claim and two long-running authoritative evidence runs
   - Owned scope: two independent isolated `/tmp/opencode` sandboxes, ignored reports/artifacts, primary controller's Control/Journal/Completion Review updates
   - Not in scope: remote push/workflow dispatch, new remediation during evidence capture, metadata reuse, publishing/releasing
   - Spike candidate: Verify the same pre-provisioned read-only environment identity and runtime/storage budgets for both sandboxes before run 1; mismatch or missing environment blocks before mutation starts.
   - Actions: Freeze accepted candidate SHA; export it independently twice; assert no `mutants` path in either; run two serial cache-free canonical full policies through the controlled inner timeout; compare provenance, independently generated keyset, normalised results, and environment identities; run final conventional gate; obtain independent review; complete locally when all evidence passes.
   - Acceptance signal: `UV_OFFLINE=1 npm_config_offline=true make mutation-final-policy CANDIDATE_SHA='<40-hex>'` exits 0; this target owns both full runs and final `ci-conventional` without permitting a patch between runs.
   - Validation: Both reports are non-empty, schema-valid, complete and identical by generated-keyset/result/environment digests; zero survived/timeout/suspicious/no-tests/skipped/not-checked; protected state unchanged; each run finishes within 19,800 seconds plus bounded reporting.
   - Acceptance evidence: Candidate SHA/tree/lock, both path-independent environment manifests, exact commands/exits/runtimes, report/generated-keyset/result hashes, final conventional output, protected-state comparison, independent review.
   - Repair attempts: 0
   - Recovery note: Any finding routes back to its sole owning task and invalidates both final-run proofs. Never patch between run 1 and run 2; restart both from a new candidate SHA.

## Optional Remote Follow-Up
RF001 is not a completion task and has no dependency edge into T022. After local completion, a separately authorised invocation may push the accepted revision, dispatch the scheduled mutation workflow, watch it, validate mandatory artefacts, and append a remote-corroboration addendum. Failure or absence of RF001 does not revoke local completion; any differing remote result opens new repair work against the recorded candidate.

## Verification Strategy
| Tier | When | Exact command | Required result |
|---|---|---|---|
| 0 | T005 and before dispatch | `UV_OFFLINE=1 npm_config_offline=true make mutation-manifest-check` | All 105 modules and every generated key owned exactly once; no spill, gap, duplicate, missing path, or digest mismatch |
| 1 | After each edit | `UV_OFFLINE=1 npm_config_offline=true make mutation-task-static TASK=T0XX` | Owned-file Ruff format/check, strict typing where applicable, CC <= 5, test-file cap, suppression and schema checks pass |
| 2 | Before mutant work | `UV_OFFLINE=1 npm_config_offline=true make mutation-task-tests TASK=T0XX` | Literal frozen ordinary tests pass with no live/manual/property/fuzz selection |
| 3 | Per executable key | `UV_OFFLINE=1 npm_config_offline=true make mutate-key TASK=T0XX MUTANT='<exact-key>'` | Key belongs to manifest; pre-repair distinction is reproduced where required; post-repair result is killed in fresh isolated state; every historical timeout records three consecutive serial post-repair kills in separate trees |
| 4 | Task closure | `UV_OFFLINE=1 npm_config_offline=true make mutate-task-policy TASK=T0XX` | Valid amendment chain and current expected keyset; every baseline key accounted for; complete schema-valid clean report; no selected actionable/no-tests/skipped/not-checked state |
| 5 | Dependency-wave boundary | `UV_OFFLINE=1 npm_config_offline=true make mutation-wave-policy TASKS='<frozen task IDs>' && UV_OFFLINE=1 npm_config_offline=true make ci-conventional` | Manifest union exact and clean; ordinary repository gate green |
| 6 | Full baseline | `UV_OFFLINE=1 npm_config_offline=true make mutation-baseline CANDIDATE_SHA='<40-hex>'` | Fresh full generated keyspace reconciles with primary manifests; expected findings are authoritative, no unowned key |
| 7 | Final closure | `UV_OFFLINE=1 npm_config_offline=true make mutation-final-policy CANDIDATE_SHA='<40-hex>'` | Two independent clean full runs plus conventional gate from one unchanged candidate |

Tiers are cumulative; a higher-tier pass cannot override a lower-tier failure. Tier 3 never substitutes for Tier 4. T006 additionally requires clean associated tests 5/5 and exact timeout mutant outcomes 3/3 before classification. Wave task lists are frozen in the Progress Journal before execution. Independent ordinary checks may run concurrently, but mutation processes never share metadata/sandboxes. Pinned uvx tools need a warm offline cache for `ci-conventional`; cache warming is not mutation evidence. Xdist validations must not compete for one temp root. Final review covers public behaviour, security, maintainability, dispositions, no live access, and provenance before COMPLETE.

## Risks And Recovery
- **False clean from stale/partial metadata (high):** T002-T005 add completeness/provenance and require missing `mutants/`. Recovery is a fresh sandbox from the same immutable SHA.
- **Equivalent mutants drive brittle tests (high):** require external behaviour mapping and independent review. Prefer production simplification; exclusions remain limited to user-authorised non-executable abstract/Protocol declarations, never equivalent behavioural code.
- **Timeouts mask hangs or test flakiness (high):** serial repetition and clean-test timing separate semantic non-termination from harness noise.
- **Test suite becomes unmaintainable (high):** split >1,000-line files, CC <= 5, public contracts first, per-wave growth/runtime review, remove duplicates.
- **Credential/network exposure (high):** sanitised environment, no credentials/live variables, repository network guard, temp-only config/files, no live/manual tests.
- **Long runs interrupted (standard):** remediation checkpoints are per module; full evidence runs restart from immutable SHA rather than trusting partial results.
- **Concurrent metadata corruption (standard):** each mutation worker owns a unique sandbox; final runs are serial.
- **Policy/schema/workflow drift (standard):** producer/schema/fixtures/workflow/docs change in dependency order with contract tests.
- **Unexpected user edits during build (standard):** csm-build records hashes at every checkpoint, never resets unrelated changes, and stops on direct conflict.
- **Optional remote corroboration unavailable (standard):** this does not block or qualify local completion. Record the accepted candidate SHA and omit RF001 until separately authorised.

Rollback and forward recovery:
- Each task commits only its owned source/tests and plan checkpoint.
- A failing survivor wave is reverted or repaired independently; accepted earlier clean reports remain advisory until T022.
- Policy/tooling tasks are landed before remediation; if they regress, repair the tooling rather than bypassing it with raw Mutmut output.
- Any change after final run 1 invalidates final evidence; create a new candidate and restart both runs.

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| F01 Full-tree ownership not proven | high | Added exhaustive 105-module primary ledger; T005 blocks on any module/key gap, duplicate, spill or union mismatch | Design source ledger; AC4 |
| F02 Acceptance signals not runnable | high | Added manifest-driven Make commands and exact Tier 0-7 matrix; all broad tasks use `mutate-task-policy TASK=...` | Tasks T005-T022; Verification Strategy |
| F03 Dirty test checkpoint unsafe | high | T001 now requires intake hashes, external patch backup, enumerated staging, preflight hooks, post-hook staged review and commit blob verification | T001 |
| F04 Existing brittle/private tests not semantically reviewed | high | Added durable review ledger with public-boundary/exactness rationale and independent disposition for every candidate assertion | T001 scope/actions/acceptance |
| F05 Exclusion authority invented | high | User explicitly authorised only exact non-executable abstract/Protocol exclusions; added strict eligibility and durable manifest | A005; T006; constraints |
| F06 Blocking policy lacked authority | high | User explicitly selected fail-closed enforcement for every mutation lane | A004; T002-T004 |
| F07 Raw skipped could conceal debt | high | Raw skipped remains distinct, makes evidence incomplete/tool-error, and is zero at final acceptance | AC2/AC7; outcome matrix |
| F08 Completeness was circular | high | Generated key multiset is independently enumerated from generated Python AST and compared with raw results | Evidence model; T002 |
| F09 Wheel identity incomplete | high | Added lock, full Python/platform, uv, installed inventory, verified Mutmut RECORD, and locked wheel digest identity | AC7; evidence model; T003 |
| F10 Hard timeout could lose reports | high | Added deadline-derived process-group inner bounds (at most 19,800/2,100 seconds), TERM/KILL grace, 120-second report deadline and publication reserves | T003/T004; requirements |
| F11 Offline environment under-specified | high | Authoritative runs use a pre-provisioned verified read-only environment with no in-run sync/install/fallback; mismatch blocks | T005/T022 |
| F12 Runner cleanup was destructive | high | Runner refuses any existing `mutants` path and has no cleanup/force capability | Design; T003 |
| F13 Parallel ownership vague | standard | T005 freezes literal source/test/pattern/key manifests; broad tasks require non-overlapping internal submanifests or serial work | Design; recovery notes |
| F14 Risk arithmetic wrong | standard | Corrected to 15 high/7 standard and added omitted T011 review | How To Execute |
| F15 Local and remote completion conflated | standard | User chose local proof; T022 is local-only and RF001 is optional | A011; T022; Optional Remote Follow-Up |
| F16 R&D evidence not durable | standard | Downgraded retained counts to planning observations; T005/T022 require durable commands/hashes/counts in journal | Current Evidence; R&D; task evidence |
| F17 Validation not executable | standard | Added cumulative exact command matrix and per-task static/test/mutation targets | Verification Strategy; tasks |
| F18 Critical path unsupported | low | Replaced with dependency spine and representative dependency-depth chains | Execution Graph |
| F19 Frozen manifests could not survive source remediation | blocker | Baselines are immutable; primary task/controller add reviewed append-only old/new key amendments and validate the current partition after every source change | Burn-down model; Tier 4 |
| F20 Baseline/triage commands lacked owner | major | T003 now explicitly owns and contract-tests every Make target consumed by T005-T022 | T003 actions/validation |
| F21 Timeout closure lacked three post-repair kills | major | Timeout overlay remains open until the primary task records three consecutive serial post-repair kills in separate trees | Timeout model; Tier 3 |
| F22 Generated-key matcher could include originals | major | Strict numeric grammar rejects originals/trampolines/aliases and cross-checks generated dictionaries with real Mutmut 3.5 fixtures | Evidence model; T002 |
| F23 Installed Mutmut digest trusted RECORD text | major | Hash every actual installed file against RECORD, reject missing/extra/mismatch, then digest verified actual bytes | Evidence model; T003 |
| F24 Selected timeout left weak publication margin | major | Reduced request to 2,100 seconds and made runner derive budget from outer deadline with explicit report/publication reserves | Requirements; T003/T004 |
| F25 Exclusion authority ambiguous | major | A005 explicitly grants blanket authority only when every exact mechanical proof/manifest/review condition passes | A005 |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---|---|---|---|---|
| 2026-08-15 | 0 | INTAKE | - | User selected mutation-only scope; planning depth classified large/open | DISCOVER |
| 2026-08-15 | 0 | DISCOVER | - | Protected dirty-worktree baseline captured; uncertainty scout found stale selected aggregate, 40 hidden no-tests, ambiguous denominator | RESEARCH |
| 2026-08-15 | 0 | RESEARCH | - | Five parallel tracks audited cache semantics, survivor clusters, timeouts/no-tests, test maintainability, policy/CI; addendum classified 1,374 outside-group actionable records | DRAFT |
| 2026-08-15 | 0 | DRAFT | - | 22-task evidence-first full-tree closure draft produced | CRITIQUE |
| 2026-08-15 | 0 | CRITIQUE | - | Independent critic found 12 high, 5 standard and 1 low build-readiness issues | REMEDIATE |
| 2026-08-15 | 0 | REMEDIATE | - | User authorised narrow structural exclusions and fail-closed lanes; local proof chosen for completion. Four remediation tracks supplied ownership, evidence, checkpoint and governance corrections | VERIFY |
| 2026-08-15 | 0 | CRITIQUE | - | Second independent review reopened manifest amendment semantics and found six major execution details | REMEDIATE |
| 2026-08-15 | 0 | REMEDIATE | - | Added append-only manifest amendments, complete target ownership, post-repair timeout proof, strict generated-key grammar, actual-file environment verification, deadline reserves and blanket exclusion authority | VERIFY |
| 2026-08-15 | 0 | VERIFY | - | Primary gate checked goal coverage, 22 runnable acceptance signals, 105-module ownership, dependencies, recovery, safety and user decisions; final independent verifier returned READY | SAVED |
| 2026-08-15 | 0 | SAVED | - | Plan saved with all implementation tasks pending; no implementation started | STOP |
| 2026-08-15 | 0 | NOT_STARTED -> RECOVER | T001, T002 | User explicitly invoked csm-build; execution begins from committed plan `04b8f0e` | VALIDATE |
| 2026-08-15 | 0 | RECOVER -> VALIDATE | T001, T002 | Protected patch hash matches planning evidence; index clean; no untracked/Mutmut/BDD artefacts; authentic current NORMS loaded; plan journal is the only expected controller edit | SELECT |
| 2026-08-15 | 0 | VALIDATE -> SELECT | T001, T002 | Ruff/format/Pyright pass; 556 focused tests pass in 8.71s; T001 split candidates confirmed at 1,127 and 1,036 lines | DISPATCH |
| 2026-08-15 | 0 | SELECT -> DISPATCH | T001, T002 | Independent write scopes frozen; external T001 recovery package and original file copies verified | INTEGRATE |
| 2026-08-15 | 0 | DISPATCH -> INTEGRATE | T001, T002 | Both implementations returned focused green evidence; T001 full gate exposed T002 nosec ratchet entries at mutation_policy.py:9,483 | VERIFY |
| 2026-08-15 | 0 | INTEGRATE -> VERIFY | T001, T002 | Actual diffs inspected; split tests and 90-row ledger present; policy/schema/evidence contracts integrated; suppression comments repaired with owner/reason | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REPAIR | T002 | Focused 569 pass; full CI stopped at quality ratchet because two existing nosec identities moved lines without count growth | VERIFY |
| 2026-08-15 | 0 | REPAIR -> VERIFY | T002 | Suppression baseline refreshed with no count growth (94 identities); ratchet and reason enforcement pass | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REVIEW | T001, T002 | 569 focused tests and full ci-conventional pass; independent correctness, security/test-quality and integration reviews dispatched | REPAIR or CHECKPOINT |
| 2026-08-15 | 0 | REVIEW -> REPAIR | T001, T002 | Valid findings: T001 ledger self-attestation/omissions, CC violations, prose/security/cancellation weaknesses; T002 wrong real path prefix and CLI args, broken direct script, weak provenance/arithmetic/exclusion validation | VERIFY |
| 2026-08-15 | 0 | REPAIR -> INTEGRATE | T001, T002 | T001 reports 108 reviewed candidates/521-node bijection/CC<=5; T002 reports 84 tests, real layout reconciliation, direct CLI and fail-closed evidence repairs | VERIFY |
| 2026-08-15 | 0 | INTEGRATE -> VERIFY | T001, T002 | Primary added omitted fixtures, made evidence tests checkout-portable, verified direct CLI import pattern, and reconciled suppression baseline at 95 identities | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REPAIR | T002 | 615 focused pass; full CI stopped after 3,123 passes on boolean-flag-argument findings at mutation_evidence.py:407/421 and mutation_policy.py:479; fresh-eyes diagnosis required after attempt 2 | VERIFY |
| 2026-08-15 | 0 | REPAIR -> VERIFY | T002 | Fresh-eyes diagnosis applied: declaration-kind value replaces protocol flag; callable invariant replaces boolean condition parameter; Semgrep/84 T002/10 evidence tests pass | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REVIEW | T001, T002 | 615 focused and full conventional CI pass after fresh-eyes repair; post-repair independent reviews dispatched | REPAIR or CHECKPOINT |
| 2026-08-15 | 0 | REVIEW -> REPAIR | T001, T002 | Valid findings: duplicate evidence crashes report publication; suffix matching spoofs exclusions; OAuth waiter not proven queued; one redaction value and one full render string remain brittle | VERIFY |
| 2026-08-15 | 0 | REPAIR -> INTEGRATE | T001, T002 | T001: 108 specific rows, durable independent artifact, 521 behavioural pass; T002: 92 focused pass, duplicate reports serialise, exact alias/shadow checks and count invariants enforced | VERIFY |
| 2026-08-15 | 0 | INTEGRATE -> VERIFY | T001, T002 | Primary inspected final artifacts; 92 T002/14 T001 evidence tests and Semgrep pass; suppression line movement reconciled at 95 identities | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REVIEW | T001, T002 | Final candidate passes 627 focused tests and full conventional CI; final independent acceptance review dispatched | CHECKPOINT or REPAIR |
| 2026-08-15 | 0 | REVIEW -> REPAIR | T002 | T001 READY; T002 rejected because compound imports can hide alias shadowing and globally reconciled dictionaries can swap ownership | VERIFY |
| 2026-08-15 | 0 | REPAIR -> VERIFY | T002 | Compound import shadow and swapped dictionary regressions added; 94 T002 tests, Pyright and zero-finding Semgrep pass | REVIEW |
| 2026-08-15 | 0 | VERIFY -> REVIEW | T002 | 94 T002 tests and full conventional CI pass after final structural repairs; narrow final review dispatched | CHECKPOINT or REPAIR |
| 2026-08-15 | 0 | REVIEW -> CHECKPOINT | T001 | Final independent verdict READY; protected test wave, 108-row review, durable review artifact and 521-node map selected for isolated checkpoint commit | CHECKPOINT T002 |
| 2026-08-15 | 0 | CHECKPOINT | T001 | Commit `3dd4e3a4b7feec7df87d7fd55cf74d4476872767`, tree `934dd78e0dafa60fbbde808b29a00046728d1a8d`; committed patch hash equals reviewed post-hook hash `0f661aa111d71ccec2abad8da5667eb4fb8a3aa73e58fdb7a517c775b499495c` | CHECKPOINT T002 |
| 2026-08-15 | 0 | REVIEW -> CHECKPOINT | T002 | Final narrow review READY; 94 focused tests and full conventional gate pass; isolated policy/schema/evidence checkpoint selected | SELECT T003 |
| 2026-08-15 | 0 | CHECKPOINT | T002 | Commit `40fb64babc9ce176011dc18391b54a455cedd2ee`, tree `fd36067c9ef995778d313d619323f215f9240382`; committed patch hash equals reviewed post-hook hash `d81134ce98a25223ceaf24ef210ec142eb08f2b8a878313e7758ca04cf689329` | SELECT T003 |
| 2026-08-15 | 1 | CHECKPOINT -> SELECT | T003 | T001/T002 committed and worktree clean; canonical runner is dependency-ready; review-discovered meta-test ignores added to T003 ownership and acceptance | DISPATCH |
| 2026-08-15 | 1 | SELECT -> DISPATCH | T003 | Acceptance signal present; isolated R&D probes selected for exact Mutmut patterns, installed-file identity, deadlines/process groups and current Make-policy contracts | DISPATCH implementation |

## Completion Review
Filled by csm-build only after all acceptance criteria have observed evidence.
