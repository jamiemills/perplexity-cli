# PEP 20 Adherence Analyser CSM Plan

## How To Execute
- Start work only through a separate, explicit `csm-build` invocation naming this plan; the planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 8 tasks — 7 standard, 1 low. Tasks T002–T005 build in parallel on one shared-types foundation (G1 invariant: no G1 module may import another G1 module). T004 (gh client) touches `subprocess` (justified `# nosec B404` on import, `# nosec B603, B607` on the call) and requires independent review before merge. T008 must refresh `quality/baselines/suppressions.json` (exactly two new `scripts/_pep20_scoping.py:<line>:nosec` fingerprints) so `make test` stays green.

## Control
- Plan ID: pep20-adherence-analyser
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Commits: allowed
- Last checkpoint: 2026-08-04 — plan drafted, critiqued, remediated, verified
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Build a deterministic, stdlib-`ast`-only Python analyser — `scripts/check_pep20.py` — that assesses a Python repository (or a GitHub pull request via read-only `gh`/GitHub API) for adherence to PEP 20 (Zen of Python), mirroring the 19-aphorism evidence-based assessment already performed on this repo. The tool reports a per-aphorism verdict (Strong / Moderate / Weak / Not-assessable) with `file:line` evidence, rubric prose for the three non-mechanical aphorisms, and deterministic Markdown + JSON output.

Deliverables:
1. `scripts/check_pep20.py` — argparse CLI entry point (repo mode default `src/`, `--root` override, `--pr N` mode, `--repo OWNER/REPO`, `--json`, `--output PATH`, `--post-comment` opt-in).
2. Four helper modules under `scripts/` (flat `_pep20_*.py` style, matching `_gates.py`/`_ratchet.py`).
3. `tests/test_check_pep20.py` — hermetic (no network), deterministic unit tests; mutmut-excluded.
4. Makefile phony target `pep20` running the advisory report.

Constraints:
- Deterministic engine only (user-dictated): stdlib `ast` + `argparse` + `json` + `dataclasses` + `pathlib` + `subprocess` (gh only). No LLM, no third-party dependencies, no network from the scoring engine.
- PR mode via `gh`/GitHub API (user-dictated): read-only GETs by default; `--post-comment` is an explicit opt-in (POST, never default, never tested against a live service).
- Advisory report tool, NOT a gate: exits 0 on success, 2 on usage/tool error. Do NOT wire into `ci-quality`, `ratchets`, `make check`, or `ci-conventional` (drift-tested inventories).
- The new analyser itself must pass the repo's full convention stack on `scripts/`: pyright strict, ruff (effective rules on scripts are `C901` CC ≤ 5 and `PLR0913` ≤ 4 args), bandit (justified `# nosec B404` + `# nosec B603, B607`), deptry.

Exclusions:
- No edits to `quality/gates.conf` (agent-denied file) and no new gate keys.
- No wiring into `ci-quality` / `ratchets` / `make check` / `ci-conventional` / `QUALITY_GATES.md` card edits (avoids drift-test and analyser-contract obligations).
- No NEW ratchet gates, no score-gate thresholds, no `--update-baseline` for a PEP20 baseline. The ONLY permitted `quality/baselines/` change is the single justified refresh of `quality/baselines/suppressions.json` in T008 that records the two new justified `# nosec` fingerprints introduced by T004 — required so `make test` -> `tests/test_quality_ratchets.py` -> `check_suppressions.py` stays green.
- No LLM/agent-assisted scoring of qualitative aphorisms; rubric prose replaces scores for 9, 14, 16.
- No PR comment-posting verification, no `gh`-based CI workflow changes, no local `git diff` PR mode (API-based per user decision).
- No evaluation of non-`.py` files, no walking `tests/` by default, no generated-code detection.

## Acceptance Criteria
1. `uv run python scripts/check_pep20.py` (default root `src/`) on this repo exits 0 and prints a Markdown report containing all 19 aphorisms, each with a verdict, and at least one `file:line` evidence entry for each mechanical aphorism that produces findings.
2. `uv run python scripts/check_pep20.py --json` prints a JSON object with the schema in `_pep20_report.py` (aphorisms array + summary), deterministic ordering (sorted by aphorism id, path, line).
3. `uv run python scripts/check_pep20.py --pr 2355 --repo pypa/hatch` exits 0 and prints a report whose findings are line-scoped to the PR's added lines. Reference PR verified open on 2026-08-04 (head `610995cdb6f3ae2d22b3ed3aedf9984fa51ee80f`; re-verify before execution since open PRs drift): changed `.py` files `src/hatch/config/constants.py`, `src/hatch/index/core.py`, `src/hatch/utils/network.py`, `tests/utils/test_network.py` all carry non-empty API `patch`; the `.md` files are filtered; at least one finding is scoped to an added line (e.g. >100-char lines in `src/hatch/utils/network.py` or the 117-char `ValueError, match=…` lines in `tests/utils/test_network.py`); files without an API `patch` are reported as "unscoped" warnings.
4. Running the same command twice on identical input produces byte-identical output (determinism test in `tests/test_check_pep20.py`).
5. `uv run pytest tests/test_check_pep20.py -q` passes (hermetic, no network — gh calls mocked).
6. `make pep20` runs the advisory report; `make lint`, `make typecheck-scripts` (`uv run pyright scripts/`), `make bandit`, `make deptry` all pass with the new files present; `make test` passes.
7. `tests/test_check_pep20.py` is added to the mutmut `--ignore` list at `pyproject.toml:180`, and `quality/baselines/suppressions.json` carries exactly the two new `scripts/_pep20_scoping.py:<line>:nosec` fingerprints.

## Current-State Evidence
- Existing gates scope to `src/`: `check_file_size.py:60` `SRC.rglob("*.py")`; `check_coupling.py:273` builds from `SRC_ROOT`; `track_metrics.py:27` `SRC_DIR = "src/perplexity_cli"`. No gate walks `tests/` for convention scoring.
- Canonical script anatomy: `check_file_size.py` — Google docstring with `Usage::` + exit codes, `from __future__ import annotations`, `if __package__ in (None, ""): sys.path.append(...)` bootstrap, package-relative imports with `# noqa: E402  # owner: ...; reason: ...` ONLY when the import follows a module-level assignment, `_parse_args()` argparse, `if __name__ == "__main__": main()`. Exit codes 0 pass / 1 findings / 2 usage. E402 nuance verified: ruff exempts `sys.path` modifications between imports, so the FIRST package import after the bootstrap needs NO noqa; a spurious noqa fails RUF100.
- Effective ruff complexity rules on `scripts/` are `C901` (mccabe ≤ 5, `pyproject.toml:113-114`) and `PLR0913` (≤ 4 args, `pyproject.toml:117`) ONLY. `max-branches`/`max-returns`/`max-statements` (PLR0911/0912/0915) are globally ignored (`pyproject.toml:107`) and also per-file-ignored for scripts (`pyproject.toml:138`); `max-nested-blocks` (PLR1702) is preview-only in ruff 0.15.16 and not enforced (verified empirically). Python floor 3.12 (`pyproject.toml:10`), so `ast` `end_lineno` is guaranteed present on all statement nodes (verified in R&D).
- `make typecheck` = `uv run ty check src` (Makefile:146-147) does NOT cover scripts; `make typecheck-scripts` = `uv run pyright scripts/` (Makefile:152-153), pyright `typeCheckingMode = "strict"` (`pyproject.toml:183-189`).
- `make deptry` = `uv run deptry src tests scripts` (Makefile:269-270); scripts are first-party (`pyproject.toml:193`).
- `make ratchets` six members and `make ci-quality` seventeen members are hard-asserted by `tests/test_quality_gates_documentation.py:592-605` and `tests/test_quality_pipeline_configuration.py:308-330`; `quality/gates.conf` is DENIED to agents (`opencode.jsonc`) and every key must be mirrored in `QUALITY_GATES.md`. Adding wiring into these inventories requires coordinated Makefile + QUALITY_GATES.md + drift-test edits — deliberately avoided by this plan (standalone `pep20` target only).
- `make test` = `uv run pytest tests/ -q --tb=line -x -n auto -m "not property and not hermetic_integration and not integration and not real_api and not manual and not real_user_config and not fuzz" $(addprefix --ignore=,$(MUTATION_PROPERTY_FILES))` (Makefile:329-332); the ignore list is the **4-file** `MUTATION_PROPERTY_FILES` (Makefile:20-24: test_property.py, test_property_policy.py, test_mutate_diff_files.py, test_mutation_policy.py). A new `tests/test_check_pep20.py` is collected by `make test` by default, INCLUDING `tests/test_quality_ratchets.py` which runs the real `check_suppressions.py` and asserts exit 0 (lines 57-66). `[tool.mutmut] pytest_add_cli_args` at `pyproject.toml:180` explicitly ignores existing meta-gate tests; the new test must be appended there.
- Suppression ratchet: `scripts/check_suppressions.py:49` scans `src/` AND `scripts/`; fingerprints `# noqa`/`# nosemgrep`/`# nosec`/`# type: ignore`/`# pyright: ignore`/`# pragma` against `quality/baselines/suppressions.json` (an object with a `"fingerprints"` array of `"path:line:type[:detail]"` strings; nosec has no capture group, so the fingerprint is `path:line:nosec`). `scripts/_ratchet.py:58-68`: any new fingerprint is a regression. `--update-baseline` exists (`_ratchet.add_update_flag`); baseline currently 91 entries. Any new `# nosec` in `scripts/` therefore REQUIRES a `check_suppressions.py --update-baseline` refresh before `make test` passes.
- Fail-closed network guard (`tests/conftest.py:44`, `tests/support/network_guard.py`) patches Python socket/DNS/curl entry points but NOT subprocesses; a `gh` subprocess in a default-lane test would escape it. PR-mode tests must mock the gh layer.
- Two syntax-invalid `.py` fixtures exist under `tests/fixtures/` (verified by `ast.parse` scan) — a whole-tree walk would break; `src/` parses cleanly. `check_coupling.py:297-299` wraps `SyntaxError` in `SyntaxErrorInSource`.
- Repo self-facts (from the prior manual PEP 20 assessment, corroborated by R&D): 0 bare `except:`, 0 `except ...: pass`, 0 `eval`/`exec` in `src/`; `# type: ignore` count 0 in production; `noqa` count 2; `__all__` present in 12 of 17 package `__init__.py` files; 43 lines over 100 chars (E501 intentionally ignored); radon CC gate uses A-grade; 1000-line file cap enforced.
- `gh` 2.45.0 installed and authenticated as `jamiemills` (verified `gh auth status`). `jamiemills/perplexity-cli` is public with zero PRs; R&D validated read-only queries against `octocat/Hello-World`, `cli/cli`, `vercel/next.js`, `pypa/hatch`.
- Bandit precedent for subprocess (verified): `scripts/smoke_test.py:28` `import subprocess  # nosec B404  # owner: quality-infrastructure; reason: ...` and `:229` `subprocess.run(  # nosec B603, B607  # owner: quality-infrastructure; reason: ...`. Empirically `subprocess.run(["gh", ...], shell=False)` fires B404 (import) + B603 + B607; `# nosec B603, B607` on the run line plus `# nosec B404` on the import is required for bandit exit 0.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | Deterministic stdlib-`ast` scoring engine, no LLM | User-dictated | User selected "Deterministic only" | Accepted |
| A2 | PR mode via read-only `gh`/GitHub API; `--post-comment` opt-in only | User-dictated | User selected "GitHub PR via gh/API" | Accepted |
| A3 | Default repo scope is `src/`, overridable with `--root` | Decision | Matches every existing gate; `src/` parses cleanly | Accepted |
| A4 | Advisory report tool, exit 0/2, NOT a gate; no gates.conf changes | Decision | `gates.conf` is agent-denied; drift tests lock gate inventories; "score" has no gate precedent | Accepted |
| A5 | Standalone Makefile `pep20` phony target only (not in ratchets/ci-quality/check/ci-conventional) | Decision | Avoids drift-test + analyser-contract + QUALITY_GATES.md obligations | Accepted |
| A6 | Verdict thresholds are documented constants in `_pep20_detectors.py` at pyproject parity (CC 5, args 4, nesting 3, returns 4, stmts 30, line 100), not gate keys | Decision | No new gates.conf keys; deterministic | Accepted |
| A7 | Zen CC includes the `try:` keyword and therefore differs numerically from radon by the number of `try:` blocks | Evidence | Verified in sandbox prototype (sample1: zen 15 vs radon 14) | Confirmed |
| A8 | Missing API `patch` (large files) means line-scope unavailable: analyse unscoped + emit warning | Evidence | Verified `gh api .../files` omits `patch` for large files/diffs, no documented cutoff | Confirmed |
| A9 | Syntax-invalid files are recorded as findings, never crash the run | Decision | Precedent: `check_coupling.py` `SyntaxErrorInSource` | Accepted |
| A10 | New test file appended to `[tool.mutmut] pytest_add_cli_args` ignore list | Decision | Mirrors existing meta-gate tests; keeps mutation runs clean | Accepted |
| A11 | Aphorisms 9, 14, 16 are Not-assessable mechanically; rubric prose replaces verdicts | Decision | Semantic judgment; honest labelling per user's "deterministic only" | Accepted |
| A12 | gh subprocess uses `shell=False` with justified nosec — `# nosec B404` on `import subprocess` and `# nosec B603, B607` on the `subprocess.run` call, both with `# owner: quality-infrastructure; reason: ...` | Evidence | Verified on pinned bandit 1.9.4; matches `smoke_test.py` precedent | Confirmed |
| A13 | PR head file content fetched via `gh api .../contents/{path}?ref=<headSha>` (base64) | Decision | Clone-free per user decision; verified read-only | Accepted |
| A14 | Findings carry severity `error|warning|info`; verdicts derive from per-aphorism finding counts + `AggregateSignals` (rows 7/18) | Decision | Deterministic, evidence-based | Accepted |
| A15 | `quality/baselines/suppressions.json` is refreshed exactly once in T008 to add the two new justified `# nosec` fingerprints | Decision | Required by the suppression ratchet inside `make test`; precedented (49 baselined nosec already) | Accepted |
| A16 | Every finding attaches a stable fingerprint `path:line:aphorism:code`; ordering sorted by (aphorism, path, line, code) | Decision | Determinism contract (`QUALITY_GATES.md:2948-2971`) | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | What git/gh commands give a PR's changed files + line-level diff without a clone? | Read-only `gh pr view --json`, `gh pr diff`, `gh api .../pulls/{n}/files` against octocat/cli/cli/next.js/hatch/public repos | No mutating commands; GET only; no repo writes | `gh pr view --json` has no `diff`/`patch`; `files` gives only path+additions/deletions. `gh api .../files` returns full Diff Entry incl. `patch` and `previous_filename`; `--paginate --jq '.[]'` flattens pages; `patch` omitted for large files; hunk parse `@@ -a,b +c,d @@` reproduces `additions` exactly | Use `gh api .../pulls/{n}/files` + hunk parser for line-scoping; handle missing `patch` |
| R2 | Can stdlib `ast` compute CC, nesting, arg/return counts, docstrings, except classification, duplicate blocks, and line spans? | Throwaway scripts in `/tmp/zen-ast-experiments` over 2 synthetic samples + 3 read-only copies of real modules | All writes confined to `/tmp`; repo untouched (git status clean after) | CC/nesting/args/returns/stmts/docstring correct; except-handler classification works (bare/broad/pass/logger/raise/raise-from/return); `end_lineno` present on all nodes at py3.12; `ast.Module` lacks lineno (span = min/max body); duplicate-hash needs ≥2-stmt floor; zen CC includes `try:` (radon doesn't) | Detector design in `_pep20_metrics.py` verified feasible; PR line intersection via `[lineno,end_lineno] ∩ added-range` works |
| R3 | What does a new check script need to fit the repo's wiring/test/policy surface? | Read-only study of scripts/, Makefile, pyproject, QUALITY_GATES.md, drift tests; bandit/ruff/ratchet simulations in /tmp | All writes confined to `/tmp`; repo untouched | pyright strict on scripts is the binding typecheck; ratchets/ci-quality inventories are drift-locked; `make test` collects any `test_*.py` incl. the suppression-ratchet test; network guard doesn't cover subprocesses; all suppressions need `owner:`/`reason:`; deptry covers scripts; bandit fires B404+B603+B607 on gh subprocess; new nosec forces a suppressions.json refresh | Standalone advisory target avoids all drift obligations; tests must mock gh; exact nosec codes; single baseline refresh in T008 |
| R4 | Which public PR has Python changes usable as an acceptance target? | Read-only `gh api .../pulls` + `.../files` on pypa/hatch | GET only | `pypa/hatch#2355` open (head `610995c…`): 4 `.py` files with non-empty patches, added >100-char lines present; `.md` files present to test filtering | Acceptance criterion 3 targets `pypa/hatch#2355`; re-verify head before execution |

## Discovered Requirements
- New `scripts/*.py` files must pass `make typecheck-scripts` (pyright strict) — `make typecheck` (ty) does NOT cover scripts.
- The only enforced complexity rules on `scripts/` are `C901` (CC ≤ 5) and `PLR0913` (≤ 4 args). Every function must stay ≤ CC 5 and ≤ 4 params (group >4 params into `@dataclass(frozen=True, slots=True)`). Do not rely on max-branches/max-returns/max-statements/max-nested-blocks — they are not enforced on scripts (globally ignored or preview-only).
- Every `# noqa` / `# nosec` / `# type: ignore` introduced must carry `# owner: <name>; reason: <explanation>` in the same comment token or the suppression-reasons gate fails (`tests/test_suppression_reasons.py`). Format verified: `# nosec B603, B607  # owner: quality-infrastructure; reason: ...`.
- Required `scripts/` file layout (verified against ruff E402/RUF100 semantics): (1) module docstring; (2) `from __future__ import annotations`; (3) stdlib imports; (4) `if __package__ in (None, ""): sys.path.append(...)` bootstrap; (5) FIRST package import `from scripts._x import (...)` — **no noqa** (ruff exempts `sys.path` modifications); (6) module-level assignments; (7) any package import AFTER an assignment needs `# noqa: E402  # owner: quality-infrastructure; reason: package-relative import after repo-root setup`. A noqa on an import still at top-of-file fails RUF100.
- Bandit runs on `scripts/`; the gh `subprocess.run` call needs `shell=False`, `# nosec B404` on `import subprocess`, and `# nosec B603, B607` on the run call.
- deptry runs `uv run deptry src tests scripts` — the analyser must remain stdlib-only.
- Python floor 3.12: `from __future__ import annotations`, `dataclass(frozen=True, slots=True)`, `StrEnum`, `TypeGuard`, `tomllib`-era syntax all available; `ast` `end_lineno` guaranteed on statement nodes.
- Tests must be hermetic: never invoke real `gh` in `tests/test_check_pep20.py` (network guard does not block subprocesses, and hermetic lanes must stay network-free).
- Any new `# nosec` fingerprint in a `scripts/` file MUST be baselined via `uv run python scripts/check_suppressions.py --update-baseline` before `make test` passes (run once in T008, exactly two new entries).
- Determinism contract: sorted traversal and deterministic tie-breaking everywhere; `QUALITY_GATES.md:2948-2971` documents `ci-quality` as "deterministic offline".
- `%s`-style lazy `logger` formatting if logging is used; `print()` reserved for CLI output (scripts use print to stdout/stderr for report output — consistent with existing gates).
- British English in docstrings/comments; Google-style docstrings on all public functions.
- The detector's CC definition deliberately differs from radon's (includes `try:`) — document this in the module docstring to avoid confusion with `make complexity`.

## Design
Target behaviour: a deterministic, offline, advisory PEP 20 assessment tool.

Flow (single pass over each `.py` file in scope):
```
enumerate .py files (src/ default, --root override; sorted; skip non-.py)
  -> collect_module_signals(source)             # ast_metrics
  -> run 19 detectors (module signals -> findings)
  -> aggregate signals repo-wide (AggregateSignals)
  -> compute verdict per aphorism (findings + aggregates)
  -> (PR mode) filter findings to added-line ranges (scoping)
  -> render markdown or JSON (deterministic sort)
  -> stdout default, --output PATH optional; exit 0 (2 on usage/tool error)
```

Modules:
- `scripts/_pep20_types.py` — all shared types. `AphorismId` (IntEnum 1..19), `Severity` (error/warning/info), `Verdict` (StrEnum: Strong/Moderate/Weak/Not-assessable), `Finding` (frozen dataclass: aphorism, severity, code, path, line, end_line, message), `FunctionMetrics` (frozen: cc, nesting_depth, arg_count, return_count, statement_count, has_docstring, start_line, end_line), `ExceptMetrics` (frozen: kind, line), `DuplicateBlock` (frozen: lines, body_hash), `ModuleSignals` (frozen with the full field contract: functions, excepts, duplicate_blocks, comment_line_count, code_line_count, long_line_count, noqa_count, type_ignore_count, todo_count, wildcard_import_count, eval_exec_count, getattr_count, magic_number_count, bare_except_count, silent_swallow_count, compound_line_count, tab_mix_count, has_all_in_init, module_path, parse_error: str | None), `Hunk` (frozen: start_line, length), `DiffEntry` (frozen: filename, status, previous_filename, additions, deletions, patch: str | None, head_sha), `AggregateSignals` (frozen: function_total, docstring_function_count, comment_line_count, code_line_count, easy_function_count), `APHORISMS: dict[AphorismId, str]` (the 19 canon lines verbatim), `NON_MECHANICAL: frozenset[AphorismId] = {9, 14, 16}` (iterate sorted, never rely on frozenset order).
- `scripts/_pep20_metrics.py` — pure `ast` extraction, no aphorism logic. `collect_module_signals(source, rel_path) -> ModuleSignals`; helpers `function_metrics(node)` (cc incl. try, nesting depth of If/For/While/Try/With reset at nested defs/lambdas, arg count, return count, statement count, docstring presence, end_lineno span), `except_metrics(handler)` (bare/broad/pass-only/logger-call/raise/raise-from/return classification), `normalised_body_hash(func)` (bodies modulo identifiers, ≥2-stmt floor), `comment_signals(lines)` (noqa/type-ignore/TODO/FIXME/HACK counts), `text_signals(lines)` (line length >100 excl. URLs, compound-statement lines, comment ratio inputs, mixed tabs/spaces). SyntaxError wrapped as `ModuleParseError`.
- `scripts/_pep20_detectors.py` — `DETECTORS: dict[AphorismId, Callable[[ModuleSignals], list[Finding]]]` (19 thin functions, each ≤ CC 5, consuming ONLY pre-computed fields on `ModuleSignals` — importing `_pep20_metrics` is forbidden by the G1 invariant), `aggregate_signals(modules: Iterable[ModuleSignals]) -> AggregateSignals` (folds raw counts; defines "easy function" = cc ≤ 5 and arg_count ≤ 4 and return_count ≤ 4 and statement_count ≤ 30 and nesting_depth ≤ 3; function set = FunctionDef/AsyncFunctionDef, lambdas excluded), `VERDICT_RULES: dict[AphorismId, Callable[[list[Finding], AggregateSignals], Verdict]]` (19 entries, table below), `verdict_for(aphorism, findings, aggregates) -> Verdict`, `RUBRICS: dict[AphorismId, str]` (prose for 9, 14, 16). Module docstring notes zen CC includes `try:` and therefore differs from radon.
- `scripts/_pep20_scoping.py` — `parse_diff_hunks(patch_text) -> list[Hunk]` (unified-diff rule `@@ -a,b +c,d @@`; both counts MAY be omitted meaning 1 — handle `@@ -1 +1,6 @@`; added lines only; `\ No newline` ignored), `added_line_ranges(hunks) -> list[tuple[int, int]]`, `in_pr(span: tuple[int, int], ranges) -> bool`, `GhClient` (injectable class wrapping `subprocess.run(["gh", "api", ...])` with `shell=False` and justified nosec; methods `pr_meta(repo, number)`, `pr_files(repo, number)` using `--paginate ... --jq '.[]'` to flatten multi-page results into `list[DiffEntry]`, `fetch_head_file(repo, number, path, head_sha)` via `contents/{path}?ref=<sha>` base64 decode, `post_comment(repo, number, body)` explicit opt-in POST; raises `GhError(message, stderr)` on non-zero exit / 404 / 403).
- `scripts/_pep20_report.py` — owns `Report` (dataclass) and `build_report(target, findings_by_aphorism, verdicts, aggregates, meta, unscoped_files) -> Report`, `render_markdown(report) -> str` (summary table `# | Aphorism | Verdict | Findings`, per-aphorism evidence `path:line code — message`, rubric section for 9/14/16, unscoped-file warnings), `render_json(report) -> str` (`{"meta": {...}, "aphorisms": [{id, title, verdict, assessable, findings, rubric}], "summary": {...}}`); all ordering sorted by (aphorism id, path, line, code).

Verdict threshold table (constants in `_pep20_detectors.py`; `strict` rule `n==0 -> Strong; 1 <= n < T -> Moderate; n >= T -> Weak`; `advisory` rule `0-2 -> Strong; 3-9 -> Moderate; >=10 -> Weak`, always labelled advisory in the report, never affecting exit code):
| Aph | Rule |
|-----|------|
| 1 | strict, T=10 (beauty proxies: missing docstrings, long lines, blank-spacing, tab mix) |
| 2 | strict, T=10 (wildcard imports, global stmt, getattr dispatch, magic numbers, function-level imports) |
| 3 | strict, T=5 (CC > 5 findings) |
| 4 | strict, T=3 (complicated = CC > 5 AND missing docstring, or CC > 8) |
| 5 | strict, T=3 (nesting > 3 findings) |
| 6 | strict, T=10 (long lines, compound statements) |
| 7 | composite from `AggregateSignals`: d = docstring_function_count/function_total (0 if function_total == 0 -> d = 1.0); c = comment_line_count/(comment_line_count + code_line_count) (0 if denominator == 0 -> c = 0.0). Strong iff d >= 0.8 AND 0.05 <= c <= 0.40; else Moderate iff d >= 0.5; else Weak |
| 8 | strict, T=5 (suppression inventory: broad except + suppression, per-file-ignore count) |
| 9 | Not-assessable (rubric) |
| 10 | strict, T=3 (silent swallows, bare except) |
| 11 | strict, T=3 (unmarked silences) |
| 12 | advisory (guessing proxies: loop catch-all continue, >=3-term fallback chains, silent getattr defaults) |
| 13 | advisory (normalised duplicate bodies >= 2 functions) |
| 14 | Not-assessable (rubric) |
| 15 | advisory (TODO/FIXME/HACK counts, pass-only stubs) |
| 16 | Not-assessable (rubric) |
| 17 | strict, T=5 (CC > 5 AND missing docstring AND (long body line OR nesting > 1)) |
| 18 | e = easy_function_count/function_total (1.0 if function_total == 0); Strong iff e >= 0.8; Moderate iff 0.6 <= e < 0.8; else Weak |
| 19 | strict, T=3 (non-empty package `__init__.py` missing `__all__`, namespace structure findings) |

CLI (`scripts/check_pep20.py`):
```
uv run python scripts/check_pep20.py [--root PATH] [--pr N] [--repo OWNER/REPO]
    [--json] [--output PATH] [--post-comment]
```
- Repo mode: walk `--root` (default `src/`), all `*.py` including `__init__.py`.
- PR mode: `gh` read-only fetch (A13): PR meta -> files (paginated) -> keep `.py` files with status in {added, modified} plus renamed-with-patch; skip pure renames, removed, unchanged, and non-`.py` -> fetch head content -> parse hunks -> line-scope findings; missing `patch` -> analyse unscoped + emit warning; PR not found / 403 -> `GhError` -> exit 2.
- `--post-comment`: explicit opt-in; POSTs a compact summary via `GhClient.post_comment`; never default, never exercised by tests against a live service.
- Output: Markdown to stdout by default; `--json` for machine schema; `--output` writes to a path.
- Exit codes: 0 success, 2 usage/tool error. Advisory only — findings never change the exit code.

## Execution Graph
Dependencies:
```
T001 (_pep20_types)      [G0]
T002 (_pep20_metrics)    [G1]  depends: T001
T003 (_pep20_detectors)  [G1]  depends: T001   (G1 invariant: MUST NOT import _pep20_metrics)
T004 (_pep20_scoping)    [G1]  depends: T001
T005 (_pep20_report)     [G1]  depends: T001
T006 (check_pep20 entry) [G2]  depends: T002, T003, T004, T005
T007 (tests + mutmut)    [G3]  depends: T006
T008 (Makefile + verify) [G4]  depends: T007
```
Critical path: T001 -> (any of G1) -> T006 -> T007 -> T008.
Parallel groups: G0 (T001 alone — shared types must exist first); G1 (T002–T005, four independent modules). **G1 invariant**: no G1 module may import another G1 module; every cross-module type lives in `_pep20_types` (T001), and every signal a detector needs is pre-computed onto `ModuleSignals` by T002 — T003 consumes only those fields and defines its own `aggregate_signals`/`VERDICT_RULES` from `_pep20_types` alone. Fallback if a detector is later found to need a direct metrics helper (not on `ModuleSignals`): move T003 to a new group G1b `depends: T002` (G1 = {T002, T004, T005}; G1b = {T003}; critical path grows by one task) — record this as a discovered requirement and re-plan the graph.
No overlapping write ownership: each task writes only its own new files (T007 additionally appends one line to `pyproject.toml:180`; T008 edits only the Makefile plus the one-time `quality/baselines/suppressions.json` refresh).

## Numbered Plan
1. [pending] Create `scripts/_pep20_types.py` — shared data model and aphorism catalogue
   - Task ID: T001
   - Depends on: none
   - Parallel group: G0
   - Risk: standard
   - Owned scope: `scripts/_pep20_types.py` only
   - Not in scope: no detector logic, no metrics extraction, no I/O
   - Spike candidate: none
   - Actions: Define `AphorismId` (IntEnum 1..19), `Severity`, `Verdict` (StrEnum), and frozen dataclasses `Finding`, `FunctionMetrics`, `ExceptMetrics`, `DuplicateBlock`, `ModuleSignals` (full field contract from Design), `Hunk`, `DiffEntry`, `AggregateSignals`; `APHORISMS` title map (all 19 canon lines verbatim); `NON_MECHANICAL = frozenset({9, 14, 16})`. Google-style module docstring; `from __future__ import annotations`; `__all__` for test imports. Do NOT define `Report` here — T005 owns it.
   - Acceptance signal: `uv run pyright scripts/_pep20_types.py` exits 0 and `uv run python -c "from scripts._pep20_types import AphorismId, APHORISMS, Verdict, ModuleSignals; assert len(APHORISMS) == 19 and 1 in AphorismId and 19 in AphorismId and Verdict.STRONG == 'Strong'"` exits 0.
   - Validation: `uv run ruff check scripts/_pep20_types.py` exits 0; `uv run ruff format --check scripts/_pep20_types.py` exits 0.
   - Acceptance evidence: pyright 0 errors; ruff 0 findings; assert command prints nothing.
   - Repair attempts: 0
   - Recovery note: partial work = file missing or missing symbols; re-run the assert command; resume by completing the dataclasses.

2. [pending] Create `scripts/_pep20_metrics.py` — stdlib-`ast` signal extraction
   - Task ID: T002
   - Depends on: T001
   - Parallel group: G1
   - Risk: standard
   - Owned scope: `scripts/_pep20_metrics.py` only
   - Not in scope: no aphorism verdicts, no diff/gh logic, no rendering, no importing `_pep20_detectors`/`_pep20_report`/`_pep20_scoping`
   - Spike candidate: none (AST techniques already verified in R&D R2: CC incl. try, nesting reset at nested defs, `end_lineno` present, Module span = min/max body, ≥2-stmt duplicate-hash floor, `from __future__` excluded from unused-name approximation)
   - Actions: Implement `collect_module_signals(source, rel_path) -> ModuleSignals` filling EVERY field of the T001 contract (functions, excepts, duplicate_blocks, comment_line_count, code_line_count, long_line_count, noqa_count, type_ignore_count, todo_count, wildcard_import_count, eval_exec_count, getattr_count, magic_number_count, bare_except_count, silent_swallow_count, compound_line_count, tab_mix_count, has_all_in_init, module_path, parse_error) via helpers `function_metrics`, `except_metrics`, `normalised_body_hash`, `comment_signals`, `text_signals`; wrap `ast.parse` SyntaxError in `ModuleParseError`; keep every function ≤ CC 5 by extracting helpers.
   - Acceptance signal: `uv run pyright scripts/_pep20_metrics.py` exits 0; `uv run python -c "from scripts._pep20_metrics import collect_module_signals; s = 'def f(x):\n    try:\n        return x\n    except ValueError:\n        pass\n'; m = collect_module_signals(s, 'a.py'); assert m.functions and m.silent_swallow_count >= 1"` exits 0.
   - Validation: `uv run ruff check scripts/_pep20_metrics.py` and `uv run ruff format --check scripts/_pep20_metrics.py` exit 0.
   - Acceptance evidence: pyright 0 errors; assert command passes (function + except signals extracted).
   - Repair attempts: 0
   - Recovery note: partial work = functions/methods half-written or ModuleSignals fields missing; the assert smoke test fails; resume by implementing the named helpers to populate the full contract.

3. [pending] Create `scripts/_pep20_detectors.py` — 19 aphorism detectors, verdict rules, rubrics
   - Task ID: T003
   - Depends on: T001
   - Parallel group: G1
   - Risk: standard
   - Owned scope: `scripts/_pep20_detectors.py` only
   - Not in scope: no AST extraction, no PR scoping, no rendering, NO import of `_pep20_metrics` (G1 invariant — consume only `ModuleSignals` fields)
   - Spike candidate: none
   - Actions: Implement `DETECTORS` (19 thin functions `ModuleSignals -> list[Finding]`, each ≤ CC 5, consuming ONLY pre-computed `ModuleSignals` fields per the Design table): complexity (3), complicated (4), nesting (5), beauty proxies (1), explicitness (2), sparseness (6), readability composite inputs (7), special-cases inventory (8), errors-never-silent (10), explicit-silencing (11), guessing proxies (12), normalised-duplicate detection (13), deferred-work (15), hard-to-explain composite (17), easy-to-explain fraction (18), namespace structure (19); non-mechanical (9, 14, 16) return rubric entries only. Implement `aggregate_signals(modules)`, `VERDICT_RULES` (19 entries per the Design verdict table, signatures `(list[Finding], AggregateSignals) -> Verdict`), `verdict_for`, `RUBRICS` prose for 9/14/16. Module docstring notes zen CC includes `try:` (differs from radon).
   - Acceptance signal: `uv run pyright scripts/_pep20_detectors.py` exits 0; `uv run python -c "from scripts._pep20_detectors import DETECTORS, VERDICT_RULES, RUBRICS, aggregate_signals; from scripts._pep20_types import NON_MECHANICAL; assert len(DETECTORS) == 19 and len(VERDICT_RULES) == 19 and len(RUBRICS) == 3 and set(RUBRICS) == set(NON_MECHANICAL)"` exits 0.
   - Validation: `uv run ruff check scripts/_pep20_detectors.py` and `uv run ruff format --check scripts/_pep20_detectors.py` exit 0.
   - Acceptance evidence: pyright 0 errors; assert command passes; verdict table matches Design table.
   - Repair attempts: 0
   - Recovery note: partial work = missing aphorism keys; the assert catches it; resume by completing the missing entries. If a detector genuinely needs a metric not on `ModuleSignals`, do NOT add the import — extend the `ModuleSignals` contract in T001 and note the graph fallback in Execution Graph.

4. [pending] Create `scripts/_pep20_scoping.py` — diff-hunk parsing, PR line-scoping, gh client
   - Task ID: T004
   - Depends on: T001
   - Parallel group: G1
   - Risk: standard (subprocess + network surface; review required)
   - Owned scope: `scripts/_pep20_scoping.py` only
   - Not in scope: no file-content analysis, no rendering, no execution of `post_comment` (implement the method; the CLI wires the flag)
   - Spike candidate: none (command shapes and hunk parse rule verified in R&D R1)
   - Actions: Implement `parse_diff_hunks(patch_text) -> list[Hunk]` (rule `@@ -a,b +c,d @@` with optional omitted counts meaning 1 — e.g. `@@ -1 +1,6 @@`; added-only; ignore `\ No newline`), `added_line_ranges`, `in_pr(span, ranges)`. Implement `GhClient` with `subprocess.run(["gh", "api", ...], shell=False, check=True, capture_output=True, text=True)` using EXACT nosec format: `import subprocess  # nosec B404  # owner: quality-infrastructure; reason: deliberate gh API call, shell=False, argv not shell interpolation` and `result = subprocess.run([...])  # nosec B603, B607  # owner: quality-infrastructure; reason: deliberate gh API call, shell=False, argv not shell interpolation`. Methods: `pr_meta`, `pr_files` (`--paginate ... --jq '.[]'`, flatten pages into `list[DiffEntry]`), `fetch_head_file` (`contents/{path}?ref=<sha>` base64 decode), `post_comment` (POST, opt-in). Map non-zero exit / 404 / 403 to `GhError(message, stderr)`. Keep functions ≤ CC 5.
   - Acceptance signal: `uv run pyright scripts/_pep20_scoping.py` exits 0; `uv run python -c "from scripts._pep20_scoping import parse_diff_hunks; h = parse_diff_hunks('@@ -1 +1,6 @@\n-Hello\n+Hello World\n'); assert h and h[0].start_line == 1 and h[0].length == 6"` exits 0; `uv run bandit -c pyproject.toml -r scripts/_pep20_scoping.py` exits 0.
   - Validation: `uv run ruff check scripts/_pep20_scoping.py` and `uv run ruff format --check scripts/_pep20_scoping.py` exit 0.
   - Acceptance evidence: pyright 0 errors; hunk parse assert passes; bandit clean (B404 + B603/B607 nosec justified).
   - Repair attempts: 0
   - Recovery note: partial work = GhClient missing or hunk parser wrong; the assert catches the parser; bandit exit 1 means the nosec codes/format are wrong — re-check against `smoke_test.py:28,229`; resume by completing the class.

5. [pending] Create `scripts/_pep20_report.py` — deterministic Markdown and JSON rendering
   - Task ID: T005
   - Depends on: T001
   - Parallel group: G1
   - Risk: standard
   - Owned scope: `scripts/_pep20_report.py` only (owns the `Report` dataclass)
   - Not in scope: no analysis, no scoping, no CLI, no importing `_pep20_metrics`/`_pep20_detectors`/`_pep20_scoping`
   - Spike candidate: none
   - Actions: Implement `Report` (frozen dataclass) and `build_report(target, findings_by_aphorism, verdicts, aggregates, meta, unscoped_files) -> Report`, `render_markdown(report) -> str` (summary table `# | Aphorism | Verdict | Findings`, per-aphorism evidence `path:line code — message`, rubric section for 9/14/16, unscoped-file warnings, advisory labels on rows 12/13/15), `render_json(report) -> str` (schema in module docstring). All ordering sorted by (aphorism id, path, line, code); iterate `NON_MECHANICAL` sorted.
   - Acceptance signal: `uv run pyright scripts/_pep20_report.py` exits 0; `uv run python -c "from scripts._pep20_report import build_report, render_json; import json; out = render_json(build_report('x', {}, {}, None, {'tool': 'check_pep20'}, [])); assert json.loads(out)['summary'] is not None"` exits 0.
   - Validation: `uv run ruff check scripts/_pep20_report.py` and `uv run ruff format --check scripts/_pep20_report.py` exit 0.
   - Acceptance evidence: pyright 0 errors; JSON renders and parses.
   - Repair attempts: 0
   - Recovery note: partial work = rendering functions missing; the assert fails; resume by implementing render_markdown/render_json/build_report and the Report dataclass.

6. [pending] Create `scripts/check_pep20.py` — CLI entry point wiring repo and PR modes
   - Task ID: T006
   - Depends on: T002, T003, T004, T005
   - Parallel group: G2
   - Risk: standard
   - Owned scope: `scripts/check_pep20.py` only
   - Not in scope: no new threshold logic, no detector changes, no new gh parsing; `--post-comment` only wires the already-implemented `GhClient.post_comment` (implementation is T004's)
   - Spike candidate: none
   - Actions: Google-style module docstring with `Usage::` and exit codes; `from __future__ import annotations`; follow the REQUIRED file layout (bootstrap; first package import NO noqa; post-assignment imports noqa'd with owner/reason). `_parse_args()` with `--root` (default `src/`), `--pr N`, `--repo OWNER/REPO`, `--json`, `--output PATH`, `--post-comment`. Repo mode: walk `--root` sorted, all `*.py` incl. `__init__.py`. PR mode orchestration: `GhClient` -> pr_meta -> pr_files -> filter `.py` + status {added, modified} + renamed-with-patch -> fetch_head_file -> parse hunks -> line-scope findings (missing patch => unscoped warning); PR not found / 403 -> `GhError` -> exit 2 with stderr message. `main()` assembles findings, `aggregate_signals`, `verdict_for`, builds report, prints to stdout or `--output`, exits 0. Keep functions ≤ CC 5 and ≤ 4 params.
   - Acceptance signal: `uv run python scripts/check_pep20.py` (default root `src/`) exits 0 and stdout contains all 19 aphorism numbers and the header `# PEP 20 Assessment`; `uv run python scripts/check_pep20.py --json` prints valid JSON with 19 aphorism entries.
   - Validation: `uv run pyright scripts/check_pep20.py` and `uv run ruff check scripts/check_pep20.py` and `uv run ruff format --check scripts/check_pep20.py` all exit 0; running the command twice on `src/` produces identical output (manual determinism spot-check).
   - Acceptance evidence: real self-assessment report printed with all 19 aphorisms; JSON parses; exit 0.
   - Repair attempts: 0
   - Recovery note: partial work = wiring incomplete; the self-assessment command fails or omits aphorisms; resume by completing orchestration in `main()`. If pyright flags `Callable` without type args, fully parameterise generics (strict mode requires it).

7. [pending] Create `tests/test_check_pep20.py` and add mutmut exclusion
   - Task ID: T007
   - Depends on: T006
   - Parallel group: G3
   - Risk: standard
   - Owned scope: `tests/test_check_pep20.py`, one-line append to `pyproject.toml:180` (`[tool.mutmut] pytest_add_cli_args`)
   - Not in scope: no live `gh` calls in tests, no network, no editing of other pyproject sections
   - Spike candidate: none
   - Actions: Write pytest classes covering ALL of: (a) metrics extraction on synthetic snippets via `tmp_path`; (b) each detector on synthetic good/bad samples; (c) verdict threshold behaviour incl. composite rows 7/18 from `AggregateSignals`; (d) `parse_diff_hunks` incl. omitted-count hunks, no-newline, deleted-only; (e) `in_pr` span intersection; (f) `GhClient` via a fake (monkeypatch `subprocess.run` or inject a stub `GhClient` — never real network); (g) report determinism (render twice, byte-equal); (h) CLI exit codes (0, and 2 on bad args and PR-not-found/GhError); (i) `--json` schema smoke; (j) hermetic self-assessment run against a `tmp_path` fixture tree; AND the nine critical paths: (k) PR-mode orchestration end-to-end with mocked gh (pr_meta -> pr_files -> .py filter -> fetch_head_file -> hunk parse -> line-scope -> build_report), asserting exit 0 and scoped findings; (l) renamed-with-patch vs pure-rename vs removed filtering (renamed-with-patch analysed; pure rename and removed skipped); (m) missing-`patch` unscoped warning rendering; (n) PR-not-found -> exit 2 via `GhError` (404); (o) multi-page `--paginate` flattening (two canned pages -> one `list[DiffEntry]`); (p) non-`.py` filtering (README.md/docs entries excluded); (q) `__init__.py` handling in the walk (yields valid module, row 19 signals, no crash); (r) `--output PATH` write path (report written, stdout empty); (s) `--post-comment` arg acceptance (flag accepted with --pr/--repo, POST method never invoked without the flag). Append `--ignore=tests/test_check_pep20.py` to `[tool.mutmut] pytest_add_cli_args` at `pyproject.toml:180`.
   - Acceptance signal: `uv run pytest tests/test_check_pep20.py -q` exits 0 with all tests passing.
   - Validation: `uv run ruff check tests/test_check_pep20.py` and `uv run ruff format --check tests/test_check_pep20.py` exit 0.
   - Acceptance evidence: pytest green; mutmut ignore line present in pyproject.toml.
   - Repair attempts: 0
   - Recovery note: partial work = some tests failing; run pytest to see which; resume by fixing the failing unit. Ensure no test path reaches the real `gh` binary.

8. [pending] Add Makefile `pep20` target, refresh suppressions baseline, and run full verification
   - Task ID: T008
   - Depends on: T007
   - Parallel group: G4
   - Risk: low
   - Owned scope: Makefile (new phony target `pep20` only — no edits to `ci-quality`, `ratchets`, `check`, or drift-tested `.PHONY` inventories) plus the one-time justified `quality/baselines/suppressions.json` refresh
   - Not in scope: no QUALITY_GATES.md card edits, no analyser-contracts.toml changes, no CI workflow changes, no gates.conf edits, no PEP20 baseline/ratchet
   - Spike candidate: none
   - Actions: Add `.PHONY: pep20` and `pep20:  ## Run the PEP 20 adherence report (advisory)` recipe `@uv run python scripts/check_pep20.py $(PEP20_ARGS)` (define `PEP20_ARGS ?=`). Then run, in order: `make pep20`; `uv run python scripts/check_suppressions.py --update-baseline` (review diff: it MUST add exactly the two `scripts/_pep20_scoping.py:<line>:nosec` fingerprints and nothing else); `make lint`; `make typecheck-scripts`; `make bandit`; `make deptry`; `make test`. Confirm determinism by diffing two runs to `/tmp/opencode/p1` and `/tmp/opencode/p2`. Spot-check PR mode read-only against `pypa/hatch#2355` (per Acceptance criterion 3; re-verify the head SHA first); if offline or the PR drifted, record `unverified` and rely on the mocked tests.
   - Acceptance signal: `make pep20` exits 0; `make lint`, `make typecheck-scripts`, `make bandit`, `make deptry`, `make test` all exit 0 with the new files present.
   - Validation: `diff /tmp/opencode/p1 /tmp/opencode/p2` shows no differences (byte-determinism); `git status` shows exactly the new files plus the intended pyproject append, Makefile target, and the two-line `suppressions.json` change.
   - Acceptance evidence: all six commands green; determinism diff empty; git status shows exactly the intended change set.
   - Repair attempts: 0
   - Recovery note: partial work = a gate failing. If `make test` fails on `test_quality_ratchets.py[check_suppressions]`, the baseline refresh was missed or a nosec line shifted — re-run `check_suppressions.py --update-baseline` and re-review the diff. If `make bandit` fails, the nosec codes are wrong (B404/B603/B607) — fix per `smoke_test.py:28,229`. If a drift test fails, a drift-tested inventory was accidentally edited — revert that edit.

## Verification Strategy
- Fast per-task gates (cheapest first): `uv run pyright <file>` (strict), `uv run ruff check <file>`, `uv run ruff format --check <file>` — run after each module task (T001–T006) and for the test file (T007). `uv run bandit -c pyproject.toml -r <file>` for T004 (subprocess).
- Unit: `uv run pytest tests/test_check_pep20.py -q` (T007) — hermetic, mocked gh, covers all nine critical PR-mode paths.
- Integration: T006 acceptance runs the real self-assessment on `src/`; T008 runs `make pep20` and the live PR spot-check (network-permitting).
- Repo-wide final gates (T008, ordered): `make lint` -> `make typecheck-scripts` -> `make bandit` -> `make deptry` -> `make test` (which enforces the suppression ratchet — hence the baseline refresh first). `make typecheck-scripts` (pyright strict on scripts/) and `make deptry` are the two most likely to catch analyser-specific issues; `make test` is the batch gate.
- Determinism: byte-compare two runs (T006 spot-check, T008 formal diff).
- Parallel execution: G1 tasks (T002–T005) may run concurrently — they share only the completed `_pep20_types` module, must not import one another, and write disjoint files. Later groups are serial dependencies.
- Known environment-sensitive checks: the PR-mode live spot-check in T008 is network-dependent — run only if permitted; otherwise record `unverified` and rely on mocked tests. No flaky checks in the hermetic suite.

## Risks And Recovery
- R1 (high): A helper module's pyright-strict or ruff CC ≤ 5 failure stalls G1. Mitigation: each G1 task accepts only on its own pyright/ruff green; recover by extracting helpers (the R&D prototype showed monolithic analysis functions hit CC 59 — the design pre-splits functions).
- R2 (medium): Detector divergence from ruff/radon semantics (zen CC includes `try:`; E501 ignored). Mitigation: document divergence in `_pep20_metrics.py`/`_pep20_detectors.py` docstrings; the tool is advisory, so divergence is informative, not a gate conflict.
- R3 (medium): `gh api` output drift (schema changes, patch truncation, PR head drift). Mitigation: `GhClient` centralises all parsing; `GhError` surfaces stderr; missing `patch` degrades to unscoped warning (A8); tests use recorded fixture shapes; the live PR spot-check re-verifies the head SHA and falls back to `unverified`.
- R4 (medium): Network guard bypass via gh subprocess if a test accidentally invokes real gh. Mitigation: T007 tests inject a fake `GhClient` / monkeypatch `subprocess.run`; no test reaches `gh` (test (s) explicitly asserts the POST method is never invoked).
- R5 (medium): Suppression ratchet regression at `make test` (new nosec fingerprints). Mitigation: T008 runs `check_suppressions.py --update-baseline` and reviews the two-line diff before `make test`; recovery note documents the exact fix.
- R6 (low): Adding the `pep20` target breaks a drift test. Mitigation: the target is not referenced by `ci-quality`/`ratchets`/`check`; T008 runs `make test` which includes `tests/test_quality_gates_documentation.py` and `tests/test_quality_pipeline_configuration.py` to prove no drift regression.
- R7 (low): mutmut ignore edit conflicts. Mitigation: one-line append; `make test` and the mutmut ignore line are both verified in T007.
- R8 (low): G1 invariant violated by T003 importing `_pep20_metrics`. Mitigation: explicit invariant + acceptance asserts; fallback Option A documented in Execution Graph.
- Rollback/forward recovery: every task is additive (new files) except the pyproject append, Makefile addition, and suppressions.json two-line refresh, all trivially revertible; `git status` verified in T008.

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| Suppression-ratchet baseline conflict: plan forbids baseline writes but new nosec requires them; `make test` fails | Blocker | Exclusions amended: single justified `quality/baselines/suppressions.json` refresh in T008; risk summary + A15 + T008 scope/actions updated | `check_suppressions.py:49` scans scripts/; `test_quality_ratchets.py:57-66` runs it; `_ratchet.py:58-68` new fingerprint = regression; `--update-baseline` verified via /tmp simulation |
| Bandit nosec incomplete: `# nosec B603` insufficient; B404 + B607 also fire | Blocker | A12, Discovered Requirements, and T004 actions now specify `# nosec B404` on import and `# nosec B603, B607` on the run call | Empirical bandit 1.9.4 run on scratch file; `smoke_test.py:28,229` precedent |
| Verdict semantics unimplementable (rows 7/18 need aggregates; advisory rows self-contradictory; coverage denominators undefined) | Major | New `AggregateSignals` type + `aggregate_signals()`; `VERDICT_RULES` signature `(list[Finding], AggregateSignals) -> Verdict`; corrected verdict table with exact rules and denominators for all 19 rows; advisory rows defined as 0-2/3-9/≥10 | Remediation §3 |
| G1 parallelism broken (T003 imports `_pep20_metrics`); Verdict/Report/DiffEntry/FunctionMetrics/ExceptMetrics/DuplicateBlock/AggregateSignals have no owner | Major | G1 invariant stated (no G1 module imports another; all shared types in `_pep20_types`; detectors consume only `ModuleSignals` fields); fallback Option A documented; T001 expanded with all shared types; `Report` owned by T005 | Remediation §4 |
| Acceptance criterion 3 vacuous (octocat#1 is README-only) | Major | Criterion retargeted to `pypa/hatch#2355` (verified open, 4 `.py` files with patches, >100-char added lines); head SHA pinned + re-verify note; T008 spot-check updated | Remediation §5 (read-only gh on pypa/hatch) |
| E402/RUF100 landmine: plan mandated unconditional `# noqa: E402` | Major | Discovered Requirements specify the exact layout: first package import needs NO noqa (ruff exempts sys.path), post-assignment imports need noqa, spurious noqa fails RUF100 | Remediation §6 (ruff source + empirical) |
| Critical-path test gaps (rename/removed, missing-patch, PR-not-found, pagination, non-.py, __init__.py, --output, --post-comment, e2e PR orchestration) | Major | T007 Actions expanded with nine explicit critical-path tests (k)–(s) | Remediation §8 |
| Factual errors: max-branches/returns claimed to apply to scripts; MUTATION_PROPERTY_FILES said 5 files | Major | Current-State Evidence corrected: only C901 + PLR0913 enforced on scripts (PLR0911/0912/0915 globally ignored, PLR1702 preview-only); MUTATION_PROPERTY_FILES is 4 files | Remediation §7 (ruff 0.15.16 empirical; Makefile:20-24) |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---|---|---|---|---|
| 2026-08-04 | 0 | INTAKE | — | Ask classified multi-component/open; user decisions: deterministic-only engine; PR via gh/API | DISCOVER |
| 2026-08-04 | 0 | DISCOVER | — | Scout confirmed wiring surface is drift-locked, gates.conf agent-denied, network guard excludes subprocesses, 2 syntax-error fixtures exist | RESEARCH |
| 2026-08-04 | 0 | RESEARCH | — | 4 parallel tracks: repo conventions, detector design (AST verified in /tmp), gh mechanics (read-only verified), uncertainty scout | DRAFT |
| 2026-08-04 | 0 | DRAFT | — | Plan written with 8 tasks, parallel groups, detector table, PR scoping design | CRITIQUE |
| 2026-08-04 | 0 | CRITIQUE | — | Hostile review: 2 blockers + 6 majors identified (baseline conflict, bandit codes, verdict semantics, G1, acceptance-3, E402, tests, facts) | REMEDIATE |
| 2026-08-04 | 0 | REMEDIATE | — | Independent investigator verified every finding empirically (bandit run, ratchet simulation, ruff E402, gh on pypa/hatch); all resolutions applied to the plan | VERIFY |
| 2026-08-04 | 0 | VERIFY | — | Primary agent approved: acceptance criteria map to T001–T008; commands and paths match repo; blockers resolved | SAVED |

## Completion Review
(filled by csm-build when all criteria are verified)
