# Quality Gates Human And Agent Replication Guide CSM Plan

## Control
- Plan ID: `quality-gates-replication-guide-2026-07-31`
- Status: complete
- Current CSM state: COMPLETE
- Cycle: 2
- Last checkpoint: 2026-07-31T23:35:00Z - final gate passed: 4548 tests, make check, actionlint, Pyright, analyser/property/OpenCode/suppression gates all green; review findings repaired
- Next transition: none (complete)
- Active tasks: none
- Blockers: none

## Goal
Rewrite `QUALITY_GATES.md` as one progressive-disclosure reference that serves two audiences:

1. Humans must be able to find the safe command for a task, understand what runs and why, and distinguish local feedback from authoritative CI or release enforcement.
2. Agents must be able to reconstruct the gates faithfully from stable identifiers, field-level authorities, exact commands, trigger and orchestration rules, outcome semantics, requirements, side effects, outputs, and acceptance checks.

The work also remediates the related drift that prevents the guide from remaining truthful:

- stale `QUALITY_GATES.md` assertions in `tests/test_help_doc_drift.py`;
- the stale, production-unvalidated analyser-contract registry;
- the stale property-test inventory and count-floor policy;
- unused mutation waivers, incompatible mutation schema, and stale tracked report;
- misleading source comments and conflicting quality sections in `README.md` and `CONTRIBUTING.md`;
- insufficient semantic drift tests for hooks, Make composites, workflows, plugins, profiles, and report paths.

Constraints:

- Preserve executable gate policy unless an exception is explicitly listed below.
- Do not change thresholds, check toggles, analyser commands, hook or workflow job topology, credential guards, or existing outcome classifications.
- The only planned new blocking edges are metadata-integrity checks:
  - production analyser-contract validation becomes part of the existing `make analyser-contract-tests` CI step;
  - exact property-manifest validation becomes a prerequisite of each property Make target and therefore blocks direct, pre-push, CI, and release property lanes.
- Relocating the generated full-mutation report is behaviour-preserving with respect to mutation classification and exit codes.
- Do not activate mutation waivers or infer human approval for placeholder entries.
- Do not rewrite historical `.agents/plans/**` or historical remediation/evidence records unless a live consumer explicitly requires a path correction.
- Do not claim knowledge of branch-protection required checks, GitHub Environment protections, or other server-side settings absent from the repository.
- Do not implement any task during this planning invocation.

## Acceptance Criteria
1. `QUALITY_GATES.md` begins with a concise human guide covering common change types, safe commands, setup, prerequisites, side effects, credentials, and expected gate phases.
2. `QUALITY_GATES.md` contains an agent replication reference covering every first-party OpenCode plugin, inline hook guard/fixer, Make-owned atomic gate and relevant composite, test lane and test-enforced meta-gate, CI job, scheduled job, release job, and artefact edge.
3. Every replication card has a unique stable ID and non-empty fields for authority, invocation, trigger/scope, execution context, contextual enforcement, skip/failure semantics, dependencies/order/concurrency/stdin, inputs/configuration, outputs/evidence, requirements, side effects, and verification.
4. The guide accurately describes the five-stage pre-commit pipeline and staged pre-push pipeline, including nested parallel groups, fixer order, post-fix checks, partial-staging guard, sole stdin ownership, and direct versus Make-delegated commands.
5. The guide accurately describes `MAX_FLAGGED = 30`, all current `CHECK_* = true` values, the missing suppression-reason toggle, unconditional `module-coverage`, six ratchet members, effective threshold authorities, and command-line override limitations.
6. The guide accurately describes current coupling, architecture-baseline, file-size, suppression, Gitleaks, Safety, fuzz, Hypothesis, coverage, mutation, package, smoke, and schema-drift semantics without preserving obsolete filters or stale metrics.
7. The guide inventories every current CI job and correctly distinguishes universal, push-only, PR-only, scheduled, local-only, session-only, on-demand, and release contexts; it does not claim local `make ci` and workflow CI are equivalent.
8. Scheduled concurrency, SARIF/artefact behaviour, mutation policy status, release publishing, Release Drafter, and action pinning are accurately represented.
9. OpenCode documentation describes exactly three registered plugins as session controls, their real hooks and limitations, `opencode-check`, `opencode-audit`, configuration-check scope, permission scope, tests, and known gaps without calling them repository lifecycle gates.
10. Mutable observations such as mutation counts, mutation score, and timings are absent from normative gate descriptions or are explicitly historical with provenance; live generated evidence is not tracked as current policy.
11. `quality/analyser-contracts.toml` remains schema version 1 but is explicitly a curated process-outcome registry rather than an exhaustive wiring inventory; stale descriptions are corrected and production `--validate` proves its declared Make targets and test references exist without running analysers.
12. `quality/property-inventory.toml` is a live exact manifest for the independently Make-declared property source files; discovered and inventoried canonical IDs have bidirectional parity without a hard-coded count, commit SHA, date, or stale statistics.
13. Mutation has one live schema, no active or placeholder waiver catalogue, no stale tracked generated report, and one agreed `build/reports/mutation-report.json` path across Make, workflow summary/upload, tests, and documentation; mutation status mapping and exits remain unchanged.
14. Semantic documentation tests compare the guide with exact threshold/toggle values, hook topology, selected Make composite membership, all workflow/job/trigger/schedule/artefact sets, plugin registration, property profiles/lanes, mutation paths, gate-card fields, and ID uniqueness.
15. `README.md`, `CONTRIBUTING.md`, audited source comments, and schema-drift rationale no longer contradict the guide; `make test` is the documented safe ordinary test command.
16. Targeted documentation/configuration/analyser/property/mutation/OpenCode tests, `make actionlint`, `make test-property`, `make test-coverage` followed by `make check`, and `make test` pass with exact evidence. A check unavailable locally is not a pass and may be replaced only by evidence from the exact resulting revision.
17. A policy-preservation review proves no unplanned changes to thresholds, toggles, hook/workflow job topology, analyser command lines, Safety credential conditions, Gitleaks required-version behaviour, or mutation classification/exit mapping.
18. Only planned files are changed; generated caches/reports/build outputs remain ignored and no full mutation, release, push, workflow dispatch, authenticated Safety, real API, manual, or real-user-config operation is run for verification.

## Current-State Evidence
- `QUALITY_GATES.md:19-25,165-169` describes three pre-commit stages; `lefthook.yml:1-18,28-239` defines five, including partial-staging rejection and post-fix revalidation.
- `QUALITY_GATES.md:280-283` calls pre-push parallel; `lefthook.yml:241-302` defines a piped sequence with bounded parallel groups and one stdin consumer.
- `QUALITY_GATES.md:123` records `MAX_FLAGGED = 10`; `quality/gates.conf:16-17` sets 30.
- `QUALITY_GATES.md:136-138,550` says heavy `make check` gates are off; `quality/gates.conf:50-62` sets every current toggle true and includes undocumented `CHECK_SUPPRESSION_REASONS`.
- `Makefile:454-498` conditionally builds `check` from those toggles and adds `module-coverage` unconditionally.
- `QUALITY_GATES.md:355-367` describes five ratchet members; `Makefile:534-566` has six, adding `suppression-reasons`.
- `QUALITY_GATES.md:339-351` describes four coupling filters; `scripts/check_coupling.py:217-259` includes function-local imports and explicitly performs no leaf/sibling filtering.
- `scripts/check_architecture.py:651-682,883-897` applies `.architecture-baseline.json` by default despite stale `Makefile:244` wording.
- `scripts/check_file_size.py:1-12,97-111` is baseline-aware despite stale `Makefile:536` wording.
- `QUALITY_GATES.md:326-331` says missing Gitleaks skips; `scripts/gitleaks_check.sh:12-33,247-285` requires exactly 8.30.1 and fails closed.
- `Makefile:319-326` owns ordinary/coverage marker exclusions, while `pyproject.toml:142-158` only registers markers and strictness; current documentation attributes exclusions to `addopts` and uses the wrong integration marker.
- `tests/conftest.py:48-79` gives every Hypothesis profile a 500 ms deadline; `QUALITY_GATES.md:393-401` says three have no deadline.
- `.github/workflows/ci.yml:17-373` has fourteen jobs, including omitted `pip-audit`, PR `diff-coverage`, and PR `mutation-diff` jobs.
- `.github/workflows/ci.yml:147-167` makes fuzz blocking; `QUALITY_GATES.md:420,554` says it is `continue-on-error` and non-authoritative.
- `.github/workflows/ci.yml:253-276` makes Safety push-only; `QUALITY_GATES.md:424,440-443` claims selected same-repository PR coverage.
- `Makefile:526` and `.github/workflows/ci.yml` differ: local `make ci` includes Sonar reports, while workflow CI adds event/platform-specific jobs and omits Sonar.
- Scheduled workflow concurrency at `mutation-scheduled.yml:11-13`, `scorecard.yml:11-13`, and `semgrep-advisory.yml:11-13` is the reverse of `QUALITY_GATES.md:456-460`.
- `opencode.jsonc:27-31` registers three plugins; their actual events are implemented at `.opencode/plugins/quality-gate.ts:257-330`, `.opencode/plugins/pxcli-quality.ts:531-638`, and `.opencode/plugins/pre-push-docs-check.ts:48-93`.
- `.opencode/package.json:3-9` makes `opencode-check` run ESLint, Vitest, TypeScript, and config checks; `Makefile:95-106` defines a separate high/critical npm audit.
- `tests/test_help_doc_drift.py:389-392,404-411` requires stale Gitleaks-skip and three-ratchet wording.
- `quality/analyser-contracts.toml:287-347` uses `pending` descriptions that imply operational gates are not integrated; `Makefile`, Lefthook, and workflows prove Gitleaks, module coverage, and mutation are operational outside the contract runner.
- `Makefile:511-512` runs only analyser-contract unit tests; it does not validate the production TOML.
- Static research observed 63 `@given` definitions in `tests/test_property.py`, 65 inventory `node_id` entries, and `quality/property-inventory.toml:718` claiming 59. The implementation must rediscover IDs rather than enforce 63.
- `tests/test_property_policy.py:278-301` uses a hard-coded minimum of 60 rather than exact inventory parity.
- `quality/mutation-waivers.toml` has placeholder reviewers and no live consumer; `scripts/mutation_policy.py:59-81,237-267` treats all survived/timeout/suspicious mutants as actionable.
- `quality/schemas/mutation-report.json` matches `scripts/mutation_policy.py`; `quality/schemas/mutation-report-v1.json` describes an incompatible, unreferenced waiver-era shape.
- `quality/evidence/mutation-report.json` differs from the counts embedded in `QUALITY_GATES.md` and lacks source SHA/timestamp provenance.
- `Makefile:276-279` and `.github/workflows/mutation-scheduled.yml:41-78` can expose that tracked stale report when a new run fails before report generation.
- Baseline `GIT_OPTIONAL_LOCKS=0 git status --short` was empty before and after planning research.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|---|---|---|---|---|
| A001 | Current executable behaviour wins when prose or comments disagree. | Decision | The request is to document and replicate the gates that exist, not silently redesign them. | Accepted |
| A002 | Authority is field-specific rather than assigned wholesale to one file. | Decision | Hooks, Make, tool config, workflows, wrappers, and schemas control different fields. | Accepted |
| A003 | `QUALITY_GATES.md` remains descriptive Markdown, not an executable policy manifest. | Decision | Agents can read structured cards; executable sources and semantic tests remain authoritative. | Accepted |
| A004 | The guide has a human layer followed by an agent replication layer. | Design | Progressive disclosure prevents exhaustive replication detail from obscuring normal workflows. | Accepted |
| A005 | Card IDs derive from authority locators. | Design | Readable deterministic namespaces make cards useful to agents and straightforward to validate. | Accepted |
| A006 | Enforcement is contextual, never one global `blocking` Boolean. | Decision | A command can block a hook, fail a job, or remain session-advisory; branch protection is unknown. | Accepted |
| A007 | Mutable quality observations are not normative. | Decision | Current mutation evidence already demonstrates manual-count drift. | Accepted |
| A008 | Analyser contracts remain schema v1 and curated, not exhaustive. | Decision | A universal analyser registry would require ambiguous eligibility rules and duplicate the complete guide. | Accepted |
| A009 | `pending` in analyser contracts means pending contract-runner activation, not pending repository wiring. | Decision | This preserves runner selection while correcting misleading descriptions. | Accepted |
| A010 | `typecheck-scripts` and `suppression-reasons` are added to the curated registry with explicit process contracts. | Decision | Both are canonical evaluator targets omitted from the current registry. | Accepted |
| A011 | Property source scope is independently declared by `PROPERTY_TEST_FILES` in Make. | Decision | The manifest must not be able to shrink its own discovery universe. | Accepted |
| A012 | The current count of 63 properties is evidence only. | Decision | Exact IDs, not counts, are the durable policy. | Accepted |
| A013 | Property policy becomes a named prerequisite of all property targets. | Intentional policy edge | This ensures direct, pre-push, CI, and release property lanes cannot bypass manifest parity. | Accepted |
| A014 | Analyser production validation blocks only the existing analyser-contract test step. | Intentional policy edge | It makes the existing CI claim truthful without adding analyser execution or rewiring other gates. | Accepted |
| A015 | Mutation waivers and the obsolete schema are deleted rather than archived in-tree or activated. | Decision | They are unused and placeholder-reviewed; Git history is sufficient archival evidence. | Accepted |
| A016 | The live mutation schema is not tightened in this work. | Decision | Tightening is a compatibility change unrelated to documentation drift. | Accepted |
| A017 | The generated mutation report moves under ignored `build/reports/`. | Decision | This prevents checkout-era evidence from masquerading as current scheduled output. | Accepted |
| A018 | OpenCode test expansion is limited to characterising the currently untested push-reminder plugin. | Scope | Existing helper/parser tests cover the other two plugins; remaining gaps are documented honestly. | Accepted |
| A019 | A new focused documentation test module is justified. | Design | Complete quality-guide cross-source validation is separable from CLI help drift checks. | Accepted |
| A020 | The new documentation test is excluded from Mutmut infrastructure collection. | Decision | It replaces quality-guide assertions already excluded through `test_help_doc_drift.py`. | Accepted |
| A021 | Broad `make ci`, npm audit, and live OpenCode resolution are supplemental, capability-dependent evidence. | Decision | They can require network/tools and are not necessary to prove a documentation-only topology description. | Accepted |
| A022 | CI evidence substitutes for unavailable local evidence only at the exact resulting revision. | Decision | Prior-revision green CI cannot validate uncommitted changes. | Accepted |
| A023 | Newly discovered documentation/comment/test drift is recorded in this plan journal and assigned before fixing. | Process | Keeps the final human guide free of historical remediation clutter while preserving resumability. | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|---|---|---|---|---|---|
| R001 | Is `QUALITY_GATES.md` current? | Parallel read-only audits of hooks/Make, CI, OpenCode, analysers/tests | Read/Glob/Grep only; no writes or execution | Material drift exists across all requested surfaces. | Seeded the drift ledger and acceptance criteria. |
| R002 | What uncertainties could invalidate the plan? | Dedicated uncertainty scout | Read-only; no Git or executable tools | Main risks were authority conflicts, ambiguous inventories, stale generated evidence, and hidden behaviour changes. | Adopted field-level authority and behaviour-preservation constraints. |
| R003 | What document form serves humans and agents? | Read current guide and executable sources | Read-only | Human runbooks and exhaustive cards require two layers; side effects and outcome states must be first-class. | Defined guide architecture and card schema. |
| R004 | What is the exact executable topology? | Static inspection of Make, Lefthook, workflows, tool config | Read-only | Five commit stages, staged pre-push, fourteen CI jobs, and non-equivalent local/workflow CI. | Defined exact topology tests and phase runbooks. |
| R005 | How should analyser-contract drift be fixed? | Inspect TOML, checker, tests, Make and CI | Read-only | Production TOML is not validated; broad schema-v2 designs introduce ambiguous scope. | Keep schema v1, curate scope, add repository-aware `--validate`. |
| R006 | How should property drift be fixed? | Inspect inventory, AST policy, Make and CI selectors | Read-only; one separate `rg --count` read found 63 source decorators | Inventory has stale IDs/counts and controls no exact parity. | Make source scope independent and enforce exact canonical IDs. |
| R007 | How should mutation drift be fixed? | Trace schemas, policy, evidence, waivers, Make and workflows | Read-only | Waivers/old schema are unused; tracked report can be uploaded stale. | Delete dead policy artefacts and move generated report. |
| R008 | Which tests/comments preserve drift? | Audit documentation/meta tests and supporting docs | Read-only | Literal assertions preserve false wording; README/CONTRIBUTING and comments also conflict. | Add semantic tests and explicit comment/doc scope. |
| R009 | What must the OpenCode guide contain? | Inspect all first-party OpenCode files | Read-only | Three session-only plugins, four-part npm check, separate audit, limited JSONC validator, untested odd/even reminder. | Add precise session cards and one missing characterisation suite. |
| R010 | Is the first draft executable and safe? | Independent hostile critique | Read-only | Found missing CSM recovery, overbroad registries, self-authorising scopes, incomplete tests, and infeasible verification. | Simplified registries, contextualised enforcement, added preflight/recovery. |
| R011 | Did remediation close critique findings? | Three independent remediation tracks and second independent critique | Read-only | No high findings remained; three medium findings concerned property task ordering, Mutmut exclusion, and stale-revision CI evidence. | Corrected task graph and evidence rules. |
| R012 | Did planning alter protected state? | `GIT_OPTIONAL_LOCKS=0 git status --short` before/after; plan-path Glob | Read-only Git with optional locks disabled | Status was empty both times; target plan path did not exist. | Safe to save only this plan. |

No runtime R&D was necessary. No test, build, formatter, generator, package manager, application, scanner, hook, workflow, network service, credential, or mutating Git command ran during planning.

## Design

### Guide Architecture
`QUALITY_GATES.md` will use progressive disclosure:

1. **Guide Contract**: audience, authority rules, repository-relative paths, normative vocabulary, and explicit non-goals.
2. **Five-Minute Guide**: task-oriented paths for Python, tests, dependencies, workflows, OpenCode, packaging, push, and release changes.
3. **Safety And Setup**: prerequisites, external tools, credentials, network access, write classes, and idempotence.
4. **Lifecycle Map**: session, five pre-commit stages, staged pre-push, workflow CI, scheduled analysis, and release.
5. **Current Policy Values**: thresholds/toggles with source references and semantic drift tests.
6. **Phase Runbooks**: exact ordering, parallelism, triggers, conditions, outputs, and reproduction commands.
7. **Gate Catalogue**: concise summary linking to complete replication cards.
8. **Agent Replication Cards**: exact build specification for each surface.
9. **Composite And Topology Reference**: differences between `make check`, `make ci`, workflow CI, trusted CI, hooks, and agent runner subsets.
10. **Tests And Meta-Gates**: ordinary, coverage, integration, property, fuzz, mutation, and policy-test placement.
11. **Evidence, Baselines, And Schemas**: producer/consumer paths, provenance, refresh procedure, and review requirements.
12. **Change Protocol**: how to add/remove/rename a gate, change a threshold, update a baseline, modify a workflow, or update the guide/tests atomically.
13. **Appendices**: source index, command index, glossary, and historical/non-normative references.

### Field-Level Authority
| Concern | Authority |
|---|---|
| Hook phase, order, groups, globs, staging, stdin | `lefthook.yml` |
| Reusable command and composite prerequisites | `Makefile` |
| Most thresholds and `CHECK_*` toggles | `quality/gates.conf` |
| Global coverage floor and native tool settings | `pyproject.toml` and dedicated tool configs |
| CI/release event, runner, condition, matrix, timeout, permission, `needs`, artefact | `.github/workflows/*.yml` |
| Analyser outcome and fail-closed semantics | Wrapper implementation plus focused tests |
| Evidence shape | The one named live schema plus producer tests |
| Session plugin behaviour | `opencode.jsonc`, `.opencode/plugins/*.ts`, package scripts and tests |
| Human rationale and replication explanation | `QUALITY_GATES.md` |

Conflicts between executable authorities are blockers. Prose and comment conflicts are corrected to match executable behaviour.

### Stable Card IDs
IDs are readable authority locators:

- `session.<plugin-name>`
- `hook.pre-commit.<lefthook-job-name>`
- `hook.pre-push.<lefthook-job-name>`
- `make.<target-name>`
- `ci.<workflow-stem>.<job-id>`
- `automation.<workflow-stem>.<job-id>`
- `release.<workflow-stem>.<job-id>`
- `inline.<stable-surface-slug>`
- `test.<lane-or-policy-name>`

Rules:

- IDs are lowercase dotted identifiers matching `^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$`.
- IDs are unique and are referenced from lifecycle tables and composites.
- Display-name changes do not change an ID.
- An authority-locator rename updates the card and references atomically; an alias is retained only for a documented external consumer.
- Retired IDs are not reused.
- One card may describe context-specific invocations of one semantic gate, but materially different trust boundaries or outcome policies require separate cards.

### Replication Card Fields
Every active card contains:

- **Purpose**
- **Authoritative source** with repository path and locator
- **Canonical invocation** with working directory and relevant environment
- **Trigger and scope** including event/glob/changed-file rules
- **Execution context** including platform/runtime/trust boundary
- **Contextual enforcement** naming exactly what invocation/hook/job/release fails
- **Skip, not-applicable, and tool-error semantics**
- **Inputs and configuration** including threshold/baseline/schema authority
- **Ordering and concurrency** including dependencies, fail-fast mode, and stdin ownership
- **Outputs and evidence** including paths, schemas, retention, and producer/consumer edges
- **Requirements** including tool versions, credentials, and network use
- **Side effects** across workspace/index/Git/cache/temp/network/remote state
- **Replication checks** covering pass, finding, skip, malformed/missing input, and tool-error cases where applicable

`Skipped` is never called `pass`. `Blocking` is always scoped to a caller/event; merge-required status remains unknown unless repository evidence exists.

### Semantic Drift Validation
A focused `tests/test_quality_gates_documentation.py` will parse descriptive structure but will not drive execution. It will validate:

- card ID/field completeness and uniqueness;
- documented threshold/toggle rows against `quality/gates.conf`;
- exact ordered Lefthook stages, nested group modes, leaf names, commands, globs, `stage_fixed`, and sole `use_stdin` consumer;
- selected Make composite prerequisite sets, including `check` expansion for current toggles and unconditional module coverage;
- the exact workflow filename and job-ID sets, policy-relevant triggers, conditions, matrices, permissions, `needs`, timeouts, schedules, and artefact edges;
- registered OpenCode plugin paths and validation/audit separation;
- property profile values and actual lane placement;
- mutation schema/report paths and absence of obsolete live-policy paths;
- inline non-Make guards/fixers and their card associations;
- stale-phrase absence for the known false claims.

Expected structures in tests are cross-source contracts, not an executable alternative to hooks or workflows. Parser helpers receive negative synthetic cases so a parser that silently ignores missing/extra elements cannot pass.

### Related-Drift Policy Decisions
- Analyser contracts remain curated schema-v1 process contracts. Their `status` governs manual runner selection, not hook/CI wiring.
- Property manifest scope comes from Make, while inventory content records exact canonical test-definition IDs.
- Generated mutation evidence belongs under ignored `build/reports/`; live schemas belong under `quality/schemas/`; historical values belong in Git history or explicitly historical evidence.
- The OpenCode push plugin is an alternating in-session reminder: first matching command blocks, second allows and resets, third blocks again. It does not verify documentation review or push success.
- Existing dormant/shadow analyser wrappers and baselines are documented as non-canonical or test-only; deleting or wiring them is outside this plan unless needed to remove a proven live contradiction.

## Drift Ledger
| ID | Discrepancy | Authority/evidence | Planned disposition | Owner | Acceptance check |
|---|---|---|---|---|---|
| D001 | Three documented pre-commit stages versus five actual stages | `QUALITY_GATES.md:19-25`; `lefthook.yml:1-239` | Rewrite lifecycle/runbook/cards | T007 | T008 exact Lefthook test |
| D002 | Pre-push described as globally parallel | `QUALITY_GATES.md:280-283`; `lefthook.yml:241-302` | Document piped stages and nested parallel groups | T007 | T008 exact Lefthook test |
| D003 | Fixer order, initial Ruff, post-fix rerun, and partial-staging guard omitted/misnumbered | `QUALITY_GATES.md:171-276`; `lefthook.yml:39-239` | Correct phase cards | T007 | T008 job/command/order test |
| D004 | `MAX_FLAGGED` 10 versus 30 | `QUALITY_GATES.md:123`; `gates.conf:17` | Correct table and semantic test | T007/T008 | Parsed value equality |
| D005 | Heavy toggles described off; suppression-reasons omitted | `QUALITY_GATES.md:134-153,550`; `gates.conf:50-62` | Correct table/prose | T007/T008 | Exact toggle-set/value equality |
| D006 | `module-coverage` unconditional but undocumented in `make check` | `Makefile:496-498` | Document state dependency and composite member | T007 | Exact composite test |
| D007 | Five ratchets documented versus six | `QUALITY_GATES.md:296,355-367`; `Makefile:534` | Add suppression-reasons and four-plus-two taxonomy | T007 | Composite equality and no stale phrase |
| D008 | Suppression ratchet described as counts and incomplete types | `QUALITY_GATES.md:362-364`; `check_suppressions.py:1-19` | Document identity/config scope | T007 | Card/source-reference review |
| D009 | Coupling filters obsolete and budget stale | `QUALITY_GATES.md:339-351`; `check_coupling.py:217-259`; `gates.conf:17` | Replace with current graph/rule/blocking mode | T006/T007 | Focused source/comment review |
| D010 | Architecture/file-size Make comments contradict baseline-aware implementations | `Makefile:244,536`; analyser scripts | Correct comments and guide | T006/T007 | Comment-only diff plus cards |
| D011 | Gitleaks graceful-skip claim false; duplicate section and wrong hook command | `QUALITY_GATES.md:287,300-331`; `gitleaks_check.sh` | Correct required 8.30.1/direct pre-push semantics | T006/T007 | Stale-phrase/path/command tests |
| D012 | Test marker expression/source wrong | `QUALITY_GATES.md:270-276`; `Makefile:319-326`; `pyproject.toml:142-158` | Make Makefile selector authority explicit | T007 | Documented selector equality |
| D013 | Hypothesis deadlines and CI placement stale | `QUALITY_GATES.md:393-401,568-575`; `conftest.py`; `ci.yml:123-145` | Correct profiles/lanes | T003/T007 | T008 profile/lane test |
| D014 | Fuzz called non-authoritative; platform limitation absent | `QUALITY_GATES.md:420,554`; `ci.yml:147-167`; `pyproject.toml:208` | Mark job blocking and Atheris Linux x86-64 requirement | T007 | Workflow/requirements test |
| D015 | Safety same-repository PR claim false; pip-audit topology incomplete | `QUALITY_GATES.md:424,440-443`; `ci.yml:253-298` | Document push-only Safety and universal audit | T007 | Workflow condition/job tests |
| D016 | CI table omits pip-audit, diff coverage, mutation diff | `QUALITY_GATES.md:413-426`; `ci.yml` | Add all fourteen job cards | T007 | Exact job-set test |
| D017 | Local `make ci` and workflow CI described as equivalent; Sonar/architecture phase labels wrong | `QUALITY_GATES.md:430-446,618-625`; `Makefile:526`; `ci.yml` | Separate local/workflow composites and direct wiring | T007 | Make/workflow card checks |
| D018 | macOS called full pipeline; property profiles overstated | `QUALITY_GATES.md:31,448-452,573-575`; `ci.yml` | Document only compatibility/smoke and Python 3.13 property job | T007 | Workflow/lane tests |
| D019 | Scheduled concurrency and universal SARIF claims false | `QUALITY_GATES.md:454-476`; three workflows | Correct each workflow card | T007 | Exact schedule/concurrency/artefact tests |
| D020 | Scheduled mutation labelled advisory despite policy failure | `mutation-scheduled.yml:35-89`; `mutation_policy.py` | Contextualise blocking producer and always-run reporting | T004/T007 | Workflow/path/status tests |
| D021 | Release flow omits concurrency, skip-existing, release assets; draft promotion overstated | `QUALITY_GATES.md:488-505`; publish/release-drafter workflows | Correct release cards | T007 | Workflow/release test |
| D022 | OpenCode controls overstated and validation/audit/test scope incomplete | `QUALITY_GATES.md:515-529`; OpenCode sources | Correct comments, characterise push plugin, rewrite session section | T005/T007 | npm tests and plugin/card tests |
| D023 | Schema drift described zero-debt rather than ratchet | `QUALITY_GATES.md:533-537`; `test_schema_drift.py:21-82` | Correct rationale/guide | T007 | Documentation assertion |
| D024 | Quick reference omits active/test-only/meta-gate distinctions | `QUALITY_GATES.md:590-644`; tests/scripts | Replace with contextual catalogue/cards | T007 | Card completeness/inventory checklist |
| D025 | Analyser registry descriptions/status interpretation stale and production file unvalidated | analyser TOML/checker/Make | Curated semantics, correct entries, add `--validate` edge | T002/T006 | Targeted tests and `make analyser-contract-tests` |
| D026 | Property inventory has stale IDs/counts and policy has minimum floor | property TOML/policy test | Exact Make-scoped AST parity | T003/T006 | Policy tests/property target |
| D027 | Mutation waivers unused; old schema incompatible; tracked report stale | mutation policy files/workflow | Delete dead files and move generated report | T004/T006/T007 | Consumer search, tests, ignored path |
| D028 | Documentation tests hard-code false wording | `test_help_doc_drift.py:389-411` | Remove obsolete class assertions and add focused semantic suite | T008 | New suite plus retained unrelated tests |
| D029 | README/CONTRIBUTING plain-pytest and ratchet/CI claims conflict | quality sections in both docs | Align with guide and `make test` | T007 | Focused text/semantic tests |
| D030 | Make/OpenCode/coupling/agent comments overstate authority or behaviour | audited comments | Line-neutral correction where possible | T005/T006 | Comment inventory and policy projection |
| D031 | Analyser-contract tests validate fixtures but not production inventory | `Makefile:511-512`; tests | Add production validation to existing target | T002/T006 | Invalid production fixture tests, CI target shape |
| D032 | New focused quality-guide test would re-enter Mutmut | `pyproject.toml:179` exclusions | Add new infrastructure-test ignore | T008 | Pipeline exclusion assertion |

New findings during implementation must be added to the progress journal before editing. Documentation/test/comment-only drift with agreeing executable authorities may be assigned to the owning task. Conflicting executable authorities, security/release changes, or scope expansion require `BLOCKED` and a user decision.

## Execution Graph
```text
T001 preflight and current inventory
  |
  +--> T002 analyser contracts ---------+
  +--> T003 property manifest ----------+--> T006 central integration/comments
  +--> T004 mutation drift -------------+              |
  +--> T005 OpenCode characterisation -----------------+
                                                         |
                                                         v
                                                T007 guide/supporting docs
                                                         |
                                                         v
                                                T008 semantic drift tests
                                                         |
                                                         v
                                                T009 final verification
```

Safe parallel group G1 contains T002, T003, T004, and T005 after T001. Their owned files do not overlap. T006 serially integrates shared Make/test-policy wiring after T002-T004. T007 is the sole `QUALITY_GATES.md` writer. T008 consumes the stable guide structure. T009 is verification-only.

Future execution uses this cyclic state machine:

`RECOVER -> VALIDATE -> SELECT -> DISPATCH -> INTEGRATE -> VERIFY -> REVIEW -> REPAIR -> CHECKPOINT`

After `CHECKPOINT`, transition to `SELECT` while tasks remain, `COMPLETE` when every acceptance criterion has observed evidence, or `BLOCKED` when a user decision or unsafe/unavailable mandatory validation is required.

## Numbered Plan
1. [completed] Capture execution baseline, inventories, consumers, and capabilities
   - Task ID: T001
   - Depends on: none
   - Parallel group: none
   - Owned scope: no implementation files; plan progress journal only
   - Actions: Record current revision/worktree state without altering concurrent changes; inventory current `CHECK_*`/threshold values, Make gate/composite targets, Lefthook stages/leaves, workflow files/jobs, plugin registrations, analyser-contract IDs, property source IDs, mutation report-path consumers, live schemas, and files proposed for deletion. Record a policy projection for thresholds, commands, hook/workflow topology, credential conditions, and mutation exits. Probe availability without installing anything: Python/uv environment, existing OpenCode dependencies, npm, actionlint path/cache, and writable ignored output locations. Classify mandatory versus supplemental validation capabilities.
   - Validation: Compare discoveries with Current-State Evidence and the Drift Ledger. Stop if executable authorities changed materially, if unexpected consumers make deletion unsafe, or if authorities conflict.
   - Acceptance evidence: Journal entry with starting revision/status, inventory sets/counts, old-path consumer list, proposed deletion reference search, policy projection, capability matrix, and exact next eligible tasks.
   - Recovery note: Re-run read-only inventory after interruption. Never infer a baseline from this plan's dated observations, and never revert pre-existing or concurrent changes.

2. [completed] Correct and validate the curated analyser-contract registry
   - Task ID: T002
   - Depends on: T001
   - Parallel group: G1
   - Owned scope: `quality/analyser-contracts.toml`, `scripts/check_analyser_contracts.py`, `tests/test_analyser_contracts.py`, `tests/fixtures/analyser_contracts/**`
   - Actions: Keep schema version 1. Define `phase` as documentation grouping, `status` as contract-runner selection rather than repository wiring, and `test_node_ids` as ownership/evidence references. Correct misleading coupling, Gitleaks, module-coverage, mutation, Ruff, and Pyright descriptions without changing current status/exit ranges. Add explicit process contracts for `typecheck-scripts` and `suppression-reasons`. Make `--validate` reject unknown analyser/state keys, duplicate IDs/targets, unsafe Make target names, missing or non-explicit/non-phony Make targets, duplicate test references, escaped/missing test files, and missing statically resolvable base class/function nodes. Support current file-only, function, class-method, and opaque parameter-suffix forms without claiming pytest will generate a parameter ID. Validate the complete production registry before selection in every CLI mode, but do not invoke any analyser under `--validate`.
   - Validation: Fixture/unit tests for each accepted/rejected form; production TOML validation; mocked tests proving invalid metadata prevents subprocess execution and valid `--validate` invokes none. Compare before/after projections of pre-existing IDs, targets, phases, statuses, and state ranges; only the two new contract entries may expand the projection.
   - Acceptance evidence: Schema remains version 1; production validation exits 0; targeted tests pass; no analyser subprocess ran; corrected descriptions distinguish operational wiring from runner status.
   - Recovery note: Detect partial work through schema/parser/fixture mismatch and the projection diff. Resume the first failing validation layer; do not run default/`--run` modes to diagnose schema work.

3. [completed] Replace property count drift with exact live-manifest parity
   - Task ID: T003
   - Depends on: T001
   - Parallel group: G1
   - Owned scope: `quality/property-inventory.toml`, `tests/test_property_policy.py`, `tests/test_property.py` only if a source node must be corrected rather than the stale inventory
   - Actions: Version the inventory format without storing commit/date/wave/stat totals. Retain canonical `node_id` plus deliberately reviewed semantic annotations; remove duplicated derivable settings/examples/line fields where they add drift rather than rationale. Implement reusable AST discovery that receives source files as input, recognises the supported current `@given` import forms on top-level synchronous/async `test_*` functions, rejects unsupported nested/class placements rather than ignoring them, creates `<repo-relative-file>::<function>` IDs, and reports missing/stale/duplicate entries separately. Reconcile against IDs discovered at execution time; do not enforce a count of 63. Replace the minimum-count test with bidirectional parity and focused synthetic parser tests. Keep repository-level source selection temporarily explicit until T006 introduces the independent Make authority, so this task's checkpoint remains green.
   - Validation: Synthetic tests for direct/aliased supported decorators, async functions, false-positive attributes, unsupported nesting/classes, duplicate IDs, stale manifest IDs, and missing IDs; repository manifest parity using the temporary explicit current source list.
   - Acceptance evidence: No hard-coded minimum/current count; exact source/inventory set equality; semantic annotations reviewed for the corrected IDs; focused policy tests pass.
   - Recovery note: Diagnostics identify source-only and inventory-only IDs. Re-run discovery after concurrent test changes and reconcile IDs, never force the historical count.

4. [completed] Remove mutation-policy ambiguity and relocate generated evidence
   - Task ID: T004
   - Depends on: T001
   - Parallel group: G1
   - Owned scope: `.github/workflows/mutation-scheduled.yml`, `tests/test_mutation_policy.py`, `tests/test_workflow_configuration.py`, deletion of `quality/evidence/mutation-report.json`, `quality/mutation-waivers.toml`, `quality/schemas/mutation-report-v1.json`, and unreferenced `tests/fixtures/mutation/**`; `quality/schemas/mutation-report.json` is read-only in this task
   - Actions: Use T001's consumer/reference search to confirm every live old-path and obsolete-file consumer. Change both shell and embedded-Python workflow readers plus artefact upload to `build/reports/mutation-report.json`. Delete the tracked generated report, placeholder waiver catalogue, incompatible old schema, and orphan fixtures only after zero live-consumer evidence. Preserve `quality/schemas/mutation-report.json` byte-for-byte and preserve mutation status mapping/exit codes. Add workflow tests for the new ignored path, absent-old-path guarantee, full-policy command, always-run summary/upload, and `mutants/` metadata upload. Do not run Mutmut.
   - Validation: Targeted fixture-only mutation-policy and workflow tests; actionlint later in T009; repository search shows no live old report path, old schema, waiver, or deleted-fixture references; `build/` is ignored.
   - Acceptance evidence: Owned-file diff, before/after consumer searches, canonical-schema hash unchanged, mutation-policy exit projection unchanged, and no mutation command executed.
   - Recovery note: Inspect each known producer/consumer independently. If interrupted after deletion but before path integration, restore only the needed task hunk or finish all consumers; never introduce a compatibility shim that could re-enable stale evidence.

5. [completed] Characterise and accurately describe the OpenCode push reminder
   - Task ID: T005
   - Depends on: T001
   - Parallel group: G1
   - Owned scope: `.opencode/tests/pre-push-docs-check.test.ts` (new), `.opencode/plugins/pre-push-docs-check.ts` comments/message/log wording only, `opencode.jsonc` comments only
   - Actions: Instantiate a fresh `PrePushDocsCheckPlugin` with a stub logger and characterise non-Bash, non-matching Bash, first matching reject/warn, second matching allow/info/reset, and third matching reject. Assert only observable calls/rejections. Change comments/log wording from “docs check completed” to an accurate alternating in-session reminder acknowledgement; explain that no review or push success is observed. Do not change the regex, hook keys, state transitions, registration, or other plugin runtime logic. Correct `opencode.jsonc` comments that claim the quality plugin proves arbitrary gate tightening or full tool permissions.
   - Validation: Targeted Vitest suite first, then existing `.opencode` tests/lint/typecheck in T009 when dependencies are available. Compare the executable lines of the plugin before/after to prove only strings/comments changed.
   - Acceptance evidence: Five observable-state cases pass on fresh plugin instances; registration remains three paths; no real OpenCode/analyser/network operation ran.
   - Recovery note: Test-file presence is not completion. Resume by comparing implemented cases with the five observations; do not modify plugin behaviour merely to satisfy an inaccurate mock.

6. [completed] Integrate metadata gates, report path, and audited source comments
   - Task ID: T006
   - Depends on: T002, T003, T004
   - Parallel group: none
   - Owned scope: `Makefile`, `tests/test_quality_pipeline_configuration.py`, `tests/test_make_policy.py`, `scripts/validate_make_policy.py` only if existing parsing cannot express the focused assertions, `tests/test_property_policy.py` source-authority integration, and audited line-neutral comments in `scripts/check_coupling.py`/`scripts/agent_check.py` only where required
   - Actions: Add `analyser-contract-validate` using `scripts/check_analyser_contracts.py --validate` and make the existing `analyser-contract-tests` target depend on it; do not add it to `make check`, hooks, or other CI targets. Add `PROPERTY_TEST_FILES := tests/test_property.py`, make every property target use it, add a `test-property-policy` prerequisite, and update property policy to read/validate that independent Make assignment. This intentionally makes manifest parity block direct, pre-push, CI, and release property lanes. Change `mutate-full-policy` report path to `build/reports/mutation-report.json`. Correct Make help/comments for reusable-target authority, Gitleaks required behaviour, architecture/file-size baseline semantics, six ratchets, `quality-architecture` advisory coupling report, and actual composite scope. Correct audited Python comments line-count-neutrally where possible; if a suppression identity moves, review the exact fingerprint change and do not refresh a baseline merely to silence failure. Add structural tests for both intended metadata edges, shared property-source use, report-path agreement, and preservation of existing commands/topology.
   - Validation: Production analyser `--validate`; analyser-contract tests; property-policy tests; `make test-property`; Make/pipeline policy tests; policy-projection comparison from T001; suppression and suppression-reason gates if Python line positions changed.
   - Acceptance evidence: Exact Make diff identifying only two metadata edges, one report-path change, source-variable consolidation, and comment corrections; thresholds/toggles and all unrelated target recipes/prerequisites unchanged.
   - Recovery note: This is the sole Makefile integration task. Resume by checking for the three markers `analyser-contract-validate`, `PROPERTY_TEST_FILES`, and `build/reports/mutation-report.json`, then run their focused structural tests before broader checks.

7. [pending] Rewrite the quality guide and align supporting human documentation
   - Task ID: T007
   - Depends on: T002, T003, T004, T005, T006
   - Parallel group: none
   - Owned scope: `QUALITY_GATES.md`, relevant quality/testing sections of `README.md` and `CONTRIBUTING.md`, and the missing historical-reference rationale in `tests/test_schema_drift.py`
   - Actions: Rewrite `QUALITY_GATES.md` using the Guide Architecture, Stable Card IDs, field-level authorities, contextual enforcement vocabulary, and Replication Card Fields above. Build the catalogue from T001's execution-time inventory, not this plan's dated counts. Correct every Drift Ledger item. Include setup and safe task runbooks before exhaustive cards. Explain direct/transitive/on-demand/session/local-CI/workflow-CI/release placement and legal skip/tool-error conditions. Document side effects and isolation expectations, including staged fixers, reports, caches, remote Gitleaks queries, dependency audits, build/smoke, and destructive release operations. Replace live mutation counts with schema/path/policy/provenance guidance. Document analyser contracts as curated and property inventory as exact Make-scoped metadata. Align README/CONTRIBUTING with `make test`, current Python/platform CI, hard gates versus baselines, and Make versus inline/workflow authority. Make schema-drift rationale self-contained rather than citing an absent historical file.
   - Validation: Manual source-coverage checklist against the execution-time inventory; all card IDs/fields complete before T008; source references resolve; no stale phrases from the Drift Ledger remain.
   - Acceptance evidence: One sole guide writer diff, completed inventory-to-card checklist, complete source index, and explicit unresolved/external-governance caveats.
   - Recovery note: Process sections and card namespaces in document order. Journal the last complete namespace and first incomplete card; do not let T008 consume unstable headings/field labels.

8. [completed] Replace brittle prose assertions with semantic guide drift tests
   - Task ID: T008
   - Depends on: T007
   - Parallel group: none
   - Owned scope: new `tests/test_quality_gates_documentation.py`; quality-gates-specific class/assertions in `tests/test_help_doc_drift.py`; `pyproject.toml` Mutmut infrastructure-test exclusions; matching exclusion assertion in `tests/test_quality_pipeline_configuration.py`
   - Actions: Remove only obsolete quality-guide literal assertions (Gitleaks graceful-skip, three-baseline-aware, and other corrected wording), preserving unrelated CLI help/README/schema tests. Implement focused parsers and exact contracts: card ID/field uniqueness/completeness, threshold/toggle equality against gates.conf, exact five-stage Lefthook topology and sole stdin consumer, selected Make composite memberships, all six workflow filenames and 14 CI job IDs, plugin registration and npm validation/audit separation, Hypothesis profiles/lane placement, mutation schema/report paths and obsolete-path absence, inline surface documentation, stale-phrase absence, plus negative synthetic parser cases. Add the new test file to Mutmut infrastructure exclusions and assert it.
   - Validation: `uv run pytest tests/test_quality_gates_documentation.py tests/test_help_doc_drift.py tests/test_quality_pipeline_configuration.py -q` — 113 passed; ruff clean; `git diff --check` clean.
   - Acceptance evidence: Exact source/document contracts pass; old false string requirements are gone; new test excluded from Mutmut infrastructure collection; no production gate reads Markdown to determine execution.
   - Recovery note: Expected contracts grouped by surface; resume one surface at a time and record the first failing group; do not weaken exactness solely to make a changed source pass without updating its card.

9. [completed] Verify integration, policy preservation, and completion evidence
   - Task ID: T009
   - Depends on: T002, T003, T004, T005, T006, T007, T008
   - Parallel group: none
   - Owned scope: no implementation files; plan journal/completion review only
   - Actions: Review the complete diff and rerun T001's policy projection. Run mandatory targeted checks: analyser contract validation/tests, property policy and `make test-property`, mutation-policy/workflow tests, quality-guide/help/Make/pipeline/schema/meta tests, and OpenCode characterisation plus `npm --prefix .opencode run check` when existing dependencies are present. Run `make actionlint` when its pinned tool can execute without an unplanned installation. Run `make test-coverage` before `make check` so module coverage consumes fresh evidence, then run `make test`. Run `git diff --check`, old-path/deleted-file searches, ignored-output checks, and repository status review. Broad `make ci`, npm audit, macOS jobs, and live resolved OpenCode config are supplemental only; record unavailable checks as unverified. CI evidence is acceptable only for the exact resulting revision/tree. Never trigger CI, push, release, authenticated Safety, real API/manual tests, or full mutation from this task.
   - Validation: Every mandatory command has command/environment/exit/result evidence. Reconcile all acceptance criteria and Drift Ledger rows. Confirm only the two metadata edges and report-path relocation are intentional non-comment/document changes.
   - Acceptance evidence: Final policy-projection comparison, intended-file diff, command matrix, deleted/ignored path evidence, exact revision evidence for any CI substitution, and completed acceptance matrix.
   - Recovery note: Checkpoint after targeted tests and before broad `make test-coverage`/`make check`/`make test`. Re-run any command whose inputs changed after it ran or whose output is not recorded. Leave status `blocked` rather than treating unavailable mandatory evidence as pass.
   - RESULT: 249 focused integration tests, 113 doc-drift tests, 4548-test full suite (4 pre-existing skips), make check, actionlint, Pyright (src+scripts), analyser-contract-validate, property policy + dev property lane (65), OpenCode npm check (114 tests), both suppression gates, and git diff --check all passed. Final independent review found 2 HIGH (planned-card status, 13-vs-11 field contract), 1 MEDIUM (unregistered integration marker), 2 LOW (stale docstring, README actionlint omission) — all repaired: card landed, all 156 cards carry all 13 fields (test strengthened to enforce), integration marker registered in pyproject and guide wording corrected, docstring updated, README list fixed. No stale phrases; no obsolete mutation paths; only planned files changed; full mutation/release/push/dispatch/authenticated Safety/real-API/manual/real-user-config operations never run.

10. [completed] Refresh reviewed suppression fingerprints moved by analyser validation code
   - Task ID: T010
   - Depends on: T002
   - Parallel group: none
   - Owned scope: `quality/baselines/suppressions.json`; `quality/baselines/suppression-reasons.json` was inspected but required no change
   - Actions: Confirm the suppression ratchet reports exactly four new and four removed identities in `scripts/check_analyser_contracts.py`, with one-for-one unchanged types/reasons: two `nosec` and two `nosemgrep:boolean-flag-argument`. Confirm the reason gate still passes. Refresh only the identity baseline using its canonical update command; do not add, remove, broaden, or alter any suppression comment.
   - Validation: `make suppression-ratchet suppression-reasons` passes; baseline diffs contain only the reviewed old/new line identities.
   - Acceptance evidence: Before/after identity list and focused baseline diff recorded in the journal.
   - Recovery note: If any additional identity appears, stop and investigate rather than refreshing. Both baselines are regenerable only after exact review.

11. [completed] Close first-batch review findings
   - Task ID: T011
   - Depends on: T002, T003, T006
   - Parallel group: none
   - Owned scope: `scripts/check_analyser_contracts.py`, `tests/test_analyser_contracts.py`, `quality/analyser-contracts.toml`, `Makefile`, `tests/test_property_policy.py`, `tests/test_quality_pipeline_configuration.py`, and moved suppression baseline if line identities change
   - Actions: Make `--validate` and `--run` mutually exclusive or make validation unconditionally non-executing, with a conflicting-flags regression test. Strip Make comments and handle logical continuations when reading `.PHONY`; add inline-comment coverage. Rename coupling exit-1 state to cover policy findings and graph errors without changing its range. Make `PROPERTY_TEST_FILES` non-overridable with `override`, update its parser, reject unsafe/non-Python/missing paths, prove command-line assignment cannot alter resolved property scope, structurally detect the module property marker, and remove the duplicate hard-coded current source-list authority. Preserve all gate commands and profile values.
   - Validation: Focused analyser/property/pipeline tests, production `--validate`, Make dry-run override test, property lane, Ruff/Pyright, and suppression gates.
   - Acceptance evidence: Review findings mapped to regression tests; no analyser subprocess under validation; command-line override leaves property recipe unchanged; coupling exit state is semantically accurate.
   - Recovery note: Repair one finding at a time and rerun its focused test. If suppression lines move, apply the same exact-review process as T010.

## Verification Strategy
### Incremental
- T002: fixture and production analyser metadata validation only; never run analysers for schema work.
- T003: synthetic AST/parser tests and exact inventory parity.
- T004: fixture-only mutation-policy tests, workflow parsing, and path/reference searches.
- T005: isolated mocked plugin characterisation.
- T006: focused Make/pipeline/property/analyser/report-path tests and policy projection.
- T007: manual inventory-to-card/source checklist before freezing structure.
- T008: semantic documentation tests with synthetic negative parser inputs.

### Integration
Run together after T008:

```bash
uv run pytest \
  tests/test_analyser_contracts.py \
  tests/test_property_policy.py \
  tests/test_mutation_policy.py \
  tests/test_workflow_configuration.py \
  tests/test_quality_pipeline_configuration.py \
  tests/test_make_policy.py \
  tests/test_quality_gates_documentation.py \
  tests/test_help_doc_drift.py \
  tests/test_schema_drift.py \
  tests/test_removed_plan_gate.py \
  tests/test_repository_hygiene.py -q
```

Then, subject to T001 capabilities:

```bash
make analyser-contract-tests
make test-property
npm --prefix .opencode run check
make actionlint
make test-coverage
make check
make test
git diff --check
```

`make test-coverage` must precede `make check` because current `check` includes the coverage consumer rather than its producer.

### Policy Preservation
Compare before/after evidence for:

- every value in `quality/gates.conf`;
- Lefthook top-level/nested job topology and command/glob/staging/stdin fields;
- every workflow filename/job/trigger/condition/needs/permission/timeout/matrix except the mutation report path;
- analyser target commands and state/exit ranges except the two new curated entries;
- Safety credential/event guards;
- Gitleaks exact-version/failure behaviour;
- mutation `ACTIONABLE_CATEGORIES`, status mapping, live schema hash, and exits;
- property profile values and marker selection;
- the two named metadata-edge additions.

### Capability And CI Evidence
- No dependency installation or network operation is performed merely to satisfy verification.
- A locally unavailable mandatory check leaves the plan blocked unless exact resulting-revision CI evidence exists.
- Prior-revision CI is never substituted.
- Supplemental network/platform checks are recorded as unverified without mislabelling the targeted acceptance evidence.

## Risks And Recovery
| Risk | Likelihood | Impact | Mitigation/recovery |
|---|---|---|---|
| Guide becomes too dense for humans | Medium | High | Put task runbooks and lifecycle summaries before cards; remove duplicate prose and link to cards. |
| Cards become a second policy source | Medium | High | State field-level authorities; tests compare cards to executable sources; no gate reads Markdown. |
| Semantic tests become brittle | Medium | Medium | Compare policy-relevant fields exactly and ignore cosmetic fields; use stable IDs and synthetic parser tests. |
| Curated analyser registry is mistaken for exhaustive wiring | Medium | High | Define schema/status semantics in TOML, checker, tests, and guide; wiring comes from hooks/workflows. |
| New analyser metadata check accidentally runs expensive tools | Low | High | Gate only `--validate`; mocked tests prove no subprocess under validation. |
| Property manifest can shrink its own scope | Low | High | Make owns `PROPERTY_TEST_FILES`; policy verifies all property targets use it. |
| Property parser misses unsupported forms | Medium | Medium | Reject unsupported decorated placements/import ambiguity rather than silently ignore; add synthetic tests. |
| Metadata validation changes blocking behaviour unexpectedly | Medium | Medium | Name both intentional edges; structural tests prove no other prerequisite/topology change. |
| Old mutation path has an external consumer | Low/unknown | High | T001 repository-wide consumer search; no compatibility shim; block if a live consumer is found and migration is unclear. |
| Deleted waiver file encoded intended approvals | Low | High | Placeholder reviewers and no consumer mean no active approval; preserve history and never activate automatically. |
| Mutation workflow uploads no report after early failure | Expected | Low | This is truthful; keep absent-file summary and warning upload semantics. |
| OpenCode tests overclaim runtime equivalence | Medium | Medium | Call them characterisation tests; assert observable mocked hook events only and document gaps. |
| Comment edits shift suppression fingerprints | Medium | Medium | Prefer line-neutral replacements; run exact suppression gates and review any identity change before baseline action. |
| README/CONTRIBUTING drift from exhaustive guide | Medium | Medium | Keep their sections concise and link to `QUALITY_GATES.md`; semantic tests cover key command/classification claims. |
| Mandatory tool unavailable locally | Medium | Medium | Preflight capabilities; exact-revision CI only; leave blocked rather than infer pass. |
| Concurrent work changes owned files | Medium | High | Record starting state per task; use disjoint G1 ownership; preserve unexpected edits and block direct conflicts. |
| Interrupted task leaves schema/path changes partial | Medium | High | Each task records markers, searches, first incomplete item, last command evidence, and exact next action in journal. |

Forward recovery is preferred. Do not use destructive Git commands. Revert or delete only a task's own newly added hunk/file when explicitly necessary and safe; preserve unrelated user/agent changes.

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| Draft lacked resumable CSM controls/checkpoints | Critical | Added required control, state machine, per-task evidence/recovery, journal, and completion gate. | Control, Numbered Plan, Progress Journal |
| Related drift scope was unbounded | High | Added D001-D032 ledger with authority, owner, and acceptance check plus a new-finding rule. | Drift Ledger |
| Universal analyser mirror was self-authorising | High | Kept schema-v1 registry curated and non-exhaustive; no `ANALYSER_TARGETS` mirror or wiring claim. | A008-A010, T002 |
| Analyser read-only definition contradicted coverage/mutation side effects | High | Registry models process outcomes and may contain side-effecting targets; guide cards carry side effects. | Design, T002 |
| Transitive wiring validation was underspecified | High | Removed it from analyser validation; exact topology is owned by focused documentation/configuration tests. | T002, T008 |
| `test_node_ids` grammar was unclear | High | Defined supported path/base-node/opaque-parameter validation without claiming collection identity. | T002 |
| Property manifest controlled its own source scope | High | Make owns `PROPERTY_TEST_FILES`; T006 integrates and validates all property targets. | A011, T003, T006 |
| Current property count risked becoming a hard target | High | 63 is evidence only; execution-time exact IDs control parity. | A012, T003 |
| Property ID discovery was underspecified | High | Limited to explicit supported top-level forms and rejects unsupported placements. | T003 |
| Metadata checks were hidden topology changes | High | Named the two intentional blocking edges and their affected lanes; prohibited others. | Goal constraints, A013-A014 |
| Mutation schema tightening was optional/unsafe | High | Live schema is byte-for-byte preserved; no tightening is allowed. | A016, T004 |
| Mutation path compatibility work was unowned | Medium | T001 records all consumers; T004/T006/T007 own workflow/Make/docs atomically. | T001, T004, T006, T007 |
| Drift tests omitted central lifecycle surfaces | High | T008 covers exact hooks, composites, every workflow, schedules, releases, artefacts, plugins, profiles, paths, inline surfaces, and cards. | Semantic Drift Validation, T008 |
| Blocking semantics were globally ambiguous | Medium | Card field requires caller/event-specific enforcement and unknown merge-required status. | Replication Card Fields |
| OpenCode tests could not prove equivalence | Medium | Scope is observable characterisation on fresh mocked plugin instances only. | A018, T005 |
| Push plugin wording inferred completed review | Medium | Wording/tests describe first-block/second-allow/reset only. | T005 |
| Source-comment acceptance was unbounded | Medium | Drift ledger and T005/T006 enumerate audited comment classes/files; T007 covers supporting docs. | D009-D011, D022, D029-D030 |
| `make ci` acceptance was environment-dependent | High | Made broad/network checks supplemental; targeted local evidence is mandatory and capability-gated. | A021-A022, T009 |
| Recovery notes lacked durable evidence | High | Every task now records markers, commands, first incomplete item, and next action in journal. | Numbered Plan |
| Stable IDs lacked a scheme | Medium | Defined readable locator namespaces, syntax, uniqueness, and rename/retirement rules. | Stable Card IDs |
| “No policy change” was not testable | Medium | Added explicit before/after policy projection and named intentional exceptions. | T001, T009, Policy Preservation |
| T003 depended on Make changes owned by T006 | Medium | T003 remains green with explicit temporary scope; T006 owns repository source-authority integration test. | T003, T006 |
| New guide test would re-enter Mutmut | Medium | T008 owns pyproject exclusion and regression assertion. | A020, T008 |
| Prior CI could be substituted for result revision | Medium | CI evidence is accepted only for the exact resulting revision; otherwise completion remains blocked. | A022, T009 |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---:|---|---|---|---|
| 2026-07-31T20:55:00Z | 0 | INTAKE | none | Goal: plan a human and agent replication guide plus related drift remediation; implementation prohibited. | DISCOVER |
| 2026-07-31T21:00:00Z | 0 | INTAKE -> DISCOVER | none | Baseline clean; existing guide, plans, Make, hooks, workflows, tests, quality and OpenCode surfaces located. | RESEARCH |
| 2026-07-31T21:15:00Z | 0 | DISCOVER -> RESEARCH | none | Uncertainty scout plus seven parallel read-only research tracks completed; no runtime R&D required. | DRAFT |
| 2026-07-31T21:30:00Z | 0 | RESEARCH -> DRAFT | none | Draft established two-layer guide, related-drift tracks, and initial task graph. | CRITIQUE |
| 2026-07-31T21:34:00Z | 0 | DRAFT -> CRITIQUE | none | Independent hostile review returned 1 critical, 12 high, and 8 medium findings. | REMEDIATE |
| 2026-07-31T21:38:00Z | 0 | CRITIQUE -> REMEDIATE | none | Three independent tracks simplified analyser/property scope, expanded semantic tests, and corrected mutation/OpenCode/verification recovery. | CRITIQUE |
| 2026-07-31T21:41:00Z | 0 | REMEDIATE -> CRITIQUE | none | Second independent review found no high issues and 3 medium dependency/evidence issues. | REMEDIATE |
| 2026-07-31T21:42:00Z | 0 | CRITIQUE -> REMEDIATE | none | Property integration moved to T006, Mutmut exclusion assigned to T008, and CI evidence restricted to exact revision. | VERIFY |
| 2026-07-31T21:43:06Z | 0 | REMEDIATE -> VERIFY | none | Primary review mapped all acceptance criteria to tasks/evidence, checked dependencies/ownership/recovery, and verified repository still clean. | SAVED |
| 2026-07-31T21:43:06Z | 0 | VERIFY -> SAVED | none | Plan saved; every implementation task remains pending. | STOP |
| 2026-07-31T21:45:00Z | 1 | NOT_STARTED -> RECOVER | none | User explicitly invoked csm-build; reconstructing repository state before selecting work. | VALIDATE |
| 2026-07-31T21:47:00Z | 1 | RECOVER -> VALIDATE | T001 | Revision `4effe079`; only plan is untracked; uv/npm/node/make/git/Gitleaks/Infisical/OpenCode available; mutation consumers and 63-vs-65 property drift confirmed. | SELECT |
| 2026-07-31T21:57:00Z | 1 | VALIDATE -> SELECT | T001 | 102 focused Python policy tests and 109 OpenCode tests passed; Make dry-run confirmed current integration points. T001 acceptance evidence recorded. | DISPATCH |
| 2026-07-31T21:57:00Z | 1 | SELECT -> DISPATCH | T002-T005 | Selected four disjoint write scopes: analyser contracts, property inventory, mutation drift, and OpenCode reminder. | INTEGRATE |
| 2026-07-31T22:08:00Z | 1 | DISPATCH -> INTEGRATE | T002-T005 | Workers report: analyser tests 41 passed; property tests 13 passed with 63/63 parity; mutation/workflow tests 52 passed and dead files removed; OpenCode reminder tests 5 passed plus lint/typecheck. | VERIFY |
| 2026-07-31T22:18:00Z | 1 | INTEGRATE -> VERIFY | T002-T006 | Inspected worker diffs and integrated shared Make/property/report metadata plus line-neutral source comment corrections. | REVIEW |
| 2026-07-31T22:22:00Z | 1 | VERIFY -> REPAIR | T002-T006,T010 | Analyser/property/mutation/Make/OpenCode checks passed; suppression ratchet found exactly four one-for-one line moves caused by T002. Added T010 for reviewed baseline repair. | VERIFY |
| 2026-07-31T22:24:00Z | 1 | REPAIR -> VERIFY | T010 | Refreshed only `suppressions.json`: two nosec and two nosemgrep fingerprints moved one-for-one; suppression-reasons baseline unchanged and both gates pass. | REVIEW |
| 2026-07-31T22:27:00Z | 1 | VERIFY -> REVIEW | T002-T006 | Combined 147 tests passed; production analyser validation, dev property lane (65 tests), OpenCode 114 tests/lint/typecheck/config, Pyright, suppression gates, and diff check passed. | CHECKPOINT |
| 2026-07-31T22:32:00Z | 1 | REVIEW -> REPAIR | T011 | Review found validate/run conflict, overridable property scope, comment-unsafe phony parsing, and ambiguous coupling exit-1 state. Stale guide report path remains assigned to T007. | VERIFY |
| 2026-07-31T22:40:00Z | 1 | REPAIR -> VERIFY | T011 | T011 repairs complete: mutually exclusive validate/run, Make comment-safe phony parser, coupling findings-or-graph-error state, override PROPERTY_TEST_FILES, structural module marker detection, Make dry-run override test. 152 combined tests pass; analyser/property/OpenCode/suppression gates green. | CHECKPOINT |
| 2026-07-31T22:40:00Z | 1 | VERIFY -> CHECKPOINT | T002-T006,T011 | First batch complete. T002 analayser contracts (v1 curated, 43 tests), T003 property manifest (exact parity, 17 tests), T004 mutation cleanup (consumers searched, dead files deleted, report moved), T005 OpenCode reminder (5 characterisation tests), T006 Make/comment integration (override scope, phony metadata, path, comments), T011 review repairs. 152 focused tests, all targeted gates pass. Next batch: T007 guide rewrite, T008 semantic drift tests, T009 final verification. | SELECT |
| 2026-07-31T22:41:00Z | 2 | CHECKPOINT -> SELECT | T007 | First batch verified; selecting T007 as the next single-writer task. | DISPATCH |
| 2026-07-31T22:55:00Z | 2 | SELECT -> DISPATCH | T007 | T007 delivered 4,008-line guide rewrite plus README/CONTRIBUTING/schema-drift alignment; integrated arch-check comment and _ratchet.py docstring corrections; stale-phrase search clean; card headings verified. | INTEGRATE |
| 2026-07-31T22:55:00Z | 2 | INTEGRATE -> DISPATCH | T008 | Guide verified against current sources; dispatching semantic drift test module task. | INTEGRATE |
| 2026-07-31T23:05:00Z | 2 | DISPATCH -> INTEGRATE | T008 | T008 module written (interrupted after writes); completed Mutmut exclusion assertion and lint fixes; 113 doc-drift tests pass. | VERIFY |
| 2026-07-31T23:10:00Z | 2 | VERIFY -> REVIEW | T007,T008 | 249 focused tests pass; make test-coverage (4548, 97.6%), make check, actionlint, Pyright, npm check, suppression gates green; dispatched final independent review. | REPAIR |
| 2026-07-31T23:25:00Z | 2 | REVIEW -> REPAIR | T009 | Final review: 2 HIGH (planned-card status; 13-vs-11 field contract), 1 MEDIUM (unregistered integration marker), 2 LOW (stale F2-DOCS docstring; README ci-static list). | VERIFY |
| 2026-07-31T23:35:00Z | 2 | REPAIR -> VERIFY | T009 | Repairs landed: guide card marked landed; all 156 cards carry all 13 fields with strengthened test; integration marker registered and guide wording corrected; docstring and README fixed. 113 doc tests + 249 focused tests + 4548 full suite all green. | COMPLETE |

## Completion Review
Filled by the csm-build session on 2026-07-31 after all criteria were verified.

### Acceptance-criteria matrix
1. Human guide with five-minute task paths, setup, safety, side effects, credentials — PASS (sections 2-3).
2. Agent replication reference covering every plugin, inline guard/fixer, Make gate/composite, test lane/meta-gate, CI/scheduled/release job, artefact edge — PASS (156 cards across 8 ID namespaces).
3. Every card unique stable ID with all 13 fields — PASS (census 0 missing; test enforces all 13).
4. Five-stage pre-commit and six-stage pre-push described exactly — PASS (semantic Lefthook topology tests).
5. MAX_FLAGGED=30, all toggles true, suppression-reasons, module-coverage unconditional, six ratchets, threshold authorities — PASS (gates.conf equality test).
6. Coupling/architecture/file-size/suppression/Gitleaks/Safety/fuzz/Hypothesis/coverage/mutation/package/smoke/schema-drift semantics current — PASS (card spot-checks + stale-phrase tests).
7. All 14 CI jobs with correct universal/push-only/PR-only/scheduled/local/session/release contexts; make ci vs workflow CI not conflated — PASS (workflow inventory tests).
8. Scheduled concurrency, SARIF/artefacts, mutation policy status, release, Release Drafter, action pinning accurate — PASS.
9. OpenCode: exactly three plugins, session-only, real hooks/limitations, opencode-check/audit, check-config scope, test gaps — PASS.
10. Mutable observations absent from normative prose; live evidence under build/reports, not tracked — PASS.
11. Analyser contracts schema v1 curated process-outcome registry; production --validate; no analyser execution under validation; validate/run mutually exclusive — PASS.
12. Property inventory live exact manifest; Make-owned source scope (override); bidirectional parity; no counts/SHAs/dates — PASS.
13. Mutation: one live schema, no waivers, no tracked report, build/reports path across Make/workflow/tests/docs; exits unchanged — PASS.
14. Semantic doc tests compare thresholds/toggles/topology/composites/workflows/plugins/profiles/paths/cards/IDs — PASS (tests/test_quality_gates_documentation.py).
15. README/CONTRIBUTING/comments/schema-drift rationale aligned; make test documented safe default — PASS.
16. Mandatory checks with exact evidence — PASS (249 focused, 4548 full suite, make check, actionlint, Pyright, npm check, suppression gates; all recorded in journal).
17. Policy preservation — PASS (gates.conf, lefthook.yml, ci.yml untouched; analyser exit ranges preserved except coupling state-key rename at same range; only named metadata edges and report-path relocation are intentional non-comment/document changes).
18. Only planned files changed; no prohibited operations run — PASS (changed-file inventory matches plan; full mutation/release/push/dispatch/authenticated Safety/real-API/manual/real-user-config never executed).

### Drift ledger disposition
D001-D032 all resolved: D001-D024 via T007 guide rewrite (semantic tests D001-D024 verification), D025/D031 via T002+T006, D026 via T003+T006, D027 via T004+T006+T007, D028 via T008, D029 via T007, D030 via T005+T006, D032 via T008.

### Intentional exceptions
1. Analyser production validation now blocks the existing analyser-contract-tests CI step.
2. Exact property-manifest validation now blocks every property lane (pre-push/CI/release).
3. Generated mutation report relocated to ignored build/reports/ (no policy/exit change).
4. `integration` pytest marker registered (hygiene; silences warnings; no selection change).

### Residual notes
- Full `make ci` (network-dependent smoke/audit), macOS platform jobs, and live resolved OpenCode config were not run locally; they are unchanged by this work and remain covered by the existing CI workflows.
- Pre-existing `scripts/_ratchet.py:133` redundant-cast ty finding is unrelated (ty does not scan scripts/).
- GitHub branch-protection/required-checks state is external and was not claimed.
- Historical `.agents/plans/**` and remediation/evidence records were left untouched.

Implementation completed without committing; the working tree contains only the planned changes.
