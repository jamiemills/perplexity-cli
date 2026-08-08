# PEP 20 Analyser Findings Remediation CSM Plan

## How To Execute
- Start work only through a separate, explicit `csm-build` invocation naming this plan; the planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 3 tasks — T001 low (add `__all__`), T002 standard (error logging), T003 standard-with-spike (conservative de-dup). T002/T003 are judgment-heavy refactors that must keep the repo's strict gates green (`make test`, `make lint`, `make typecheck-all`, radon A-grade); they carry regression risk and should be validated by the full suite. No task touches security-critical logic beyond adding logging.

## Control
- Plan ID: pep20-findings-remediation
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Commits: allowed
- Last checkpoint: 2026-08-08 — plan drafted from a live `scripts/check_pep20.py` run (findings extracted verbatim)
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Remediate the small set of genuinely addressable findings produced by the repo's own PEP 20 analyser (`scripts/check_pep20.py`), while leaving the analyser's proxy-noise findings (missing private docstrings, line-length, CC-vs-radon divergence) as accepted convention. Deliverables:
1. `__all__` declared in the 5 package `__init__.py` files that lack it (aphorism 19).
2. Unlogged `except` blocks either gain meaningful logging or an explicit intentional-silence marker (aphorisms 10/11).
3. A conservative de-duplication of the clearest real duplicate-logic clusters (aphorism 13), scoped to avoid regression risk.

Constraints:
- Do not touch the proxy-noise findings (#1 missing private docstrings, #3 CC-vs-radon, #6 line-length) — those are accepted by the repo's stricter human-tuned gates (ruff ignores E501; radon passes A-grade; docstring convention exempts private helpers).
- Every change must keep the repo's strict gates green: `make test`, `make lint`, `make typecheck-all`, `make complexity` (radon A-grade), `make ratchets`.
- Follow repo conventions (Google docstrings, `%s`-lazy logging, `raise X from Y`, no bare except, British English, CC ≤ 5, ≤ 4 params).
- This is a remediation of `src/` only; no changes to the analyser itself, no new dependencies, no gate/config changes.

Exclusions:
- No changes to `scripts/check_pep20.py` or its verdict thresholds.
- No edits to `quality/gates.conf`, Makefile, CI, or analyser baselines.
- No de-duplication of clusters whose refactor carries high regression risk (see T003 anti-scope).

## Acceptance Criteria
1. `scripts/check_pep20.py` aphorism 19 verdict improves from Weak (5 findings) to Strong (0 findings): all 5 `__init__.py` declare `__all__`.
2. Aphorisms 10/11 finding count drops: every previously-silent `except` either logs (via `%s`-lazy `logger`) or carries an explicit intentional-silence marker/comment; no NEW silent swallows introduced.
3. Aphorism 13 duplicate-logic count drops for the de-duplicated clusters, with no behaviour change.
4. All repo gates pass after the changes: `make test`, `make lint`, `make typecheck-all`, `make complexity`, `make ratchets`.
5. No behaviour change: `pxcli` public API and CLI behaviour unchanged (verified by the existing test suite passing unmodified).

## Current-State Evidence
- Live `scripts/check_pep20.py` run (2026-08-08): Overall 5 Strong / 3 Moderate / 8 Weak / 3 Not-assessable.
- #19 (5): `perplexity_cli/__init__.py:1`, `models/__init__.py:1`, `ports/__init__.py:1`, `services/__init__.py:1`, `utils/__init__.py:1` — all `[missing-all]`.
- #10/#11 (16 each): silent-swallow at `query_runner.py:542,544`, `runners/auth.py:193,195,243`, `runners/config.py:93,125,159,243`, `runners/export.py:291,610,618`, `runners/status.py:235`, `threads/scraper.py:707`, `utils/http_errors/impl.py:57`, `utils/logging/impl.py:57`.
- #13 (19): duplicate-logic clusters incl. `api/client.py:126(3),238(6)`, `utils/config/impl.py:213(9)`, `runners/status.py:51,58`, `query_streaming.py:91,97 & 256,264,279,287`, `threads/pagination.py:87,95`, `utils/session_factory.py:53,75`, `utils/encryption.py:177,195`, `utils/upstream_contracts.py:70,77`, `services/model_service.py:77,92`, `commands/style_cmds.py:129,180`, `mcp_server.py:270,285`, `api/models.py:38,52`, `commands/_help_sections.py:104,112`, `query_runner.py:184,190`, `threads/models.py:122,168`.
- Proxy-noise (out of scope): #1 = 30 missing-docstring on private `_require_*`/`_*` helpers (private exempt by convention); #3 = 15 CC findings (analyser CC counts `try:`, radon passes A-grade); #6 = 565 line-length (ruff ignores E501).

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | Proxy-noise (#1/#3/#6) is accepted convention, not remediated | Decision | Repo gates already pass (ruff ignores E501; radon A-grade; docstring convention exempts private helpers) | Accepted |
| A2 | `__all__` for a re-export facade lists the public names it re-exports; for a near-empty package `__init__` it lists submodules or is `[]` | Decision | Matches PEP 8 / repo facade pattern (`utils/config/__init__.py` already declares `__all__`) | Accepted |
| A3 | Intentional best-effort silences (e.g. logging-flush probes) get an explicit marker/comment rather than new logging | Decision | Aphorism 11 "unless explicitly silenced"; some swallows are deliberate | Accepted |
| A4 | De-dup (T003) is limited to low-risk, clearly-identical clusters; behaviour must be preserved and proven by the existing suite | Decision | Regression risk on strict gates is the main hazard | Accepted |
| A5 | The analyser is advisory; improving verdicts is the goal, not making it a gate | Decision | User asked to "address" findings, not gate on them | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | Which findings are real vs proxy-noise? | Live `scripts/check_pep20.py` run + cross-check vs repo gates | Read-only run; output captured to /tmp | #19 real (5); #10/#11 mostly real (some intentional); #13 mixed (some real, some false-pos); #1/#3/#6 noise | Scope T001-T003 to the real set |
| R2 | Are the 5 `__init__.py` re-export facades or empty? | Read each `__init__.py` (planning read) | Read-only | To be confirmed in T001; add `__all__` accordingly | T001 inspects each before editing |
| R3 | Which #13 clusters are safe to de-dup? | Inspect each cluster (planning read) | Read-only | `runners/status.py:51,58`, `utils/session_factory.py:53,75`, `utils/encryption.py:177,195`, `utils/upstream_contracts.py:70,77` look like near-identical helpers; `utils/config/impl.py:213(9)` is a repeated env-getter pattern; `api/client.py:238(6)` are `_require_*` adapters (intentional) | T003 de-dups the safe subset only |

## Discovered Requirements
- `__all__` additions must not break `from perplexity_cli import X` public imports or star-imports; verify with the existing suite.
- Adding logging must use `%s`-lazy formatting and an existing module `logger` (repo convention); do not introduce `print`.
- Intentional-silence markers must satisfy `scripts/check_suppression_reasons.py` if a `# noqa` is used (needs `owner:`/`reason:`); prefer an explanatory comment over `# noqa` where possible.
- De-dup must preserve exact behaviour and signatures; prefer extracting a shared helper over rewriting call sites.
- All changes must keep radon A-grade (CC ≤ 5) and pyright strict clean.

## Design
Three independent remediation tasks over `src/`, each validated by the full gate suite:
- T001 (namespaces): add `__all__` to the 5 package `__init__.py`. For re-export facades, list the re-exported public names; for near-empty packages, list submodules or use `[]`.
- T002 (errors): for each silent-swallow, either add `%s`-lazy `logger.<level>(...)` or an explicit intentional-silence comment. Classify each site first (real vs intentional).
- T003 (de-dup): extract shared helpers for the safe duplicate clusters (status readers, session_factory, encryption, upstream_contracts, config env-getter), preserving behaviour. Skip high-risk clusters (`api/client.py` `_require_*` adapters are intentional; leave them).

## Execution Graph
```
T001 (namespaces)  [G1]  depends: none
T002 (errors)      [G1]  depends: none
T003 (de-dup)      [G2]  depends: none (but run after T001/T002 to keep diffs separable)
```
T001 and T002 touch disjoint files (init files vs runner/util bodies) and can run in parallel. T003 touches overlapping util files, so run it after T001/T002 to avoid merge friction. Critical path: (T001|T002) -> T003 -> full-suite validation.

## Numbered Plan
1. [pending] Declare `__all__` in the 5 package `__init__.py` (aphorism 19)
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: low
   - Owned scope: `src/perplexity_cli/__init__.py`, `models/__init__.py`, `ports/__init__.py`, `services/__init__.py`, `utils/__init__.py`
   - Not in scope: any other file; the analyser; gates/config
   - Spike candidate: none
   - Actions: Inspect each `__init__.py`; if it re-exports names, set `__all__` to those names; if it only exposes submodules, set `__all__` to the submodule names; if effectively empty, set `__all__ = []`. Keep Google docstring.
   - Acceptance signal: `uv run python scripts/check_pep20.py | sed -n '/### 19/,/### /p'` shows 0 `[missing-all]` findings (verdict Strong).
   - Validation: `make lint`, `make typecheck-all`, `make test` pass; `python -c "import perplexity_cli, perplexity_cli.utils, perplexity_cli.ports"` still imports.
   - Acceptance evidence: analyser #19 Strong; gates green; imports work.
   - Repair attempts: 0
   - Recovery note: if a star-import or public import breaks, adjust `__all__` to include the missing name; re-run suite.

2. [pending] Log or explicitly silence the unlogged `except` blocks (aphorisms 10/11)
   - Task ID: T002
   - Depends on: none
   - Parallel group: G1
   - Risk: standard
   - Owned scope: `query_runner.py`, `runners/{auth,config,export,status}.py`, `threads/scraper.py`, `utils/http_errors/impl.py`, `utils/logging/impl.py`
   - Not in scope: adding new exception types; changing control flow; the analyser
   - Spike candidate: none
   - Actions: For each of the 16 silent-swallow sites, classify: (a) real -> add `%s`-lazy `logger.debug/warning/error(...)`; (b) intentional best-effort -> add an explanatory comment (or `# noqa` with `owner:`/`reason:` if a lint fires). Do not alter control flow or return values.
   - Acceptance signal: `uv run python scripts/check_pep20.py | sed -n '/### 10/,/### 11/p'` shows a reduced/zero silent-swallow count and no NEW findings elsewhere.
   - Validation: `make test`, `make lint`, `make typecheck-all` pass; behaviour unchanged.
   - Acceptance evidence: #10/#11 counts reduced; gates green; no behaviour change.
   - Repair attempts: 0
   - Recovery note: if a logged site changes behaviour/tests, revert that site to a comment-marker instead of logging.

3. [pending] De-duplicate the safe duplicate-logic clusters (aphorism 13)
   - Task ID: T003
   - Depends on: T001, T002 (run after to keep diffs separable)
   - Parallel group: G2
   - Risk: standard (regression risk; validated by full suite)
   - Owned scope: `runners/status.py`, `utils/session_factory.py`, `utils/encryption.py`, `utils/upstream_contracts.py`, `utils/config/impl.py`
   - Not in scope: `api/client.py` `_require_*` adapters (intentional), `api/models.py`, `mcp_server.py`, `commands/*` (higher risk); the analyser
   - Spike candidate: confirm each chosen cluster is truly identical-before-extraction by running the suite before and after.
   - Actions: For each safe cluster, extract a single shared helper and replace the duplicates, preserving signatures/behaviour. Keep CC ≤ 5 and pyright strict clean.
   - Acceptance signal: `uv run python scripts/check_pep20.py | sed -n '/### 13/,/### 15/p'` shows a reduced duplicate-logic count for the de-duped files.
   - Validation: `make test`, `make lint`, `make typecheck-all`, `make complexity` pass; behaviour unchanged.
   - Acceptance evidence: #13 count reduced for the chosen files; all gates green.
   - Repair attempts: 0
   - Recovery note: if a de-dup regresses a test, revert that cluster and mark it out-of-scope (advisory).

## Verification Strategy
- Cheapest first per task: `make lint` + `make typecheck-all` before `make test`.
- Per-task analyser check: re-run `scripts/check_pep20.py` and inspect the relevant aphorism section.
- Final gate: `make test`, `make lint`, `make typecheck-all`, `make complexity`, `make ratchets` all green.
- Known flaky: `make test` under `-n auto` can flake on gitleaks/semgrep (environment). Run the full suite; if a known-flaky env test fails unrelated to the change, isolate and re-run that test serially to confirm it's environmental.

## Risks And Recovery
- R1 (standard): de-dup (T003) changes behaviour subtly. Mitigation: conservative subset only; full suite must pass; revert cluster on regression.
- R2 (standard): adding logging changes stdout/stderr in tests that assert output. Mitigation: use `logger.debug` (below default level) for noisy sites; run suite.
- R3 (low): `__all__` changes break a star-import. Mitigation: run suite; adjust `__all__`.
- Rollback: each task is a separable commit; revert per-task if it regresses.

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| (primary-led) De-dup is regression-risky | Major | Scoped T003 to a conservative subset with spike + full-suite gate; excluded high-risk clusters | R3 |
| (primary-led) Logging may alter test-asserted output | Minor | Use `logger.debug` for noisy sites; suite as gate | R2 |
| (primary-led) Proxy-noise must not be "fixed" | Minor | Explicitly excluded #1/#3/#6 with rationale | A1 |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---|---|---|---|---|
| 2026-08-08 | 0 | INTAKE | — | Ask = plan remediation of the pep20 analyser's addressable findings (#19, #10/#11, #13) | DISCOVER |
| 2026-08-08 | 0 | DISCOVER/RESEARCH | — | Live analyser run extracted exact findings; real set = #19 (5), #10/#11 (16), #13 (19, mixed); #1/#3/#6 = proxy-noise | DRAFT |
| 2026-08-08 | 0 | DRAFT | — | 3-task plan (namespaces / errors / conservative de-dup) | CRITIQUE |
| 2026-08-08 | 0 | CRITIQUE | — | Primary-led: scoped de-dup, logging level, proxy-noise exclusion | VERIFY |
| 2026-08-08 | 0 | VERIFY | — | Acceptance criteria map to T001-T003; gates named; recovery per task | SAVED |

## Completion Review
(filled by csm-build when all criteria are verified)
