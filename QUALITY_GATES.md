# Quality Gates and Analysers

A progressive-disclosure reference for the repository's quality gates, analysers,
git hooks, CI jobs, and release controls. It serves two audiences:

1. **Humans** who need the safe command for a task, an understanding of what
   runs and why, and a clear distinction between local feedback and
   authoritative CI or release enforcement.
2. **Agents** who must reproduce or extend the gates faithfully from stable
   identifiers, field-level authorities, exact invocations, trigger rules,
   outcome semantics, requirements, side effects, outputs, and acceptance
   checks.

The human-facing sections come first; the machine-oriented replication cards
are in [Agent Replication Cards](#8-agent-replication-cards).

---

## 1. Guide Contract

### Purpose

This document is a **descriptive reference**. It explains every quality gate in
the repository, where each gate is defined, when and how it runs, what happens
when it fails, and how to replicate or verify it. It is deliberately
progressive: read the [Five-Minute Guide](#2-five-minute-guide) for day-to-day
use, and consult the cards for authoritative detail.

### Audiences

| Audience | Needs | Start here |
|---|---|---|
| Humans (developers, reviewers, maintainers) | Safe commands, side effects, what runs where, local vs authoritative enforcement | Sections 2-6, 9 |
| Agents (coding assistants, automation) | Stable IDs, field-level authorities, exact invocations, outcome semantics | Sections 8, 9, 11-13 |

### Field-level authority

Authority is **field-specific**, not assigned wholesale to one file. No single
file owns "the quality system". The table below states which file owns which
field. A conflict between two executable authorities is a specification
failure and MUST be resolved before a change is committed.

| Concern | Authority |
|---|---|
| Hook phase, stage order, groups, globs, staging, `stage_fixed`, stdin ownership | `lefthook.yml` |
| Reusable command recipes and composite prerequisite sets | `Makefile` |
| Most numeric thresholds and `CHECK_*` toggles | `quality/gates.conf` (denied to agents via `opencode.jsonc`) |
| Native tool settings and the global coverage floor | `pyproject.toml` and dedicated tool configs (`.semgrep*.yml`, `quality/*.toml`) |
| CI/release events, runners, conditions, matrices, `needs`, timeouts, permissions, concurrency, artefacts | `.github/workflows/*.yml` |
| Analyser outcome semantics and fail-closed behaviour | Wrapper implementations in `scripts/` plus their focused tests |
| Evidence shape | The named live schemas under `quality/schemas/` and their producer tests |
| Session plugin behaviour | `opencode.jsonc`, `.opencode/plugins/*.ts`, `.opencode/package.json`, `.opencode/scripts/check-config.ts`, plugin tests |
| Human rationale, replication guidance, glossary | `QUALITY_GATES.md` (this file) |

The following MUST hold:

- **Markdown never drives execution.** No hook, Make target, workflow, or
  analyser reads this document to decide what to run.
- **Executable sources are authoritative.** When prose or a comment disagrees
  with the current executable behaviour, the executable behaviour wins and the
  prose/comment MUST be corrected.
- **Conflicts are specification failures.** Two executable authorities that
  disagree (for example a workflow `needs` edge that contradicts a Make
  composite) are blockers, not documentation trivia.
- **External GitHub settings are unknown.** Branch protection, required status
  checks, environment protection rules, and other server-side configuration are
  not present in this repository and are NOT claimed by this guide. "Blocking"
  is always scoped to the hook/job/release caller described in the card;
  merge-required status remains unknown.

### Normative vocabulary

This guide uses RFC 2119 keywords (**MUST**, **SHOULD**, **MAY**) in normative
statements. Definitions of gate-specific terms (atomic gate, composite,
blocking scoped, advisory, authoritative, universal, trusted, pass, finding,
skipped, not-applicable, tool error, fail-closed/open, baseline, threshold,
evidence, side effect, replication-equivalent) are collected in the
[Glossary](#133-glossary).

---

## 2. Five-Minute Guide

Everything below is safe to run locally. Credentials, network writes, and
mutating git operations are called out explicitly. Commands run from the
repository root.

> **Golden rule.** The documented safe ordinary test command is
> `make test`. Plain `uv run pytest` does NOT apply the live-marker
> exclusions and is not the recommended default (see
> [Tests And Meta-Gates](#10-tests-and-meta-gates)).

### Changed Python code

```bash
make format-fix        # ruff format + ruff check --fix on src/, tests/, scripts/
make check             # all enabled CHECK_* gates (static only; no coverage)
```

- What runs: `make check` expands `quality/gates.conf` toggles. With the
  current configuration every toggle is `true`, so it runs format-check, lint,
  typecheck-all (ty + pyright + pyright-scripts), bandit, vulture, complexity,
  semgrep, architecture, coupling, ratchets (six members), import-linter,
  dynamic imports, suppression-reasons, deptry. `make check` is **static
  only** — it no longer consumes coverage reports; per-module coverage
  enforcement lives in `make test-coverage`.
- Credentials/network/write side effects: none for `format-fix` (writes your
  working tree — it rewrites `src/`, `tests/`, `scripts/`). `make check`
  writes nothing and requires no prior coverage run.
- Duration class: minutes (semgrep is the bottleneck).
- Results appear: in your terminal; ratchet regressions point at the baseline
  refresh command in `quality/baselines/`.

### Changed tests

```bash
make test              # safe ordinary suite: no property/hermetic/live/fuzz tests
make test-coverage     # adds global + per-module coverage enforcement (>= 85%)
make test-fuzz         # atheris fuzz lane (linux x86_64 only)
make test-property     # Hypothesis dev profile (10 examples) after manifest parity
```

- What runs: `make test` runs pytest with `-n auto` and `-x`, excluding the
  `property`, `hermetic_integration`, `integration`, `real_api`, `manual`,
  `real_user_config` and `fuzz` markers, and the **literal core-exclusion
  manifest** (`MUTATION_PROPERTY_FILES`): the property/mutation test families
  are `--ignore`d by explicit path (plan decision A003), never by glob. The
  exclusions live in the Make recipes, **not** in `pyproject.toml` `addopts`.
- Credentials/network: none. Side effects: writes `.pytest_cache`,
  `.hypothesis/`, and (for `test-coverage`) `coverage.json`, `coverage.xml`,
  `.coverage`.
- Duration class: seconds to a couple of minutes.
- Results appear: terminal output. `test-coverage` produces `coverage.json`
  (consumed by `module-coverage` inside the same target) and `coverage.xml`
  (consumed by `make diff-coverage`, the sole changed-line authority).
- The fail-closed **network guard** is default-on: it is installed in
  `pytest_configure` before collection, so every non-live lane (ordinary,
  coverage, hermetic) is loopback-only unless a test is explicitly marked
  `real_api` with `RUN_REAL_API_TESTS=1`.

### Changed dependencies

```bash
uv lock                # update the lockfile (network read of indexes)
make deptry            # declaration hygiene (missing/unused/misplaced)
make pip-audit         # credential-free vulnerability audit (network read)
make safety            # authenticated scan; skips locally without credentials
```

- What runs: `deptry` on `src tests scripts`; `pip-audit` on the project;
  `safety` via `scripts/agent_check.py` using pinned Safety 3.8.1.
- Credentials/network/write: `uv lock` and both audits need network reads.
  `safety` needs `SAFETY_API_KEY` or a configured Infisical workspace; without
  credentials it prints an informational skip (never a pass). Authenticated
  child failures propagate and block.
- Duration class: `deptry`/`pip-audit` are fast; `safety` is minutes.
- Results appear: terminal output. See the `make.safety` and `make.pip-audit`
  cards.

### Changed workflows / CI

```bash
make actionlint        # validate all GitHub Actions workflows (pinned actionlint)
make workflow-policy   # strict semantic validation of workflow policy
make make-policy       # validate Make target ownership and dependency policy
make analyser-contract-tests   # validates production contracts then runs contract tests
```

- What runs: `actionlint` via `uvx --from actionlint-py==1.7.12.24`;
  `workflow-policy` via `scripts/validate_workflow_policy.py --strict`;
  `make-policy` via `scripts/validate_make_policy.py`; `analyser-contract-tests`
  first runs production `scripts/check_analyser_contracts.py --validate`, then
  the unit tests. Editing a workflow also triggers the `workflow-policy`
  pre-commit job (`tests/test_workflow_configuration.py`).
- Credentials/network/write: none (tool fetch is cached by `uvx`).
- Duration class: seconds to a minute.
- Results appear: terminal output.

### Changed OpenCode plugins

```bash
make configure-opencode   # npm ci, then full opencode-check
make opencode-check       # eslint + vitest + tsc + check-config (+ resolved config when CLI present)
make opencode-audit       # npm audit for high/critical
```

- What runs: `npm --prefix .opencode ci`, then lint/test/typecheck/`check:config`
  over `.opencode/{plugins,scripts,tests}` and `opencode.jsonc`.
- Credentials/network/write: `configure-opencode` and `opencode-audit` fetch
  from the npm registry (network read); `opencode-check` is offline once
  dependencies exist. No source writes.
- **Restart OpenCode** after changing plugins or configuration files.
- Duration class: `opencode-check` seconds-to-minutes; `opencode-audit` minutes.
- Results appear: terminal output.

### Changed packaging

```bash
make build             # rm -rf dist; uv build
make verify            # twine check dist/* + scripts/verify_wheel.py
make smoke-test        # install newest dist/ wheel in an isolated venv and exercise it
```

- What runs: sdist+wheel build, distribution verification, then an isolated
  venv install smoke test.
- Credentials/network/write: `verify`/`smoke-test` do not publish anywhere.
  `uv build`/`uvx twine` may fetch build backend tools (network read). Writes:
  `dist/`, `build/`.
- Duration class: a minute or two.
- Results appear: `dist/*.whl`, `dist/*.tar.gz`, terminal output.

### About to push

Pre-push runs automatically via Lefthook. To see exactly what will run, see
[Hook Phase Runbook](#63-pre-push-phase-runbook). The staged pipeline is:

```bash
# Lefthook pre-push runs these in order (stages):
# 1 gitleaks (sole stdin consumer) + static checks (agent/arch/coupling/ratchets)
# 2 test-coverage
# 3 test-property-push + sonar-reports
# 4 mutate-diff
# 5 safety + fuzz
```

- Credentials/network: gitleaks queries the configured remote
  (`git ls-remote`, network read) to scan new refs; `make safety` needs
  credentials or skips informationally. Everything else is local.
- Side effects: `coverage.json`/`coverage.xml`, `build/reports/bandit-report.json`,
  `.hypothesis/`, `mutants/` cache, `dist/` if `make ci` is invoked locally.
- Duration class: minutes to tens of minutes.
- Results appear: terminal output; the push is aborted if any stage fails.

### Releasing

```bash
make ci-trusted        # credential-free ci + fail-closed authenticated safety
make release V=1.2.3   # bump version, uv lock, ci-trusted, commit, tag v1.2.3, push
```

- What runs: `make release` mutates git (commit + tag + push to `origin master`
  and `origin v1.2.3`). The tag triggers `.github/workflows/publish-to-pypi.yml`,
  which re-validates version agreement, runs `make ci-trusted` with
  `SAFETY_API_KEY`, publishes to PyPI via OIDC, and creates a GitHub Release.
- Credentials/network/write: **push and publish are network writes**; PyPI uses
  OIDC (no long-lived token) and Safety needs its secret. Do not run locally
  unless you intend to publish.
- Duration class: CI hours; release workflow up to 30 minutes.
- Results appear: `git log`, `git tag`, PyPI project page, GitHub Release.

---

## 3. Safety, Setup, And Execution Classes

### Prerequisites

`make setup` refuses to proceed until three external tools are on `PATH`:

| Tool | Check target | Purpose | Install |
|---|---|---|---|
| `uv` | `make check-uv` | Python package manager (venv, locked deps) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gitleaks` | `make check-gitleaks` | Pre-push secret scan | `brew install gitleaks` (see [alternatives](https://github.com/gitleaks/gitleaks#installing)) |
| `infisical` | `make check-infisical` | Pre-commit uncommitted-change secret scan | `brew install infisical` (see [docs](https://infisical.com/docs/cli/overview)) |

> **gitleaks is a required, version-pinned tool.** Pre-push and CI secret
> scanning fail closed when gitleaks is missing or is not exactly
> **8.30.1** (`scripts/gitleaks_check.sh` checks the version and exits 3).
> There is no local skip; CI installs 8.30.1 explicitly.

Then:

```bash
make setup               # venv, locked deps, lefthook hooks, CLI help verification
make configure-opencode  # npm ci, plugin lint/test/typecheck, config validation
make test                # verify the environment works
```

- `make setup` creates the virtualenv, syncs locked dependencies, installs
  lefthook git hooks, and verifies the dev CLI shows help. Idempotent.
- `make configure-opencode` runs `npm ci`, strictly checks every OpenCode
  plugin (lint, test, typecheck), and validates `opencode.jsonc` plus
  registered plugin paths. Idempotent.
- `make test` is the safe ordinary test command (see the `make.test` card).

### Execution classes

Every command in this repository belongs to one or more execution classes.
Replication cards state which classes apply, so an agent can reason about
side effects before running anything.

| Class | Description | Examples | Side effects |
|---|---|---|---|
| **read-only-local** | Inspects the working tree without modifying it | `make lint`, `make typecheck`, `make arch-check`, `make ratchets`, `make coupling-report` | None beyond caches/temp files the tool creates (`.ruff_cache`, `__pycache__`) |
| **writes-ephemeral** | Produces ignored reports, caches, and build outputs | `make test-coverage`, `make sonar-reports`, `make build`, `make semgrep-advisory-report`, `make mutate-full-policy` | `coverage.json`, `coverage.xml`, `.coverage`, `build/reports/*`, `dist/`, `.hypothesis/`, `.mutmut-cache` |
| **writes-working-tree** | Rewrites source files (fixers) | `make format-fix`, `ruff check --fix`, `ruff format` via pre-commit stage 3 | Re-writes `src/`, `tests/`, `scripts/` on disk |
| **writes-index** | Re-stages files after fixing | Lefthook fixer jobs with `stage_fixed: true` | Updates the git index |
| **mutates-git** | Commits, tags, pushes | `make release`, pre-push hooks on failure | Creates commits/tags; a failed pre-push aborts the push but leaves the working tree intact |
| **network-read** | Fetches data or tools from the network | `pip-audit`, `deptry`, `uv lock`, `semgrep`/`semgrep-advisory` tool fetch, gitleaks `git ls-remote` remote query | No repository writes; downloads into `uvx`/npm caches |
| **network-write** | Sends data to a remote | `git push` (via `make release`), PyPI publish, GitHub Release creation | Remote state changes only |
| **credentialed** | Requires a secret or OIDC token | Safety (`SAFETY_API_KEY` or Infisical), PyPI publish (OIDC) | Reads secrets from env/Infisical/CI; never logs them |

### Safe replication guidance

- **Prefer the documented Make targets** over raw tool invocations: the Makefile
  is the canonical command layer and the hooks/workflows delegate to it.
- **Never run a class-`mutates-git` or `network-write` command to "verify" a
  change.** Use `git diff --check` and read-only gates instead.
- **Skipped is never a pass.** An informational credential skip is a known gap,
  not a green check. A card that says "skip semantics" MUST be treated as such
  by the caller.
- **Coverage consumers need coverage producers.** `module-coverage` consumes
  `coverage.json` produced by `make test-coverage-report` and is invoked by
  `make test-coverage` (never by `make check`). `make diff-coverage` consumes
  `coverage.xml` and is the sole changed-line authority.
- **Restart OpenCode after plugin/config changes.** Session plugins load at
  session start.
- **Do not refresh baselines to silence a regression.** Baselines record
  reviewed accepted debt; refreshing one is a deliberate, reviewed act (see
  [Baseline refresh protocol](#baseline-refresh-protocol)).

---

## 4. Lifecycle Map

The repository is a layered defence. Cheap deterministic checks run before a
commit; expensive whole-project checks run before a push; CI repeats critical
checks in a clean environment and adds build validation; scheduled workflows
produce long-horizon signals; the release workflow proves tag, source,
metadata, and artefacts agree before upload. Session plugins run continuously
across all of this inside an OpenCode session but never act as lifecycle gates.

```text
OpenCode session (advisory/interception only, not lifecycle gates)
  |
  +-> pre-commit, 5 piped stages:
  |    1 reject-partial-staging (guard)      [hook.pre-commit.reject-partial-staging]
  |    2 read-only linters & validators      [hook.pre-commit.lint-and-validate]
  |    3 auto-fixers, fix-then-format        [hook.pre-commit.fix-formatting]
  |    4 re-run read-only linters            [hook.pre-commit.lint-after-fix]
  |    5 unit tests (no coverage)            [hook.pre-commit.pytest-check]
  |
  +-> pre-push, 6 piped stages (bounded parallel groups):
  |    1 gitleaks (sole stdin) + static      [hook.pre-push.gitleaks-detect, hook.pre-push.static-checks]
  |    2 test coverage                       [hook.pre-push.pytest-coverage]
  |    3 property + sonar reports            [hook.pre-push.property-and-advisory]
  |    4 mutate-diff                         [hook.pre-push.mutate-diff]
  |    5 safety + fuzz                       [hook.pre-push.safety-and-fuzz]
  |
  +-> CI (17 jobs, one concurrency group)
  |    universal: secret-scan, static, test-coverage, hermetic-integration,
  |                repository-policy, test-compat (3.13/3.14), property (3.13),
  |                fuzz-status, package, wheel-smoke-linux, wheel-smoke-macos,
  |                windows_packaging_smoke, pip-audit, test-macos
  |    push-only:  safety (make safety-gate)
  |    PR-only:    diff-coverage, mutation-diff
  |
  +-> scheduled: mutation (Sun 02:00), scorecard (Mon 06:00),
  |               semgrep-advisory (Tue 07:00)
  |
  +-> release: publish-to-pypi on v* tags (version agreement, ci-trusted,
               OIDC publish, GitHub Release); release-drafter drafts notes
```

Node-to-card references:

| Lifecycle node | Cards |
|---|---|
| OpenCode session | `session.quality-gate`, `session.pxcli-quality`, `session.pre-push-docs-check` |
| Pre-commit stage 1 | `hook.pre-commit.reject-partial-staging` |
| Pre-commit stage 2 | `hook.pre-commit.lint-and-validate` (22 parallel jobs) |
| Pre-commit stage 3 | `hook.pre-commit.fix-formatting` (4 piped fixers, `stage_fixed`) |
| Pre-commit stage 4 | `hook.pre-commit.lint-after-fix` (8 parallel re-runs) |
| Pre-commit stage 5 | `hook.pre-commit.pytest-check` |
| Pre-push stage 1 | `hook.pre-push.gitleaks-detect`, `hook.pre-push.static-checks` |
| Pre-push stage 2 | `hook.pre-push.pytest-coverage` |
| Pre-push stage 3 | `hook.pre-push.property-and-advisory` |
| Pre-push stage 4 | `hook.pre-push.mutate-diff` |
| Pre-push stage 5 | `hook.pre-push.safety-and-fuzz` |
| Universal CI | `ci.ci.secret-scan`, `ci.ci.static`, `ci.ci.test-coverage`, `ci.ci.hermetic-integration`, `ci.ci.test-compat`, `ci.ci.property`, `ci.ci.fuzz-status`, `ci.ci.package`, `ci.ci.wheel-smoke-linux`, `ci.ci.wheel-smoke-macos`, `ci.ci.windows_packaging_smoke`, `ci.ci.pip-audit`, `ci.ci.test-macos` |
| Push-only CI | `ci.ci.safety` |
| PR-only CI | `ci.ci.diff-coverage`, `ci.ci.mutation-diff` |
| Scheduled | `automation.mutation-scheduled.mutation`, `automation.scorecard.scorecard`, `automation.scorecard.scorecard-validate`, `automation.semgrep-advisory.semgrep-advisory` |
| Release | `release.publish-to-pypi.publish`, `automation.release-drafter.update_release_draft`, `make.release` |
| Local composites | `make.check`, `make.ci`, `make.ci-trusted`, and every `make.*` card |

---

## 5. Current Policy Values

The single source of truth for most numeric thresholds and all check toggles is
`quality/gates.conf`. It is locked from agent edits by a `deny` rule in
`opencode.jsonc`; agents may only tighten thresholds elsewhere (see
[Change Protocol](#12-change-protocol)). Make evaluates `CHECK_*` toggles
directly; Python analysers read numeric thresholds through
`scripts/_gates.py`, which re-reads the file on every call.

### Quantitative thresholds

| Key | Value | Controls | Source of truth |
|---|---|---|---|
| `MAX_FLAGGED` | 30 | Coupling: maximum allowed flagged modules | `quality/gates.conf`; passed to `check_coupling.py --max-flagged` |
| `DISTANCE_THRESHOLD` | 0.3 | Coupling: Martin distance-from-main-sequence flagging threshold | `quality/gates.conf` |
| `MIN_COVERAGE` | 85 | Coverage: minimum per-module coverage percentage | `quality/gates.conf`; consumed by `scripts/check_module_coverage.py` |
| `FAIL_UNDER` | 85 | Coverage: global `fail_under` floor | Reference mirror only — see duplicate note below |
| `MIN_CONFIDENCE` | 80 | Vulture: minimum confidence for dead-code reporting | `quality/gates.conf` |
| `RADON_CC_GRADE` | B | Radon cyclomatic complexity: worst allowed grade (B and worse fail, so only A passes) | `quality/gates.conf` |
| `RADON_MI_GRADE` | B | Radon maintainability index: worst allowed grade (B and worse fail, so only A passes) | `quality/gates.conf` |
| `FILE_SIZE_CAP` | 1000 | File-size ratchet: maximum source lines per file | `quality/gates.conf` |
| `SEMGREP_SEVERITY` | `--severity ERROR --severity WARNING` | Semgrep: minimum severities scanned | `quality/gates.conf`; consumed by `make semgrep` via `$(SEMGREP_SEVERITY)` |
| `DIFF_COVERAGE_THRESHOLD` | 90 | Diff-cover: minimum coverage on changed lines | `quality/gates.conf` |

### Check toggles (control which analysers run in `make check`)

All toggles in `quality/gates.conf` are currently `true`, so `make check` runs
every one of the analysers below. `make check` is static only: it never
consumes coverage reports.

| Key | Value | Gate added to `make check` |
|---|---|---|
| `CHECK_FORMAT` | true | `format-check` (ruff format --check) |
| `CHECK_LINT` | true | `lint` (ruff check) |
| `CHECK_TYPECHECK_ALL` | true | `typecheck-all` (ty + pyright + pyright-scripts) |
| `CHECK_SECURITY` | true | `security` (bandit + vulture) |
| `CHECK_COMPLEXITY` | true | `complexity` (radon cc + mi) |
| `CHECK_SEMGREP` | true | `semgrep` (blocking policy wrapper) |
| `CHECK_ARCH` | true | `arch-check` (baseline-aware architecture check) |
| `CHECK_COUPLING` | true | `coupling-check` (blocking via `--max-flagged`) |
| `CHECK_RATCHETS` | true | `ratchets` (six members — see the `make.ratchets` card) |
| `CHECK_IMPORT_LINTER` | true | `import-linter` (import contracts) |
| `CHECK_DYNAMIC_IMPORTS` | true | `arch-check-dynamic` (dynamic-import enforcement) |
| `CHECK_SUPPRESSION_REASONS` | true | `suppression-reasons` (owner/reason format on new suppressions) |
| `CHECK_DEPTRY` | true | `deptry` (dependency hygiene) |

### Duplicate-value notes

Two `quality/gates.conf` entries duplicate a value whose active source lives
elsewhere. They are documented here so the duplication is not "fixed" by
mistake:

- **`FAIL_UNDER = 85` is a reference mirror.** pytest-cov reads the global
  floor directly from `pyproject.toml` (`[tool.coverage.report] fail_under =
  85`). The `gates.conf` value is documentation only.
- **`SEMGREP_SEVERITY` is consumed by `make semgrep`.** The value
  `--severity ERROR --severity WARNING` is expanded into the Semgrep
  invocation through `$(SEMGREP_SEVERITY)` inside `SEMGREP_OPTIONS`.

### Command-line override limitation

Because `Makefile` starts with `include quality/gates.conf`, the file's values
are Make variables. A **command-line assignment overrides the included value**
for that invocation, e.g. `make coupling-check MAX_FLAGGED=50` would loosen the
budget for that single run. The `deny` rule in `opencode.jsonc` prevents agents
from editing the file, and `scripts/_gates.py` reads the file directly for
Python analysers, but Make CLI overrides remain possible for a human and are
NOT a persisted policy change. Prefer editing `quality/gates.conf` through the
human protocol in [Change Protocol](#12-change-protocol).

### Per-module coverage ownership (not a `make check` member)

`module-coverage` is owned by the coverage lane, **not** by `make check`:

- `make test-coverage` = `test-coverage-report` then `module-coverage`; the
  report is produced first, so the module floor is always enforced against
  fresh evidence.
- `make check` no longer appends `module-coverage` — it must never consume a
  potentially stale `coverage.json`. Run `make test-coverage` (or
  `make test-coverage-report` first, then `module-coverage`) to enforce the
  per-module floor.
- If `coverage.json` is absent or stale, `module-coverage` fails (exit 2 for a
  missing report). Run the producer first; never "skip" the consumer.

---

## 6. Phase Runbooks

This section describes exactly what runs in each phase, in what order, with
what concurrency, and how it fails. Replication detail lives in the cards.

### 6.1 OpenCode session

Inside an OpenCode session, exactly three first-party plugins are registered
in `opencode.jsonc` and loaded from `.opencode/plugins/`. They are **session
controls**: advisory and interception only. They are NOT repository lifecycle
gates and NOT security boundaries. They MUST NOT be treated as a substitute for
the hooks or CI.

| Plugin | Card | Real hooks |
|---|---|---|
| `quality-gate` | `session.quality-gate` | `tool.execute.before` (write/edit/apply_patch on `scripts/` and `Makefile`); `event: session.idle` (idle coupling check when `git status` shows protected changes) |
| `pxcli-quality` | `session.pxcli-quality` | `experimental.chat.system.transform`; `tool.execute.after` (write/edit only); `event: session.idle` |
| `pre-push-docs-check` | `session.pre-push-docs-check` | `tool.execute.before` (bash `git push` regex) |

- `OPENCODE_DISABLE_QUALITY_GATE=1` disables the whole `quality-gate` plugin.
- Restart OpenCode after changing any plugin, agent, or configuration file.
- Plugins are validated reproducibly by `make opencode-check` / `make
  configure-opencode`; `make opencode-audit` separately audits npm
  dependencies.

### 6.2 Pre-commit phase runbook

`lefthook.yml` declares pre-commit as a **piped pipeline of five stages**. A
piped pipeline aborts on first failure and never runs later stages. Ordering
guarantees:

1. Every read-only check runs in a stage **before** any step that modifies
   files, so semantic errors surface on the original staged content.
2. `ruff check --fix` runs **before** `ruff format` (fix-then-format), so
   formatting is applied to already-fixed code and is never undone.
3. The read-only linters are **re-run after** the auto-fixers to catch a
   regression a fixer may have introduced.
4. Commits that stage only part of a file's changes are rejected up front,
   before any fixer can re-stage and mask the partial edit.

| Stage | Lefthook job | Mode | Jobs | Stdin |
|---|---|---|---|---|
| 1 | `reject-partial-staging` | single guard | 1 | none |
| 2 | `lint-and-validate` | parallel group | 22 read-only jobs | none |
| 3 | `fix-formatting` | piped group | 4 fixers, all `stage_fixed: true` | none |
| 4 | `lint-after-fix` | parallel group | 8 read-only re-runs | none |
| 5 | `pytest-check` | single | `make test` | none |

No pre-commit job sets `use_stdin`. Stage 2 globs and commands are enumerated
in `hook.pre-commit.lint-and-validate`; stage 3 order and `stage_fixed`
behaviour in `hook.pre-commit.fix-formatting`; stage 4 members in
`hook.pre-commit.lint-after-fix`.

### 6.3 Pre-push phase runbook

`lefthook.yml` declares pre-push as a **piped pipeline of six stages with
bounded parallel groups**. Each stage runs only if the previous one passed.

| Stage | Lefthook job | Mode | Jobs | Stdin |
|---|---|---|---|---|
| 1 | `gitleaks-detect` | single | 1 — `scripts/gitleaks_check.sh pre-push "{1}" "{2}"` | **sole `use_stdin` consumer** |
| 2 | `static-checks` | parallel group | `make agent-check-no-tests`, `make arch-check`, `make coupling-check`, `make ratchets` | none |
| 3 | `pytest-coverage` | single | `make test-coverage` | none |
| 4 | `property-and-advisory` | parallel group | `make test-property-push`, `make sonar-reports` | none |
| 5 | `mutate-diff` | single | `make mutate-diff` | none |
| 6 | `safety-and-fuzz` | parallel group | `make safety`, `make test-fuzz` | none |

**Sole stdin ownership:** gitleaks runs first and is the ONLY job that sets
`use_stdin`, so it owns the git push stdin pipe
(`<local-ref> <local-oid> <remote-ref> <remote-oid>` rows). No other job MAY
set `use_stdin`.

**Difference from `make gitleaks`:** the pre-push hook runs the shell script
directly (not the Make target) so it can consume the git-provided stdin and
remote arguments. `make gitleaks` is the standalone/on-demand form.

### 6.4 `make check`, `make ci`, `make ci-quality`, `make ci-conventional`, and workflow CI

These surfaces are related but NOT equivalent:

- **`make check`** — static analysis only, driven by the `CHECK_*` toggles. No
  tests, no build, no smoke, no coverage consumption.
- **`make ci`** — the credential-free local aggregate:
  `ci-static`, `ci-test-coverage`, `ci-fuzz-status`, `pip-audit`,
  `sonar-reports`, `ci-property`, `ci-package`, `smoke-test`. Local `make ci`
  runs `sonar-reports` and `smoke-test` **directly**.
- **`make ci-quality`** — the deterministic offline quality-gate inventory:
  `format-check lint typecheck-all bandit vulture complexity semgrep arch-check
  arch-check-dynamic import-linter coupling-check ratchets analyser-contract-tests
  deptry make-policy workflow-policy actionlint`. No tests, no build.
- **`make ci-conventional`** — the serial final gate list, run offline
  (`UV_OFFLINE=1`, `npm_config_offline=true`) in one exact order: format-check,
  lint, typecheck-all, network-guard/test-isolation tests, test-coverage,
  test-integration, ci-quality, MCP tests, test-fuzz, OpenCode
  test:coverage + check, package-contract, gitleaks-ci, architecture model +
  check.
- **Workflow CI** — splits the same authority into 17 jobs for isolation and
  adds event/platform-specific work: gitleaks full-history, OpenCode
  plugin/config checks, analyser-contract validation/tests, blocking semgrep,
  the `repository-policy` job running the full `make ci-quality` inventory with
  a warmed uvx tool cache (semgrep/actionlint), the 3.13/3.14 compatibility
  matrix, macOS, Windows packaging smoke, push-only Safety, credential-free
  pip-audit, PR-only diff-coverage and mutation-diff.
  Workflow CI **omits `sonar-reports`**.
- **`make ci-trusted`** — `make ci` plus the fail-closed authenticated Safety
  gate; used on push CI and the tag release path.

Architecture, coupling, ratchets, deptry, import-linter, and dynamic-imports
run pre-push / on-demand, and are also covered in CI by the `repository-policy`
job's `make ci-quality` run — they are **not** separate CI jobs (see
[Composite And Topology Reference](#9-composite-and-topology-reference)).

### 6.5 Scheduled workflows

Three scheduled workflows run weekly with `workflow_dispatch` overrides. Each
pins every external action to a full 40-character commit SHA and uploads its
artefacts.

**Concurrency semantics (all three):** the group is
`<workflow>-scheduled` for scheduled runs and `<workflow>-dispatch-<run_id>`
for manual dispatches; `cancel-in-progress: true` applies **only** to
dispatches. Scheduled runs are therefore **never cancelled** by newer runs,
and each dispatch has a unique group.

| Workflow | Schedule | Job | Runs | Outputs / artefacts |
|---|---|---|---|---|
| `mutation-scheduled.yml` | Sunday 02:00 UTC | `mutation` ("Full Mutation Policy") | `make mutate-full-policy` on Python 3.12; timeout 360 min | `build/reports/mutation-report.json` + `mutants/` metadata; 30-day retention; job summary |
| `scorecard.yml` | Monday 06:00 UTC | `scorecard` (producer) + `scorecard-validate` (validator) | OpenSSF Scorecard action; SARIF validation | `results.sarif`; code scanning under `openssf-scorecard` |
| `semgrep-advisory.yml` | Tuesday 07:00 UTC | `semgrep-advisory` ("Latest Community Rules") | `make semgrep-advisory-report` on Python 3.13; timeout 30 min | `build/reports/semgrep-advisory.json` + `.sarif`; code scanning under `semgrep-advisory` |

- **Mutation is a blocking producer.** The `make mutate-full-policy` step can
  FAIL the job (findings or tool error exit). The summary and upload steps use
  `if: always()` so reporting still happens, and they tolerate a missing report
  (`if-no-files-found: warn`).
- **Scorecard** producer publishes results and uploads SARIF; the validator
  parses and uploads SARIF to code scanning.
- **Semgrep advisory** findings are advisory (Semgrep exit 1 does not fail the
  job), but scanner/infrastructure errors propagate and CAN fail the job, and
  the upload step uses `if-no-files-found: error`.

### 6.6 Release phase runbook

**`publish-to-pypi.yml`** is triggered by `v*` tags only.

1. Checkout, set up uv, Python 3.13, sync locked deps.
2. **Version-agreement validation:** tag version == `pyproject.toml`
   `[project].version` == runtime `perplexity_cli.__version__`; mismatch fails.
3. `make ci-trusted` with `SAFETY_API_KEY` from secrets (full credential-free
   CI plus fail-closed Safety).
4. **OIDC publish** via `pypa/gh-action-pypi-publish` (v1.14.1) with
   `skip-existing: true` — no long-lived token.
5. **GitHub Release** via `softprops/action-gh-release` (v3.0.2), `draft:
   false`, `prerelease: false`, `files: dist/*`.
6. Concurrency: group `publish-<tag-ref>`, `cancel-in-progress: true`, so
   re-pushes of the same tag cancel superseded runs. Timeout: 30 minutes.

**`release-drafter.yml`** is separate automation, NOT a quality gate. It runs
on pushes to `main`/`master` and PR `opened`/`reopened`/`synchronize`/`closed`,
maps labels to changelog categories via `.github/release-drafter.yml`, and
maintains a draft release for the next tag (`v$RESOLVED_VERSION`). It does not
block merges or publish anything.

**Local release** (`make release V=x.y.z`) bumps `pyproject.toml`, re-locks,
runs `make ci-trusted`, commits, tags, and pushes `master` plus the tag; the
tag then drives the remote publish workflow.

---

## 7. Gate Catalogue

Type legend: **atomic** = single analyser/guard; **composite** = aggregates
other gates; **advisory** = reports but never blocks (informational);
**session** = OpenCode plugin, not a lifecycle gate; **release-action** =
remote publishing/mutation step.

| ID | Display name | Type | Phases | Canonical target | Contextual enforcement |
|---|---|---|---|---|---|
| `session.quality-gate` | OpenCode quality-gate plugin | session | session | `.opencode/plugins/quality-gate.ts` | Blocks selected bypass additions / gate-reference removals; idle coupling warning |
| `session.pxcli-quality` | OpenCode pxcli-quality plugin | session | session | `.opencode/plugins/pxcli-quality.ts` | Appends findings to tool output; idle semgrep/pyright log |
| `session.pre-push-docs-check` | OpenCode pre-push docs reminder | session | session | `.opencode/plugins/pre-push-docs-check.ts` | Blocks first `git push`, allows second |
| `hook.pre-commit.reject-partial-staging` | Partial-staging guard | atomic | pre-commit 1 | `lefthook.yml` | Fails the commit when staged files also have unstaged edits |
| `hook.pre-commit.lint-and-validate` | Read-only linters & validators | composite | pre-commit 2 | `lefthook.yml` | Fails the commit if any of 22 parallel jobs fail |
| `hook.pre-commit.fix-formatting` | Auto-fixers (fix then format) | composite | pre-commit 3 | `lefthook.yml` | Fails the commit if a fixer errors; re-stages fixed files |
| `hook.pre-commit.lint-after-fix` | Post-fix re-run | composite | pre-commit 4 | `lefthook.yml` | Fails the commit if a fixer introduced a regression |
| `hook.pre-commit.pytest-check` | Unit tests (no coverage) | atomic | pre-commit 5 | `make test` | Fails the commit on any failing test |
| `hook.pre-push.gitleaks-detect` | Gitleaks stdin secret scan | atomic | pre-push 1 | `scripts/gitleaks_check.sh pre-push "{1}" "{2}"` | Blocks the push; fails closed when gitleaks missing/wrong version |
| `hook.pre-push.static-checks` | Static group | composite | pre-push 2 | `make agent-check-no-tests`, `make arch-check`, `make coupling-check`, `make ratchets` | Blocks the push if any member fails |
| `hook.pre-push.pytest-coverage` | Coverage enforcement | atomic | pre-push 3 | `make test-coverage` | Blocks the push below global/per-module floors |
| `hook.pre-push.property-and-advisory` | Property + sonar | composite | pre-push 4 | `make test-property-push`, `make sonar-reports` | Blocks the push on property findings or report failure |
| `hook.pre-push.mutate-diff` | Diff mutation | atomic | pre-push 5 | `make mutate-diff` | Blocks the push on surviving diff mutants |
| `hook.pre-push.safety-and-fuzz` | Safety + fuzz | composite | pre-push 6 | `make safety`, `make test-fuzz` | Blocks the push on authenticated safety failure or fuzz failure |
| `inline.*` | Inline guards/fixers | atomic | pre-commit 2/3 | `lefthook.yml` jobs | Fails the commit (see each card) |
| `make.*` | Make targets | atomic/composite | any | `Makefile` | Depends on caller (hook, workflow, on-demand) |
| `ci.ci.*` | CI jobs (17) | atomic | CI | `.github/workflows/ci.yml` | Fails the job; see each card |
| `automation.*` | Scheduled/release-drafter jobs | atomic/composite | scheduled | `.github/workflows/*.yml` | See each card |
| `release.publish-to-pypi.publish` | Publish Distribution | release-action | release | `.github/workflows/publish-to-pypi.yml` | Fails the release on version mismatch / CI / publish error |
| `test.*` | Test lanes and meta-gates | atomic | on-demand / CI | `Makefile`, `tests/` | See each card |

Full detail for every ID is in [Agent Replication Cards](#8-agent-replication-cards).

---

## 8. Agent Replication Cards

Every active gate has a card with a **stable ID** and the full field set below.
IDs are lowercase dotted identifiers matching
`^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$` and are unique. Display-name changes do not
change an ID; retired IDs are never reused; an authority-locator rename updates
the card and all references atomically.

**ID namespaces**

| Prefix | Namespace |
|---|---|
| `session.<plugin>` | OpenCode session plugin |
| `hook.pre-commit.<job>` / `hook.pre-push.<job>` | Lefthook pipeline job |
| `make.<target>` | Makefile target |
| `ci.<workflow>.<job>` | CI workflow job |
| `automation.<workflow>.<job>` | Scheduled / supporting workflow job |
| `release.<workflow>.<job>` | Release workflow job |
| `inline.<slug>` | Inline (non-Make) guard or fixer |
| `test.<lane>` | Test lane or test-enforced meta-gate |

**Card fields**

- **Purpose** — what the gate is for.
- **Authoritative source** — repository path/locator that actually controls it.
- **Canonical invocation** — the exact command (cwd and relevant environment).
- **Trigger and scope** — event/glob/changed-file rules.
- **Execution context** — platform/runtime/trust boundary.
- **Contextual enforcement** — exactly which caller/hook/job/release fails;
  merge-required status is unknown unless repository evidence exists.
- **Skip / not-applicable / tool-error semantics** — when a run is legal to
  skip, when a gate is not applicable, and how tool errors behave. *Skipped is
  never called pass.*
- **Inputs and configuration** — threshold/baseline/schema authority.
- **Ordering and concurrency** — dependencies, fail-fast, stdin ownership.
- **Outputs and evidence** — paths, schemas, retention, producer/consumer.
- **Requirements** — tool versions, credentials, network.
- **Side effects** — workspace/index/git/cache/temp/network/remote.
- **Replication checks** — pass, finding, skip, malformed/missing input, and
  tool-error cases.

### Session plugins

#### `session.quality-gate`: OpenCode quality-gate plugin

- **Purpose:** Prevent an OpenCode agent from loosening quality infrastructure:
  block edits/writes that add bypass patterns, remove enumerated gate
  references, or drop severity levels; verify coupling still passes after
  protected changes.
- **Authoritative source:** `.opencode/plugins/quality-gate.ts`; registration in
  `opencode.jsonc` `plugin` array; override `OPENCODE_DISABLE_QUALITY_GATE`.
- **Canonical invocation:** loaded by OpenCode from `opencode.jsonc`; validated
  via `make opencode-check` (see `make.opencode-check`).
- **Trigger and scope:** `tool.execute.before` for `write`, `edit`, and
  `apply_patch` when the target file is protected (`scripts/` directory or
  `Makefile`); `event: session.idle` when `git status --porcelain -- scripts/
  Makefile` is non-empty.
- **Execution context:** local OpenCode session; Bun runtime; no CI role.
- **Contextual enforcement:** throws (blocks) the tool call for the specific
  bypass/reference-removal; logs a warning and `coupling-check` result on idle.
  It is NOT a general semantic proof that every Make target remains wired, and
  it is NOT a security boundary.
- **Skip semantics:** whole plugin disabled when
  `OPENCODE_DISABLE_QUALITY_GATE=1`. Non-protected files are ignored. Suppression
  lines matching the justified-format (`# nosec B404 — reason`, `# pragma: no
  cover — reason`, `# type: ignore[...] — reason`) are not treated as new
  bypasses.
- **Inputs and configuration:** `BYPASS_PATTERNS` (`--exclude`, `--exclude-rule`,
  `# nosec`, `# pragma: no cover`, `# type: ignore`); `GATE_REFERENCES`
  (`--max-flagged`, `--min-coverage`, `--min-confidence`, `fail_under`,
  `radon cc|mi ... -n`, `$(MIN_COVERAGE)`, `$(MIN_CONFIDENCE)`, `$(MAX_FLAGGED)`,
  `$(SEMGREP_SEVERITY)`); `PROTECTED_DIRS = ["scripts/", "Makefile"]`.
- **Ordering and concurrency:** hook runs before the tool executes (block) and
  after the turn on idle (verify). No stdin.
- **Outputs and evidence:** OpenCode app logs (service `quality-gate`); blocked
  errors carry the override hint.
- **Requirements:** OpenCode with the `@opencode-ai/plugin` runtime;
  `make coupling-check` must be invocable for the idle check.
- **Side effects:** none on the repository; runs `git status`/`make
  coupling-check` read-only.
- **Replication checks:** write/edit/apply_patch adding each bypass; severity
  reduction; removal of each gate reference; justified suppression passthrough;
  protected vs unprotected path; idle behaviour with/without protected
  modifications; `OPENCODE_DISABLE_QUALITY_GATE=1`.

#### `session.pxcli-quality`: OpenCode pxcli-quality plugin

- **Purpose:** Real-time quality feedback inside an OpenCode session: inject
  coding conventions, run per-file checks after Python edits, run pinned Safety
  after dependency edits, and run immutable Semgrep + pyright on idle for files
  recorded by those tools.
- **Authoritative source:** `.opencode/plugins/pxcli-quality.ts`; registration in
  `opencode.jsonc`.
- **Canonical invocation:** loaded by OpenCode; validated via
  `make opencode-check`.
- **Trigger and scope:** `experimental.chat.system.transform` (every chat);
  `tool.execute.after` for `write` and `edit` **only** — `apply_patch` changes
  are NOT recorded (they rely on Lefthook/Make); `event: session.idle` for
  semgrep + pyright over the session's recorded Python files.
- **Execution context:** local OpenCode session; Bun runtime; no CI role.
- **Contextual enforcement:** appends `--- Quality Check ---` findings to the
  tool output (ruff/radon/bandit/ty after Python edits; safety after
  `pyproject.toml`/`requirements*.txt` edits) and logs idle findings. Findings
  are advisory to the model, not hard blocks.
- **Skip semantics:** skipped paths (`/tests/`, `/test_`, `conftest.py`,
  `vulture_whitelist.py`, `_fuzz_harnesses.py`); non-Python/non-dependency
  files. Tool and parser failures become visible `TOOL_FAILURE` error findings
  and mark that tool unavailable for the session.
- **Inputs and configuration:** conventions block (embedded); `SKIPPED_PATHS`;
  `DEPENDENCY_FILES`; pinned Safety `uvx --from safety==3.8.1 safety scan`;
  `make semgrep-json SEMGREP_TARGETS=...` for idle semgrep; `uv run pyright
  --outputjson` for idle pyright.
- **Ordering and concurrency:** per-file tools run in parallel (`Promise.all`);
  idle semgrep + pyright run in parallel. No stdin.
- **Outputs and evidence:** OpenCode tool-output append and app logs (service
  `pxcli-quality`).
- **Requirements:** the toolset (`ruff`, `radon`, `bandit`, `ty`, `safety`,
  `semgrep`, `pyright`) resolvable through `uv run`/`uvx`; network for
  `uvx --from safety==3.8.1` on first use.
- **Side effects:** none on the repository; reads files, writes nothing.
- **Replication checks:** conventions injection; parallel per-file findings;
  dependency-safety trigger; `apply_patch` non-recording; idle semgrep/pyright;
  tool-unavailable handling.

#### `session.pre-push-docs-check`: OpenCode pre-push docs reminder

- **Purpose:** Remind an agent, in-session, to verify CLI `--help` text and
  `README.md` are consistent with changes before pushing.
- **Authoritative source:** `.opencode/plugins/pre-push-docs-check.ts`;
  registration in `opencode.jsonc`; characterisation tests in
  `.opencode/tests/pre-push-docs-check.test.ts`.
- **Canonical invocation:** loaded by OpenCode; validated via
  `make opencode-check`.
- **Trigger and scope:** `tool.execute.before` for `bash` commands matching the
  `\bgit\s+push\b` regex.
- **Execution context:** local OpenCode session; Bun runtime; no CI role.
- **Contextual enforcement:** an alternating in-session reminder. First
  recognised push attempt is blocked (error with the docs checklist); the next
  recognised attempt is allowed and the reminder resets; the following attempt
  blocks again. It does NOT observe whether a review occurred or whether an
  allowed push succeeded.
- **Skip semantics:** non-`bash` tools and non-matching commands are ignored.
- **Inputs and configuration:** `GIT_PUSH_RE`; the embedded `DOCS_CHECK_MESSAGE`.
- **Ordering and concurrency:** per-hook sequential state machine; no stdin.
- **Outputs and evidence:** OpenCode app logs (service `pre-push-docs-check`).
- **Requirements:** OpenCode runtime only.
- **Side effects:** none.
- **Replication checks:** non-Bash pass-through; non-matching Bash pass-through;
  first matching block; second matching allow+reset; third matching block.

### Pre-commit stage cards

#### `hook.pre-commit.reject-partial-staging`: Partial-staging guard

- **Purpose:** Reject a commit when a staged file also has unstaged
  modifications, so a fixer cannot re-stage and silently mask a partial edit.
- **Authoritative source:** `lefthook.yml` pre-commit stage 1 (inline shell).
- **Canonical invocation:** run by Lefthook on `pre-commit`; equivalent shell:
  stage files via `git diff --cached --name-only --diff-filter=ACMR`, then
  require `git diff --quiet -- <staged>`.
- **Trigger and scope:** every commit, before any fixer runs.
- **Execution context:** local git repository; no CI role.
- **Contextual enforcement:** fails the commit (exit 1) listing affected files
  when any staged file has unstaged changes.
- **Skip semantics:** exits 0 when nothing is staged.
- **Inputs and configuration:** none (git index only).
- **Ordering and concurrency:** first pre-commit stage; no stdin.
- **Outputs and evidence:** stderr list of affected files.
- **Requirements:** `git`.
- **Side effects:** none.
- **Replication checks:** clean index passes; partial staging fails; empty index
  passes.

#### `hook.pre-commit.lint-and-validate`: Read-only linters and validators

- **Purpose:** Run all cheap deterministic checks on the original staged content
  before any fixer runs.
- **Authoritative source:** `lefthook.yml` pre-commit stage 2 (parallel group).
- **Canonical invocation:** run by Lefthook on `pre-commit`; each job is one
  row below.
- **Trigger and scope:** every commit; each job gates on its glob.
- **Execution context:** local git repository; delegated Make targets are the
  same ones CI uses.
- **Contextual enforcement:** any job failure fails the commit. The whole group
  is parallel; Lefthook reports all failures.
- **Skip semantics:** jobs not matching a staged file's glob do not run (e.g.
  `Makefile` jobs only on `Makefile` changes); `infisical-scan` and
  `check-env-files` always run.
- **Ordering and concurrency:** parallel (`parallel: true`); no stdin.
- **Inputs and configuration:** globs and commands below; thresholds from
  `quality/gates.conf`/`pyproject.toml` via the delegated Make targets.

| Lefthook job | glob | Command |
|---|---|---|
| `ruff-check` | `*.py` | `make lint` |
| `pyright-check` | `*.py` | `make typecheck-pyright` |
| `ty-check` | `*.py` | `make typecheck` |
| `bandit` | `*.py` | `make bandit` |
| `vulture` | `*.py` | `make vulture` |
| `radon-cc` | `*.py` | `make complexity-cc` |
| `radon-mi` | `*.py` | `make complexity-mi` |
| `semgrep` | `*.{py,yml,yaml,ts}` | `make semgrep` |
| `opencode-check` | `{.opencode/**/*.ts,.opencode/**/*.json,.opencode/**/*.md,opencode.jsonc}` | `make opencode-check` |
| `make-recipe-syntax` | `Makefile` | `make -n safety-gate \| bash -n` |
| `shell-syntax` | `scripts/*.sh` | `bash -n {staged_files}` |
| `workflow-policy` | `.github/workflows/*.{yml,yaml}` | `uv run pytest tests/test_workflow_configuration.py -q` |
| `check-yaml` | `*.{yml,yaml}` | `uvx --from pre-commit-hooks check-yaml {staged_files}` |
| `check-json` | `*.json` | `uvx --from pre-commit-hooks check-json {staged_files}` |
| `check-toml` | `*.toml` | `uvx --from pre-commit-hooks check-toml {staged_files}` |
| `check-env-files` | — | inline: block newly added `.env` files |
| `check-added-large-files` | — | `uvx --from pre-commit-hooks check-added-large-files --maxkb=1000 {staged_files}` |
| `check-merge-conflict` | — | `uvx --from pre-commit-hooks check-merge-conflict {staged_files}` |
| `check-case-conflict` | — | `uvx --from pre-commit-hooks check-case-conflict {staged_files}` |
| `check-docstring-first` | `*.py` | `uvx --from pre-commit-hooks check-docstring-first {staged_files}` |
| `name-tests-test` | `tests/**/*.py` | `uvx --from pre-commit-hooks name-tests-test --pytest-test-first {staged_files}` |
| `infisical-scan` | — | `make infisical-scan` |

- **Outputs and evidence:** terminal output per job.
- **Requirements:** uv environment; `uvx` cache for pre-commit-hooks; `gitleaks`
  NOT required here; `infisical` optional (see `make.infisical-scan`).
- **Side effects:** none (read-only); tool caches (`__pycache__`,
  `.ruff_cache`) may update.
- **Replication checks:** each row's command runs and passes on clean staged
  content; a deliberately broken `.env`/large file/merge-conflict is rejected;
  glob selection.

#### `hook.pre-commit.fix-formatting`: Auto-fixers (fix then format)

- **Purpose:** Auto-fix staged files and re-stage them, in a fixed order so
  formatting is applied to already-fixed code.
- **Authoritative source:** `lefthook.yml` pre-commit stage 3 (piped group).
- **Canonical invocation:** run by Lefthook on `pre-commit`; jobs run in this
  exact order, each with `stage_fixed: true`:

| Job | glob | Command |
|---|---|---|
| `ruff-check-fix` | `*.py` | `uv run ruff check --fix {staged_files}` |
| `ruff-format` | `*.py` | `uv run ruff format {staged_files}` |
| `trailing-whitespace` | — | `uvx --from pre-commit-hooks trailing-whitespace-fixer {staged_files}` |
| `end-of-file-fixer` | — | `uvx --from pre-commit-hooks end-of-file-fixer {staged_files}` |

- **Trigger and scope:** every commit whose staged files match a glob.
- **Execution context:** local git repository; git-specific re-staging cannot be
  expressed in the Makefile, so these are inline.
- **Contextual enforcement:** any fixer failure fails the commit; the whole
  stage aborts and later fixers do not run.
- **Skip semantics:** jobs not matching staged files do not run.
- **Ordering and concurrency:** **piped** (`piped: true`) — sequential, one
  mutating tool at a time. `ruff check --fix` runs before `ruff format`.
- **Inputs and configuration:** Ruff config from `pyproject.toml`
  (`[tool.ruff]`, target py312, line length 100).
- **Outputs and evidence:** re-staged files in the git index; terminal output.
- **Requirements:** uv environment; uvx cache.
- **Side effects:** **writes the working tree and the git index** for matched
  files.
- **Replication checks:** fix-then-format order; re-staging; a file with a
  fixable lint + format issue ends canonical after both jobs.

#### `hook.pre-commit.lint-after-fix`: Post-fix re-run

- **Purpose:** Re-run the read-only linters on the fixed content to catch a
  regression a fixer introduced (e.g. an unused import removed mid-expression,
  or a fix that pushes complexity over a radon threshold).
- **Authoritative source:** `lefthook.yml` pre-commit stage 4 (parallel group).
- **Canonical invocation:** run by Lefthook on `pre-commit`.
- **Trigger and scope:** every commit, after stage 3.
- **Execution context:** local git repository.
- **Contextual enforcement:** any re-run failure fails the commit.
- **Skip semantics:** glob-gated like stage 2.
- **Ordering and concurrency:** parallel group of 8 jobs: `ruff-check-rerun`
  (`make lint`), `pyright-check-rerun` (`make typecheck-pyright`),
  `ty-check-rerun` (`make typecheck`), `bandit-rerun` (`make bandit`),
  `vulture-rerun` (`make vulture`), `radon-cc-rerun` (`make complexity-cc`),
  `radon-mi-rerun` (`make complexity-mi`), `semgrep-rerun` (`make semgrep`).
  No stdin.
- **Inputs and configuration:** same delegated Make targets as stage 2.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (read-only).
- **Replication checks:** a fixer-induced regression is detected here; clean
  fix passes.

#### `hook.pre-commit.pytest-check`: Unit tests (no coverage)

- **Purpose:** Run the safe ordinary test suite before a commit is created,
  after all static/fixer gates pass.
- **Authoritative source:** `lefthook.yml` pre-commit stage 5; recipe
  `make test`.
- **Canonical invocation:** `make test`
  (`uv run pytest tests/ -q --tb=line -x -n auto -m "not property and not
  hermetic_integration and not real_api and not manual and not real_user_config
  and not fuzz"`).
- **Trigger and scope:** every commit that passes stages 1-4.
- **Execution context:** local git repository.
- **Contextual enforcement:** any failing test fails the commit (`-x`
  fail-fast).
- **Skip semantics:** marker exclusions above; coverage enforcement is deferred
  to pre-push.
- **Ordering and concurrency:** single job; pytest-xdist `-n auto`; no stdin.
- **Inputs and configuration:** marker set from `pyproject.toml`; exclusions in
  the Make recipe (see the `make.test` card).
- **Outputs and evidence:** terminal output; `.pytest_cache`.
- **Requirements:** uv environment with dev deps.
- **Side effects:** `.pytest_cache`, `__pycache__`.
- **Replication checks:** pass on clean tree; failing test blocks commit.

### Pre-push stage cards

#### `hook.pre-push.gitleaks-detect`: Gitleaks stdin secret scan

- **Purpose:** Scan the exact commits being pushed (and, for new refs, commits
  not reachable from advertised remote refs) for secrets, as the sole consumer
  of the git push stdin pipe.
- **Authoritative source:** `lefthook.yml` pre-push stage 1;
  `scripts/gitleaks_check.sh` (required version logic).
- **Canonical invocation:** `scripts/gitleaks_check.sh pre-push "{1}" "{2}"`
  with `use_stdin: true`; arguments are the remote name and remote URL.
- **Trigger and scope:** every push; parses `<local-ref> <local-oid>
  <remote-ref> <remote-oid>` rows from stdin.
- **Execution context:** local git repository; scans local objects plus
  `git ls-remote` of the destination (network read).
- **Contextual enforcement:** blocks the push on secret findings (exit 10) and
  on any input/git/config/scanner error (exit 3). **Fails closed** when
  gitleaks is missing or not exactly **8.30.1**. Deleted refs are skipped
  (informational).
- **Skip semantics:** no refs on stdin or no commits to scan => exit 0
  (informational); a deleted ref is skipped. Missing/wrong gitleaks is NOT a
  skip — it fails.
- **Inputs and configuration:** `REQUIRED_GITLEAKS_VERSION=8.30.1`; gitleaks
  config (default detection rules).
- **Ordering and concurrency:** first pre-push stage; sole `use_stdin` job;
  no other job MAY set `use_stdin`.
- **Outputs and evidence:** stdout scan summary; redacted findings.
- **Requirements:** gitleaks 8.30.1 on `PATH`; network to the remote.
- **Side effects:** network read only; nothing written.
- **Replication checks:** clean push passes; secret push fails 10; missing
  gitleaks fails 3; wrong version fails 3; malformed stdin row fails 3; new-ref
  advertisement handling; deleted ref skip.

#### `hook.pre-push.static-checks`: Static group

- **Purpose:** Run the static architecture/coupling/ratchet set and the
  read-only agent subset before the expensive coverage stage.
- **Authoritative source:** `lefthook.yml` pre-push stage 2 (parallel group).
- **Canonical invocation:** parallel jobs: `make agent-check-no-tests`,
  `make arch-check`, `make coupling-check`, `make ratchets`.
- **Trigger and scope:** every push.
- **Execution context:** local git repository.
- **Contextual enforcement:** any member failure blocks the push.
- **Skip semantics:** none (all four always run). A failure is a finding, not a
  skip.
- **Ordering and concurrency:** parallel (`parallel: true`); no stdin; runs
  after `gitleaks-detect`.
- **Inputs and configuration:** thresholds via the delegated Make targets.
- **Outputs and evidence:** terminal output per member.
- **Requirements:** uv environment; gitleaks not needed here.
- **Side effects:** none (read-only).
- **Replication checks:** each member's standalone failure blocks; clean passes.

#### `hook.pre-push.pytest-coverage`: Coverage enforcement

- **Purpose:** Enforce global and per-module coverage before a push.
- **Authoritative source:** `lefthook.yml` pre-push stage 3; `make test-coverage`.
- **Canonical invocation:** `make test-coverage` (pytest-cov + `-n auto` +
  `scripts/check_module_coverage.py`).
- **Trigger and scope:** every push.
- **Execution context:** local git repository.
- **Contextual enforcement:** blocks the push when overall `fail_under` (85) or
  any module's coverage (85) is below threshold.
- **Skip semantics:** none; missing/stale `coverage.json` handled by the
  producer inside this target.
- **Ordering and concurrency:** single stage after static-checks; no stdin.
- **Inputs and configuration:** `MIN_COVERAGE=85`, `pyproject.toml`
  `[tool.coverage]` (`branch = true`, `fail_under = 85`).
- **Outputs and evidence:** `coverage.json`, `coverage.xml`, `.coverage`,
  `coverage.xml` diff-cover consumer.
- **Requirements:** uv environment with dev deps.
- **Side effects:** writes coverage artefacts (ignored).
- **Replication checks:** clean push passes; low per-module coverage fails;
  missing branch data fails.

#### `hook.pre-push.property-and-advisory`: Property tests and sonar reports

- **Purpose:** Run the Hypothesis push profile and generate advisory Sonar
  reports.
- **Authoritative source:** `lefthook.yml` pre-push stage 4 (parallel group).
- **Canonical invocation:** parallel jobs: `make test-property-push`,
  `make sonar-reports`.
- **Trigger and scope:** every push.
- **Execution context:** local git repository.
- **Contextual enforcement:** property findings or a report-generation failure
  block the push. `sonar-reports` is advisory output; its failure blocks only
  because it cannot produce its report.
- **Skip semantics:** none for property (manifest parity is a prerequisite of
  the target).
- **Ordering and concurrency:** parallel; after coverage; no stdin.
- **Inputs and configuration:** Hypothesis `push` profile (50 examples, 500 ms
  deadline); `PROPERTY_TEST_FILES := tests/test_property.py` (Make-owned,
  `override`).
- **Outputs and evidence:** terminal output; `build/reports/bandit-report.json`.
- **Requirements:** uv environment; `hypothesis`.
- **Side effects:** `.hypothesis/` database, `build/reports/`.
- **Replication checks:** property failure blocks; report produced; manifest
  mismatch blocks via `test-property-policy` prerequisite.

#### `hook.pre-push.mutate-diff`: Diff-scoped mutation testing

- **Purpose:** Run mutmut only over production source files changed relative to
  the base branch.
- **Authoritative source:** `lefthook.yml` pre-push stage 5; `make mutate-diff`;
  `scripts/discover_mutate_diff_files.py`.
- **Canonical invocation:** `make mutate-diff`
  (defaults `BASE_SHA ?= origin/main`, `TESTED_SHA ?= HEAD`).
- **Trigger and scope:** every push; discovery uses the local worktree diff
  context.
- **Execution context:** local git repository.
- **Contextual enforcement:** blocks the push when any diff mutant survives
  (mutmut exit non-zero). No changed production source files => skip (exit 0).
- **Skip semantics:** "No source files changed" prints a skip message and exits
  0 — a genuine not-applicable, not a pass on evidence.
- **Ordering and concurrency:** single stage; no stdin.
- **Inputs and configuration:** `BASE_SHA`/`TESTED_SHA`; `[tool.mutmut]` config
  in `pyproject.toml`.
- **Outputs and evidence:** terminal output; `.mutmut-cache`.
- **Requirements:** uv environment; mutmut.
- **Side effects:** `.mutmut-cache`; runs mutmut mutations in a cache.
- **Replication checks:** no changed files skips; changed files with survivors
  block; clean diff passes.

#### `hook.pre-push.safety-and-fuzz`: Safety and fuzz

- **Purpose:** Run the authenticated Safety scan (or informational skip) and the
  fuzz lane before the push completes.
- **Authoritative source:** `lefthook.yml` pre-push stage 6 (parallel group).
- **Canonical invocation:** parallel jobs: `make safety`, `make test-fuzz`.
- **Trigger and scope:** every push.
- **Execution context:** local git repository; Safety may read credentials from
  env or Infisical.
- **Contextual enforcement:** an authenticated Safety failure (once scanning
  starts) blocks the push; fuzz failures block the push.
- **Skip semantics:** `make safety` prints an informational skip when
  credentials are unavailable — this is NOT a pass and does not block.
  `make test-fuzz` never skips on missing atheris (it fails loudly).
- **Ordering and concurrency:** parallel; last pre-push stage; no stdin.
- **Inputs and configuration:** `SAFETY_API_KEY` or Infisical `--env dev`;
  Safety pinned 3.8.1; atheris linux x86_64 only.
- **Outputs and evidence:** terminal output.
- **Requirements:** Safety needs credentials for a real scan; atheris only on
  linux x86_64.
- **Side effects:** Safety stages a copy of inputs in a temp dir; fuzz writes
  `.mutmut-cache`/harness temp state.
- **Replication checks:** credentialed scan blocks on findings; missing
  credentials skip informationally; fuzz harness failure blocks.

### Inline guards and fixers

These non-Make jobs live inline in `lefthook.yml` because they need
git-specific behaviour (staged files, index re-staging) or a tiny shell guard.
They are not duplicated in the Makefile.

#### `inline.reject-partial-staging`

- **Purpose/authoritative source:** guard that rejects commits whose staged
  files also have unstaged edits. Source: `lefthook.yml` (stage 1). See
  `hook.pre-commit.reject-partial-staging` for the full card; the card and this
  slug refer to the same inline surface, with `inline` preferred for slug
  stability.
- **Canonical invocation:** inline shell in `lefthook.yml`.
- **Trigger and scope:** every commit.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit.
- **Skip semantics:** nothing staged => pass.
- **Ordering and concurrency:** first job.
- **Inputs/outputs/requirements/side effects/replication:** as the hook card.

#### `inline.check-yaml`

- **Purpose:** validate staged YAML.
- **Authoritative source:** `lefthook.yml` job `check-yaml`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-yaml {staged_files}`.
- **Trigger and scope:** staged files matching `*.{yml,yaml}`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on invalid YAML.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** valid YAML passes; invalid fails.

#### `inline.check-json`

- **Purpose:** validate staged JSON.
- **Authoritative source:** `lefthook.yml` job `check-json`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-json {staged_files}`.
- **Trigger and scope:** staged files matching `*.json`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on invalid JSON.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** valid JSON passes; invalid fails.

#### `inline.check-toml`

- **Purpose:** validate staged TOML.
- **Authoritative source:** `lefthook.yml` job `check-toml`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-toml {staged_files}`.
- **Trigger and scope:** staged files matching `*.toml`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on invalid TOML.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** valid TOML passes; invalid fails.

#### `inline.check-env-files`

- **Purpose:** block newly added `.env` files, which are almost always
  secret-bearing.
- **Authoritative source:** `lefthook.yml` job `check-env-files`.
- **Canonical invocation:** inline shell listing added files via
  `git diff --cached --name-only --diff-filter=A` and grepping `(^|/)\.env$`.
- **Trigger and scope:** every commit.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit listing blocked files.
- **Skip semantics:** no added `.env` files => pass.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** stderr list.
- **Requirements:** git.
- **Side effects:** none.
- **Replication checks:** added `.env` fails; other files pass.

#### `inline.check-added-large-files`

- **Purpose:** reject newly added files over 1000 KiB.
- **Authoritative source:** `lefthook.yml` job `check-added-large-files`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-added-large-files --maxkb=1000 {staged_files}`.
- **Trigger and scope:** every commit.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on an oversized added file.
- **Skip semantics:** none.
- **Inputs and configuration:** `--maxkb=1000` (note: this is a KiB cap,
  unrelated to `FILE_SIZE_CAP` source-line cap).
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** large added file fails; normal additions pass.

#### `inline.check-merge-conflict`

- **Purpose:** reject staged files containing unresolved merge conflict markers.
- **Authoritative source:** `lefthook.yml` job `check-merge-conflict`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-merge-conflict {staged_files}`.
- **Trigger and scope:** every commit.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on conflict markers.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** conflict markers fail; clean files pass.

#### `inline.check-case-conflict`

- **Purpose:** reject case-insensitive filename conflicts (problematic on
  macOS/Windows).
- **Authoritative source:** `lefthook.yml` job `check-case-conflict`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-case-conflict {staged_files}`.
- **Trigger and scope:** every commit.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on a case conflict.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** conflicting names fail.

#### `inline.check-docstring-first`

- **Purpose:** require the module docstring to be the first statement.
- **Authoritative source:** `lefthook.yml` job `check-docstring-first`.
- **Canonical invocation:** `uvx --from pre-commit-hooks check-docstring-first {staged_files}`.
- **Trigger and scope:** staged `*.py` files.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on misplaced docstrings.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** misplaced docstring fails.

#### `inline.name-tests-test`

- **Purpose:** require test files/functions to be `test_*`-named
  (pytest-first).
- **Authoritative source:** `lefthook.yml` job `name-tests-test`.
- **Canonical invocation:** `uvx --from pre-commit-hooks name-tests-test --pytest-test-first {staged_files}`.
- **Trigger and scope:** staged files under `tests/**/*.py`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on a misnamed test.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** none.
- **Replication checks:** misnamed test fails.

#### `inline.make-recipe-syntax`

- **Purpose:** syntax-check the Makefile recipes.
- **Authoritative source:** `lefthook.yml` job `make-recipe-syntax`.
- **Canonical invocation:** `make -n safety-gate | bash -n`.
- **Trigger and scope:** staged `Makefile` changes.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on a recipe syntax error.
- **Skip semantics:** no `Makefile` staged => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** make, bash.
- **Side effects:** none.
- **Replication checks:** malformed recipe fails; valid passes.

#### `inline.shell-syntax`

- **Purpose:** syntax-check staged shell scripts.
- **Authoritative source:** `lefthook.yml` job `shell-syntax`.
- **Canonical invocation:** `bash -n {staged_files}`.
- **Trigger and scope:** staged `scripts/*.sh` files.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on a shell syntax error.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** bash.
- **Side effects:** none.
- **Replication checks:** malformed script fails.

#### `inline.workflow-policy`

- **Purpose:** statically validate workflow topology and policy whenever a
  workflow changes.
- **Authoritative source:** `lefthook.yml` job `workflow-policy`; tests in
  `tests/test_workflow_configuration.py`.
- **Canonical invocation:** `uv run pytest tests/test_workflow_configuration.py -q`.
- **Trigger and scope:** staged `.github/workflows/*.{yml,yaml}` files.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary; the same `tests/test_workflow_configuration.py` module also
  runs in CI as part of the ordinary suite.
- **Contextual enforcement:** fails the commit when the workflow policy tests
  fail.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** none beyond the test module.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** policy violations fail; clean passes.

#### `inline.ruff-check-fix`

- **Purpose:** auto-fix staged Python with `ruff check --fix`.
- **Authoritative source:** `lefthook.yml` stage 3 job `ruff-check-fix`.
- **Canonical invocation:** `uv run ruff check --fix {staged_files}`,
  `stage_fixed: true`.
- **Trigger and scope:** staged `*.py` files.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit if ruff errors; re-stages fixed
  files.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** `[tool.ruff]` from `pyproject.toml`.
- **Ordering and concurrency:** FIRST stage-3 fixer (before `ruff format`).
- **Outputs and evidence:** re-staged files.
- **Requirements:** uv environment.
- **Side effects:** writes working tree and index.
- **Replication checks:** fixable violation is fixed and re-staged.

#### `inline.ruff-format`

- **Purpose:** format staged Python with `ruff format`.
- **Authoritative source:** `lefthook.yml` stage 3 job `ruff-format`.
- **Canonical invocation:** `uv run ruff format {staged_files}`,
  `stage_fixed: true`.
- **Trigger and scope:** staged `*.py` files.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit if formatting errors; re-stages.
- **Skip semantics:** no matching staged files => not run.
- **Inputs and configuration:** `[tool.ruff.format]` from `pyproject.toml`.
- **Ordering and concurrency:** SECOND stage-3 fixer (after `ruff check --fix`).
- **Outputs and evidence:** re-staged files.
- **Requirements:** uv environment.
- **Side effects:** writes working tree and index.
- **Replication checks:** unformatted file is formatted and re-staged.

#### `inline.trailing-whitespace`

- **Purpose:** strip trailing whitespace from staged files.
- **Authoritative source:** `lefthook.yml` stage 3 job `trailing-whitespace`.
- **Canonical invocation:** `uvx --from pre-commit-hooks trailing-whitespace-fixer {staged_files}`, `stage_fixed: true`.
- **Trigger and scope:** every commit (all staged files).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on tool error; re-stages.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** THIRD stage-3 fixer.
- **Outputs and evidence:** re-staged files.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** writes working tree and index.
- **Replication checks:** trailing whitespace removed and re-staged.

#### `inline.end-of-file-fixer`

- **Purpose:** ensure files end with exactly one newline.
- **Authoritative source:** `lefthook.yml` stage 3 job `end-of-file-fixer`.
- **Canonical invocation:** `uvx --from pre-commit-hooks end-of-file-fixer {staged_files}`, `stage_fixed: true`.
- **Trigger and scope:** every commit (all staged files).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit on tool error; re-stages.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** FOURTH stage-3 fixer.
- **Outputs and evidence:** re-staged files.
- **Requirements:** network for `uvx` on first use.
- **Side effects:** writes working tree and index.
- **Replication checks:** missing EOF newline fixed and re-staged.

### Make target cards

The Makefile is the canonical command layer. All atomic gates and composites
below have cards. Recipe text in the Makefile is authoritative; the card
documents how to reproduce it and what it means.

#### `make.check-uv`: Verify uv is installed

- **Purpose:** fail fast when `uv` is missing so `make setup` cannot proceed.
- **Authoritative source:** `Makefile` `check-uv`.
- **Canonical invocation:** `make check-uv`.
- **Trigger and scope:** prerequisite of `make setup`; on-demand.
- **Execution context:** any local shell; no CI role.
- **Contextual enforcement:** exits 1 with an install hint when `uv` is absent.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** stdout install hint on failure.
- **Requirements:** `uv` on `PATH` (documented install:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- **Side effects:** none.
- **Replication checks:** present => exit 0; absent => exit 1 + hint.

#### `make.check-gitleaks`: Verify gitleaks is installed

- **Purpose:** fail fast when gitleaks is missing before setup/scanning.
- **Authoritative source:** `Makefile` `check-gitleaks`.
- **Canonical invocation:** `make check-gitleaks`.
- **Trigger and scope:** prerequisite of `make setup`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 1 with an install hint when gitleaks is
  absent. (Note: this only checks presence; the exact **8.30.1** version
  requirement is enforced by `scripts/gitleaks_check.sh`.)
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** stdout hint on failure.
- **Requirements:** gitleaks on `PATH`.
- **Side effects:** none.
- **Replication checks:** present => exit 0; absent => exit 1.

#### `make.check-infisical`: Verify infisical is installed

- **Purpose:** fail fast when the Infisical CLI is missing.
- **Authoritative source:** `Makefile` `check-infisical`.
- **Canonical invocation:** `make check-infisical`.
- **Trigger and scope:** prerequisite of `make setup`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 1 with an install hint when `infisical` is
  absent.
- **Skip semantics:** none (setup requires it, even though the pre-commit scan
  itself degrades gracefully when the CLI is missing later).
- **Inputs and configuration:** none.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** stdout hint on failure.
- **Requirements:** infisical CLI on `PATH`.
- **Side effects:** none.
- **Replication checks:** present => exit 0; absent => exit 1.

#### `make.setup`: Bootstrap the development environment

- **Purpose:** create the venv, sync locked deps, install lefthook hooks, verify
  the dev CLI.
- **Authoritative source:** `Makefile` `setup`.
- **Canonical invocation:** `make setup` (prerequisites `check-uv`,
  `check-gitleaks`, `check-infisical`).
- **Trigger and scope:** one-time/on-demand; idempotent.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails at the first missing prerequisite; recipe
  steps fail on error.
- **Skip semantics:** none; re-runs are safe (idempotent).
- **Inputs and configuration:** `PYTHON_VERSION ?= 3.12`; `--locked` uses
  `uv.lock`.
- **Ordering and concurrency:** sequential recipe.
- **Outputs and evidence:** `.venv/`, synced lockfile state, lefthook hook
  install.
- **Requirements:** uv, gitleaks, infisical on `PATH`; network for dependency
  fetch.
- **Side effects:** creates `.venv/`; writes to uv cache; installs git hooks.
- **Replication checks:** clean bootstrap; missing prerequisite aborts;
  re-run no-ops.

#### `make.configure-opencode`: Reproducibly install and validate OpenCode plugins/config

- **Purpose:** `npm ci`, run the full `opencode-check`, and verify the three
  plugin files plus `opencode.jsonc` exist.
- **Authoritative source:** `Makefile` `configure-opencode`.
- **Canonical invocation:** `make configure-opencode`.
- **Trigger and scope:** on-demand; after plugin/config changes.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 1 if `npm ci` fails, `opencode-check` fails,
  or any registered plugin/config file is missing.
- **Skip semantics:** none (idempotent).
- **Inputs and configuration:** `.opencode/package.json` +
  `package-lock.json`; the three plugin filenames.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** `.opencode/node_modules/`; verification output.
- **Requirements:** npm/node; network on first install.
- **Side effects:** writes `.opencode/node_modules/`.
- **Replication checks:** clean install passes; missing plugin fails; broken
  config fails.

#### `make.opencode-check`: Lint, test, type-check OpenCode plugins and validate config

- **Purpose:** offline validation of OpenCode plugins and configuration.
- **Authoritative source:** `Makefile` `opencode-check`;
  `.opencode/package.json` (`check` = `lint && test && typecheck &&
  check:config`); `.opencode/scripts/check-config.ts`.
- **Canonical invocation:** `make opencode-check`.
- **Trigger and scope:** on-demand; pre-commit stage 2 on OpenCode file globs;
  CI `static` job.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller (commit/job) on any ESLint,
  Vitest, `tsc`, or config-check failure.
- **Skip semantics:** the `opencode debug config` resolved-config step is
  skipped with a notice when the OpenCode CLI is not installed.
- **Inputs and configuration:** `check-config.ts` validates ONLY: schema URL
  equals `https://opencode.ai/config.json`, `plugin` is a non-empty array of
  strings with prefix `.opencode/plugins/`, and each registered path exists.
- **Ordering and concurrency:** sequential sub-steps.
- **Outputs and evidence:** terminal output.
- **Requirements:** npm dependencies installed.
- **Side effects:** none (read-only).
- **Replication checks:** valid config passes; wrong schema URL fails; bad
  plugin shape fails; missing plugin file fails; CLI-absent skip notice.

#### `make.opencode-audit`: npm audit for OpenCode dependencies

- **Purpose:** fail on high/critical npm vulnerabilities in `.opencode`.
- **Authoritative source:** `Makefile` `opencode-audit`.
- **Canonical invocation:** `make opencode-audit`
  (`npm --prefix .opencode audit --audit-level=high`).
- **Trigger and scope:** on-demand; CI `static` job.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 0 no high/critical; exit 1 when found; exit 2
  on infrastructure error.
- **Skip semantics:** none.
- **Inputs and configuration:** `package-lock.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** npm; network (registry).
- **Side effects:** network read.
- **Replication checks:** clean => 0; vulnerabilities => 1; registry error => 2.

#### `make.format-check`: Ruff format check

- **Purpose:** verify formatting of `src tests scripts`.
- **Authoritative source:** `Makefile` `format-check`.
- **Canonical invocation:** `uv run ruff format --check src tests scripts`.
- **Trigger and scope:** member of `make check`, `make ci-static`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on formatting drift.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.ruff.format]` (line length 100).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** formatted => 0; unformatted => 1.

#### `make.format-fix`: Ruff format + lint fix

- **Purpose:** auto-fix formatting and lint in `src tests scripts`.
- **Authoritative source:** `Makefile` `format-fix`.
- **Canonical invocation:** `make format-fix` (`ruff format` then
  `ruff check --fix`).
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on error.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.ruff]`.
- **Ordering and concurrency:** format first, then fix.
- **Outputs and evidence:** rewritten files.
- **Requirements:** uv environment.
- **Side effects:** **writes-working-tree** for `src/`, `tests/`, `scripts/`.
- **Replication checks:** dirty files become clean and fixed.

#### `make.lint`: Ruff lint

- **Purpose:** `ruff check` over `src tests scripts`.
- **Authoritative source:** `Makefile` `lint`.
- **Canonical invocation:** `uv run ruff check src tests scripts`.
- **Trigger and scope:** pre-commit stage 2 `ruff-check`/stage 4
  `ruff-check-rerun`; `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on lint findings.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.ruff.lint]` (select/ignore/per-file-ignores).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; findings => 1.

#### `make.typecheck`: ty type checker

- **Purpose:** run `ty` over `src/`.
- **Authoritative source:** `Makefile` `typecheck`.
- **Canonical invocation:** `uv run ty check src`.
- **Trigger and scope:** pre-commit stage 2 `ty-check`/stage 4 `ty-check-rerun`;
  `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on type errors.
- **Skip semantics:** none.
- **Inputs and configuration:** none (ty has no config file).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; errors => 1.

#### `make.typecheck-pyright`: Pyright strict type checker

- **Purpose:** run strict Pyright over `src/`.
- **Authoritative source:** `Makefile` `typecheck-pyright`; `[tool.pyright]`
  (strict mode, Python 3.12).
- **Canonical invocation:** `uv run pyright src/`.
- **Trigger and scope:** pre-commit stage 2 `pyright-check`/stage 4
  `pyright-check-rerun`; `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on diagnostics.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.pyright]` with `typeCheckingMode =
  "strict"`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; diagnostics => 1.

#### `make.typecheck-scripts`: Pyright strict on quality scripts

- **Purpose:** run strict Pyright over `scripts/`.
- **Authoritative source:** `Makefile` `typecheck-scripts`; analyser contract
  `typecheck-scripts`.
- **Canonical invocation:** `uv run pyright scripts/`.
- **Trigger and scope:** member of `make typecheck-all` (`make check`,
  `make ci-static`).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on script diagnostics.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.pyright]` (strict).
- **Ordering and concurrency:** within `typecheck-all`.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; diagnostics => 1.

#### `make.typecheck-all`: All type checkers

- **Purpose:** run ty + pyright + pyright-scripts.
- **Authoritative source:** `Makefile` `typecheck-all`.
- **Canonical invocation:** `make typecheck-all`.
- **Trigger and scope:** `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller if any checker fails.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential prerequisites.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** each member behaves as documented.

#### `make.bandit`: Bandit security linter

- **Purpose:** scan `src/` and `scripts/` for security issues.
- **Authoritative source:** `Makefile` `bandit`; `[tool.bandit]`.
- **Canonical invocation:** `uv run bandit -c pyproject.toml -r src/ scripts/`.
- **Trigger and scope:** pre-commit stage 2 `bandit`/stage 4 `bandit-rerun`;
  `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on findings.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.bandit]` (excludes `tests`; no global
  rule skips).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; findings => 1.

#### `make.vulture`: Vulture dead-code detector

- **Purpose:** detect likely unused code in `src/`.
- **Authoritative source:** `Makefile` `vulture`; `[tool.vulture]`.
- **Canonical invocation:** `uv run vulture src/ vulture_whitelist.py --min-confidence $(MIN_CONFIDENCE)`.
- **Trigger and scope:** pre-commit stage 2 `vulture`/stage 4 `vulture-rerun`;
  `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on dead-code findings.
- **Skip semantics:** none.
- **Inputs and configuration:** `MIN_CONFIDENCE=80` from `quality/gates.conf`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; findings => 1.

#### `make.security`: Security composite

- **Purpose:** run bandit + vulture.
- **Authoritative source:** `Makefile` `security`.
- **Canonical invocation:** `make security`.
- **Trigger and scope:** `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller if either member fails.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** members behave as documented.

#### `make.complexity-cc`: Cyclomatic complexity check

- **Purpose:** reject functions graded B or worse (only A passes).
- **Authoritative source:** `Makefile` `complexity-cc`; `RADON_CC_GRADE`.
- **Canonical invocation:** `uv run radon cc src/ -s -n $(RADON_CC_GRADE)`; fails
  when output is non-empty.
- **Trigger and scope:** pre-commit stage 2 `radon-cc`/stage 4 `radon-cc-rerun`;
  `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller when any block reports grade B or
  worse.
- **Skip semantics:** none.
- **Inputs and configuration:** `RADON_CC_GRADE = B`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; B-or-worse block => 1.

#### `make.complexity-mi`: Maintainability index check

- **Purpose:** reject modules graded B or worse (only A passes).
- **Authoritative source:** `Makefile` `complexity-mi`; `RADON_MI_GRADE`.
- **Canonical invocation:** `uv run radon mi src/ -s -n $(RADON_MI_GRADE)`; fails
  when output is non-empty.
- **Trigger and scope:** pre-commit stage 2 `radon-mi`/stage 4 `radon-mi-rerun`;
  `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller when any module reports grade B or
  worse.
- **Skip semantics:** none.
- **Inputs and configuration:** `RADON_MI_GRADE = B`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; B-or-worse module => 1.

#### `make.complexity`: Complexity composite

- **Purpose:** run radon CC + MI.
- **Authoritative source:** `Makefile` `complexity`.
- **Canonical invocation:** `make complexity`.
- **Trigger and scope:** `make check`, `make ci-static`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller if either member fails.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** members behave as documented.

#### `make.semgrep`: Blocking immutable Semgrep ruleset

- **Purpose:** run the pinned Semgrep 1.171.0 ruleset through the policy wrapper
  in blocking mode.
- **Authoritative source:** `Makefile` `semgrep`; `scripts/semgrep_policy.py`;
  `quality/semgrep-policy.toml`; `quality/semgrep-snapshot.json`;
  `.semgrep.yml` + `.semgrep-community-*.yml`.
- **Canonical invocation:** `uv run python scripts/semgrep_policy.py --blocking
  $(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS) $(SEMGREP_TARGETS)`, where
  `SEMGREP_OPTIONS` expands `$(SEMGREP_SEVERITY)` plus excludes `tests/`,
  `.semgrep-community-*.yml`, `.github/`; `SEMGREP_TARGETS ?= .`.
- **Trigger and scope:** pre-commit stage 2/4 `semgrep`/`semgrep-rerun`;
  `make check`; CI `static` job; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on blocking findings (exit 1) or
  scanner/config/tool errors (exit 2-5). Unknown rules default to blocking.
- **Skip semantics:** none. Severity filter is ERROR+WARNING.
- **Inputs and configuration:** severity from `SEMGREP_SEVERITY`; policy manifest
  declares per-rule blocking; immutable community snapshots pinned by SHA in
  `quality/semgrep-snapshot.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal summary of blocking/advisory findings.
- **Requirements:** pinned semgrep 1.171.0 via `uvx`; network on first fetch.
- **Side effects:** network read for tool fetch.
- **Replication checks:** clean => 0; blocking finding => 1; malformed JSON =>
  2; timeout => 3; missing config => 4; internal/errors => 5.

#### `make.semgrep-json`: Machine-readable immutable Semgrep

- **Purpose:** emit JSON for the immutable ruleset (used by session idle
  analysis).
- **Authoritative source:** `Makefile` `semgrep-json`.
- **Canonical invocation:** `$(SEMGREP) $(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS)
  --json $(SEMGREP_TARGETS)`.
- **Trigger and scope:** on-demand; consumed by
  `session.pxcli-quality` idle check via
  `make semgrep-json SEMGREP_TARGETS=<files>`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** non-zero exit on findings or scanner error.
- **Skip semantics:** none.
- **Inputs and configuration:** same as `make.semgrep`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** JSON on stdout.
- **Requirements:** pinned semgrep 1.171.0.
- **Side effects:** network read for tool fetch.
- **Replication checks:** JSON parseable; findings exit 1.

#### `make.semgrep-advisory`: Latest community packs (advisory)

- **Purpose:** scan the LATEST `p/python`, `p/comment`, `p/r2c-best-practices`
  packs non-blocking (no snapshot pinning).
- **Authoritative source:** `Makefile` `semgrep-advisory`.
- **Canonical invocation:** `uvx semgrep --config p/python --config p/comment
  --config p/r2c-best-practices $(SEMGREP_SEVERITY) --exclude tests/
  --metrics=off .`.
- **Trigger and scope:** on-demand; pre-push NOT wired; scheduled job uses
  `semgrep-advisory-report` instead.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** advisory only — findings do not fail.
- **Skip semantics:** none.
- **Inputs and configuration:** latest remote packs; severity ERROR+WARNING.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** semgrep via `uvx`; network.
- **Side effects:** network read.
- **Replication checks:** findings reported as advisory.

#### `make.semgrep-advisory-local`: Custom advisory rules via wrapper

- **Purpose:** run the immutable custom/community configs through the policy
  wrapper in advisory mode.
- **Authoritative source:** `Makefile` `semgrep-advisory-local`.
- **Canonical invocation:** `uv run python scripts/semgrep_policy.py --advisory
  $(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS) $(SEMGREP_TARGETS)`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** never fails on findings; may fail on scanner/tool
  errors.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.semgrep`, advisory mode.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal summary.
- **Requirements:** pinned semgrep 1.171.0.
- **Side effects:** network read for tool fetch.
- **Replication checks:** findings reported, exit 0.

#### `make.semgrep-advisory-report`: Advisory Semgrep JSON + SARIF report

- **Purpose:** emit `build/reports/semgrep-advisory.{json,sarif}` from the
  latest community packs for the scheduled workflow.
- **Authoritative source:** `Makefile` `semgrep-advisory-report`;
  `semgrep-advisory.yml`.
- **Canonical invocation:** `make semgrep-advisory-report` (creates
  `build/reports`, runs `uvx semgrep --config p/python --config p/comment
  --config p/r2c-best-practices $(SEMGREP_SEVERITY) --exclude tests/
  --metrics=off --json-output=... --sarif-output=... .`).
- **Trigger and scope:** scheduled `automation.semgrep-advisory.semgrep-advisory`
  (Tuesday 07:00) and manual dispatch.
- **Execution context:** Local developer workstation; repository checkout; also runs in the
  scheduled workflow (`automation.semgrep-advisory.semgrep-advisory`); untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** findings (exit 1) are advisory; scanner errors
  propagate and can fail the job.
- **Skip semantics:** none.
- **Inputs and configuration:** latest remote packs.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `build/reports/semgrep-advisory.json`,
  `build/reports/semgrep-advisory.sarif` (uploaded as artefacts and to code
  scanning under `semgrep-advisory`).
- **Requirements:** semgrep via `uvx`; network.
- **Side effects:** writes `build/reports/`.
- **Replication checks:** report files exist; findings advisory; scanner error
  fails.

#### `make.arch-check`: Architecture layer check

- **Purpose:** enforce ports-and-adapters layer rules: import direction, adapter
  independence, framework isolation, and complete classification.
- **Authoritative source:** `Makefile` `arch-check`; `scripts/check_architecture.py`;
  `quality/architecture.toml`; `.architecture-baseline.json`.
- **Canonical invocation:** `uv run python scripts/check_architecture.py`.
- **Trigger and scope:** pre-push `static-checks`; `make check`; CI `static`;
  on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller (exit 1) when any active error OR
  warning remains after baseline filtering. **Baseline-aware by default**:
  `.architecture-baseline.json` is applied unless `--no-baseline`.
- **Skip semantics:** none; baseline-accepted violations are not findings.
- **Inputs and configuration:** `quality/architecture.toml` layer/adapter model;
  baseline at repository root. Warnings also fail — not just errors.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report (active vs accepted counts).
- **Requirements:** uv environment.
- **Side effects:** none (read-only).
- **Replication checks:** new violation fails; baseline-accepted violation passes;
  `--update-baseline` records current violations; `--no-baseline` shows all.

#### `make.arch-check-dynamic`: Dynamic-import architecture enforcement

- **Purpose:** detect runtime import-resolution calls (`importlib.import_module`,
  `__import__`) that circumvent static import checks; every dynamic import must
  be declared in the manifest.
- **Authoritative source:** `Makefile` `arch-check-dynamic`;
  `scripts/check_dynamic_imports.py`; `quality/architecture.toml`;
  `.dynamic-imports-baseline.json`.
- **Canonical invocation:** `uv run python scripts/check_dynamic_imports.py`.
- **Trigger and scope:** `make check` (`CHECK_DYNAMIC_IMPORTS`); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on undeclared dynamic imports.
- **Skip semantics:** none.
- **Inputs and configuration:** direction policy in `quality/architecture.toml`;
  baseline applied by default.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** declared dynamic import passes; undeclared fails.

#### `make.arch-explain`: Architecture layer model explainer

- **Purpose:** print the layer model for humans.
- **Authoritative source:** `Makefile` `arch-explain`.
- **Canonical invocation:** `uv run python scripts/check_architecture.py --explain`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** informational.
- **Skip semantics:** none.
- **Inputs and configuration:** `quality/architecture.toml`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal model description.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exits 0 with model text.

#### `make.coupling-check`: Coupling gate (blocking)

- **Purpose:** compute Robert C. Martin package metrics and block when the
  flagged-module budget is exceeded.
- **Authoritative source:** `Makefile` `coupling-check`;
  `scripts/check_coupling.py`.
- **Canonical invocation:** `uv run python scripts/check_coupling.py --max-flagged $(MAX_FLAGGED) --blocking`.
- **Trigger and scope:** pre-push `static-checks`; `make check`
  (`CHECK_COUPLING`); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 when `--blocking` is set and flagged count
  exceeds `MAX_FLAGGED`; graph/syntax/read/config errors exit 1/2/3/4
  respectively.
- **Skip semantics:** without `--blocking` the budget breach is advisory only.
- **Inputs and configuration:** `MAX_FLAGGED=30`, `DISTANCE_THRESHOLD=0.3`.
  Current implementation includes module-level, relative, **and** function-local
  imports as coupling edges; there are **no** leaf/sibling/TYPE_CHECKING
  filters. A module is flagged when `distance >= DISTANCE_THRESHOLD` and
  `Ce > 0`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report; `--json` mode available.
- **Requirements:** uv environment.
- **Side effects:** none (read-only).
- **Replication checks:** flagged > budget + blocking => 1; advisory without
  blocking => 0; error classes.

#### `make.coupling-report`: Advisory coupling report with trend

- **Purpose:** produce an advisory coupling report compared against a stored
  trend baseline.
- **Authoritative source:** `Makefile` `coupling-report`.
- **Canonical invocation:** `uv run python scripts/check_coupling.py --trend-compare quality/baselines/coupling-report.json`.
- **Trigger and scope:** member of `make quality-architecture`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** advisory; does not block on budget.
- **Skip semantics:** trend file missing/invalid => error exit.
- **Inputs and configuration:** `quality/baselines/coupling-report.json`
  (advisory trend baseline, not a ratchet).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report with trend delta.
- **Requirements:** uv environment.
- **Side effects:** none (read-only).
- **Replication checks:** clean/advisory exit 0; malformed trend file fails.

#### `make.metrics-track`: CC/MI trend tracking

- **Purpose:** diff radon CC and MI across recent git revisions to surface
  gradual erosion.
- **Authoritative source:** `Makefile` `metrics-track`;
  `scripts/track_metrics.py`.
- **Canonical invocation:** `uv run python scripts/track_metrics.py`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** informational (not blocking).
- **Skip semantics:** none.
- **Inputs and configuration:** `--revisions`/`--since`/`--json` options.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal trend table.
- **Requirements:** uv environment; git.
- **Side effects:** reads git history (read-only).
- **Replication checks:** exits 0 on valid history.

#### `make.deptry`: Dependency hygiene

- **Purpose:** detect missing, unused, and misplaced dependencies.
- **Authoritative source:** `Makefile` `deptry`; `[tool.deptry]`.
- **Canonical invocation:** `uv run deptry src tests scripts`.
- **Trigger and scope:** `make check` (`CHECK_DEPTRY`); `make dependency-hygiene`;
  on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on dependency findings.
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.deptry]` and `per_rule_ignores`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; findings => 1.

#### `make.pip-audit`: Credential-free dependency vulnerability audit

- **Purpose:** scan dependencies for known vulnerabilities without credentials,
  in every PR/CI context including forks.
- **Authoritative source:** `Makefile` `pip-audit`.
- **Canonical invocation:** `uv run pip-audit .`.
- **Trigger and scope:** `make ci`; CI `pip-audit` job; on-demand.
- **Execution context:** Local developer workstation; repository checkout; also runs in CI
  (`ci.ci.pip-audit`, credential-free on all events); untrusted-local (developer) trust
  boundary.
- **Contextual enforcement:** fails the caller on known vulnerabilities or audit
  errors.
- **Skip semantics:** none (credential-free everywhere).
- **Inputs and configuration:** project dependencies/lockfile.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment; network.
- **Side effects:** network read (advisory DB).
- **Replication checks:** clean => 0; vulnerabilities => 1.

#### `make.dependency-hygiene`: Deptry alias

- **Purpose:** alias for `make deptry`.
- **Authoritative source:** `Makefile` `dependency-hygiene`.
- **Canonical invocation:** `make dependency-hygiene`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** as `make deptry`.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make deptry`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** as `make deptry`.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** as `make deptry`.

#### `make.import-linter`: Import contract enforcement

- **Purpose:** enforce architecture import contracts.
- **Authoritative source:** `Makefile` `import-linter`; import-linter contract
  config (`.importlinter` / declared contracts).
- **Canonical invocation:** `uv run lint-imports`.
- **Trigger and scope:** `make check` (`CHECK_IMPORT_LINTER`); `make
  quality-architecture`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the caller on contract violations.
- **Skip semantics:** none.
- **Inputs and configuration:** import-linter config.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; violation => 1.

#### `make.refurb`: Refurb readability advisory

- **Purpose:** run advisory Refurb readability checks over `src/`.
- **Authoritative source:** `Makefile` `refurb`.
- **Canonical invocation:** `uv run refurb src/`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** advisory.
- **Skip semantics:** none.
- **Inputs and configuration:** none beyond Refurb defaults.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal findings.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exits 0; findings reported.
#### `make.mutate`: Full-tree mutation run

- **Purpose:** run mutmut over the full `src/perplexity_cli/` tree (hours-long).
- **Authoritative source:** `Makefile` `mutate`; `[tool.mutmut]`.
- **Canonical invocation:** `uv run mutmut run`.
- **Trigger and scope:** on-demand/CI overnight.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** non-zero on surviving mutants (raw mutmut exit).
- **Skip semantics:** none.
- **Inputs and configuration:** `[tool.mutmut]` (`paths_to_mutate`,
  `pytest_add_cli_args` with `--ignore` infrastructure exclusions,
  `do_not_mutate`).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `.mutmut-cache`, `mutants/` metadata.
- **Requirements:** uv environment; mutmut.
- **Side effects:** writes `.mutmut-cache`, `mutants/`.
- **Replication checks:** clean run => 0; surviving mutants => 1.

#### `make.mutate-full-policy`: Full mutation then canonical policy

- **Purpose:** run full mutation, classify via `scripts/mutation_policy.py`, and
  write the canonical report.
- **Authoritative source:** `Makefile` `mutate-full-policy`;
  `scripts/mutation_policy.py`; `quality/schemas/mutation-report.json`.
- **Canonical invocation:** `uv run mutmut run` then `uv run python
  scripts/mutation_policy.py --report-path build/reports/mutation-report.json`.
- **Trigger and scope:** scheduled `automation.mutation-scheduled.mutation`;
  on-demand.
- **Execution context:** Local developer workstation; repository checkout; also runs in the
  scheduled workflow (`automation.mutation-scheduled.mutation`); untrusted-local (developer)
  trust boundary.
- **Contextual enforcement:** exits 0 clean, 1 findings (any survived/timeout/
  suspicious mutant), 2 tool-error (mutmut unavailable or output unparseable).
  The scheduled job FAILS on 1/2 while the summary/upload steps still run
  (`if: always()`).
- **Skip semantics:** none. Waivers are NOT supported.
- **Inputs and configuration:** policy constants `ACTIONABLE_CATEGORIES =
  {survived, timeout, suspicious}`; six report categories (killed, survived,
  timeout, suspicious, skipped, not_checked).
- **Ordering and concurrency:** mutmut run then policy classification.
- **Outputs and evidence:** `build/reports/mutation-report.json` conforming to
  `quality/schemas/mutation-report.json`; uploaded as a 30-day workflow
  artefact; `mutants/` metadata uploaded separately.
- **Requirements:** uv environment; mutmut.
- **Side effects:** writes `.mutmut-cache`, `mutants/`, `build/reports/`.
- **Replication checks:** all-killed => 0; survivor => 1; unparseable => 2 +
  tool-error report.

#### `make.mutate-estimate`: Full-run time estimate

- **Purpose:** print how long a full mutation run would take.
- **Authoritative source:** `Makefile` `mutate-estimate`.
- **Canonical invocation:** `uv run mutmut print-time-estimates`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** informational.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal estimate.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exits 0.

#### `make.mutate-module`: Single-module mutation

- **Purpose:** mutate one module, e.g. `make mutate-module MODULE=api`.
- **Authoritative source:** `Makefile` `mutate-module`.
- **Canonical invocation:** `uv run mutmut run src/perplexity_cli/$(MODULE)/`;
  requires `MODULE`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** non-zero on survivors.
- **Skip semantics:** errors when `MODULE` unset.
- **Inputs and configuration:** `MODULE`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `.mutmut-cache`.
- **Requirements:** uv environment.
- **Side effects:** writes `.mutmut-cache`.
- **Replication checks:** survivor => 1; missing `MODULE` => error.

#### `make.mutate-diff`: Diff-scoped mutation (pre-push/PR)

- **Purpose:** mutate only production source files changed vs a base.
- **Authoritative source:** `Makefile` `mutate-diff`;
  `scripts/discover_mutate_diff_files.py`; `[tool.mutmut]`.
- **Canonical invocation:** `make mutate-diff` (defaults `BASE_SHA ?= origin/main`,
  `TESTED_SHA ?= HEAD`; CI passes base/head SHAs).
- **Trigger and scope:** pre-push stage 5; CI `mutation-diff` (PR only);
  on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** blocks the caller on surviving diff mutants.
- **Skip semantics:** no changed production source files => "skipping mutation
  tests" and exit 0 (not-applicable, not a pass on evidence).
- **Inputs and configuration:** `BASE_SHA`, `TESTED_SHA`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `.mutmut-cache`.
- **Requirements:** uv environment; git.
- **Side effects:** writes `.mutmut-cache`.
- **Replication checks:** no diff => 0 skip; survivors => 1; clean => 0.

#### `make.mutate-results`: Show last mutation results

- **Purpose:** print results from the last mutmut run.
- **Authoritative source:** `Makefile` `mutate-results`.
- **Canonical invocation:** `uv run mutmut results`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** informational.
- **Skip semantics:** none.
- **Inputs and configuration:** `.mutmut-cache`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal table.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exits 0.

#### `make.mutate-browse`: Interactive mutation TUI

- **Purpose:** browse mutation results interactively.
- **Authoritative source:** `Makefile` `mutate-browse`.
- **Canonical invocation:** `uv run mutmut browse`.
- **Trigger and scope:** on-demand interactive.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** informational.
- **Skip semantics:** none.
- **Inputs and configuration:** `.mutmut-cache`.
- **Ordering and concurrency:** interactive.
- **Outputs and evidence:** terminal TUI.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** launches when results exist.

#### `make.test`: Safe ordinary test suite

- **Purpose:** the documented safe default test command.
- **Authoritative source:** `Makefile` `test`.
- **Canonical invocation:** `uv run pytest tests/ -q --tb=line -x -n auto -m
  "not property and not hermetic_integration and not integration and not real_api
  and not manual and not real_user_config and not fuzz"` plus
  `$(addprefix --ignore=,$(MUTATION_PROPERTY_FILES))`, where
  `MUTATION_PROPERTY_FILES` is the literal core-exclusion manifest (the
  property/mutation families listed by explicit path, never by glob).
- **Trigger and scope:** pre-commit stage 5; `make ci-test-compat`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on any failing test (`-x` fail-fast,
  `-n auto` parallel).
- **Skip semantics:** marker exclusions above plus the explicit `--ignore`
  manifest. The exclusions live in the Make recipe, NOT in `pyproject.toml`
  `addopts`. `security`/`slow` markers are NOT excluded. The `integration`
  marker is excluded even though no ordinary-lane test currently uses it.
- **Inputs and configuration:** marker set from `pyproject.toml`
  (`--strict-markers -v`); `MUTATION_PROPERTY_FILES`.
- **Ordering and concurrency:** pytest-xdist `-n auto`.
- **Outputs and evidence:** terminal output; `.pytest_cache`.
- **Requirements:** uv environment with dev deps.
- **Side effects:** `.pytest_cache`, `__pycache__`.
- **Replication checks:** clean tree passes; failing test fails; live-marked
  tests are excluded; every manifest path is `--ignore`d by exact path.

#### `make.test-coverage-report`: Tests with coverage reports

- **Purpose:** run the ordinary suite with coverage, producing JSON/XML
  reports.
- **Authoritative source:** `Makefile` `test-coverage-report`.
- **Canonical invocation:** `uv run pytest tests/ -q --tb=line -x -n auto
  --dist loadfile -m "not property and not hermetic_integration and not
  integration and not real_api and not manual and not real_user_config and not
  fuzz"` plus `$(addprefix --ignore=,$(MUTATION_PROPERTY_FILES))`,
  `--cov=perplexity_cli --cov-report=term-missing --cov-report=json
  --cov-report=xml:coverage.xml`.
- **Trigger and scope:** producer for `module-coverage` and `diff-coverage`;
  CI `diff-coverage` job.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on failing tests or coverage errors.
- **Skip semantics:** same marker and manifest exclusions as `make test`.
- **Inputs and configuration:** `[tool.coverage.run]` (`branch = true`),
  `[tool.coverage.report]` (`fail_under = 85`).
- **Ordering and concurrency:** pytest-xdist with `--dist loadfile`.
- **Outputs and evidence:** `coverage.json`, `coverage.xml`, `.coverage`.
- **Requirements:** uv environment.
- **Side effects:** writes coverage artefacts (ignored).
- **Replication checks:** reports produced; overall floor enforced by pytest-cov.

#### `make.module-coverage`: Per-module coverage gate

- **Purpose:** fail when any measured module falls below `MIN_COVERAGE`.
- **Authoritative source:** `Makefile` `module-coverage`;
  `scripts/check_module_coverage.py`.
- **Canonical invocation:** `uv run python scripts/check_module_coverage.py
  --min-coverage $(MIN_COVERAGE)`.
- **Trigger and scope:** member of `make test-coverage`; CI `test-coverage` job
  via `make ci-test-coverage`; on-demand. **Not** a member of `make check`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails when any executable module is below 85%,
  missing from the report, non-numeric/NaN/Inf, missing branch data, or outside
  the source root.
- **Skip semantics:** statement-free modules (docstring/import/constant-only,
  re-export `__init__`) may be absent. Missing `coverage.json` => exit 2
  (state dependency).
- **Inputs and configuration:** `MIN_COVERAGE=85`; `coverage.json`.
- **Ordering and concurrency:** consumes `coverage.json` produced by
  `make test-coverage-report`.
- **Outputs and evidence:** terminal summary.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** full-coverage pass; low module fails; missing report
  exits 2; branch data required.

#### `make.test-coverage`: Tests with coverage enforcement

- **Purpose:** `test-coverage-report` + `module-coverage`.
- **Authoritative source:** `Makefile` `test-coverage`.
- **Canonical invocation:** `make test-coverage`.
- **Trigger and scope:** pre-push stage 3; CI `test-coverage` job;
  `make ci-test-coverage`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on tests, global floor, or per-module floor.
- **Skip semantics:** as members.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential prerequisites.
- **Outputs and evidence:** coverage artefacts.
- **Requirements:** uv environment.
- **Side effects:** coverage artefacts.
- **Replication checks:** members behave as documented.

#### `make.test-fuzz`: Fuzz lane

- **Purpose:** run the atheris fuzz harnesses.
- **Authoritative source:** `Makefile` `test-fuzz`; `tests/test_fuzz.py`;
  `tests/_fuzz_harnesses.py`; atheris marker in `pyproject.toml`.
- **Canonical invocation:** `uv run pytest tests/test_fuzz.py -q --tb=line -x
  -m fuzz`.
- **Trigger and scope:** pre-push stage 6; CI `fuzz-status` (blocking);
  on-demand.
- **Execution context:** Local developer workstation; repository checkout; atheris on linux
  x86_64 only; untrusted-local (developer) trust boundary.
- **Contextual enforcement:** fails loudly when atheris is unavailable — the
  fuzz lane is authoritative and MUST NOT silently skip. CI has no
  `continue-on-error`.
- **Skip semantics:** none. atheris only installs on linux x86_64 (dependency
  marker `sys_platform == 'linux' and platform_machine == 'x86_64'`), so the
  fuzz lane is only runnable there.
- **Inputs and configuration:** `[tool.pytest]` marker `fuzz`.
- **Ordering and concurrency:** `-x`; each harness runs in a separate
  subprocess.
- **Outputs and evidence:** terminal output.
- **Requirements:** atheris on linux x86_64.
- **Side effects:** harness temp state.
- **Replication checks:** harness crash fails; clean passes; missing atheris
  fails.

#### `make.test-integration`: Hermetic integration tests

- **Purpose:** run loopback-only hermetic integration tests.
- **Authoritative source:** `Makefile` `test-integration`; marker
  `hermetic_integration` in `pyproject.toml`.
- **Canonical invocation:** `uv run pytest tests/ -q --tb=short -m
  hermetic_integration` plus `$(addprefix --ignore=,$(MUTATION_PROPERTY_FILES))`
  (the manifest files are excluded from collection so broken dormant families
  cannot interrupt the lane).
- **Trigger and scope:** CI `hermetic-integration` job; on-demand.
- **Execution context:** Local developer workstation; repository checkout; loopback-only (no
  real network); untrusted-local (developer) trust boundary. The fail-closed
  network guard is default-on (installed in `pytest_configure`), so the lane
  runs under loopback-only semantics with no bypass in CI.
- **Contextual enforcement:** fails on failing hermetic tests.
- **Skip semantics:** none. The `hermetic_integration` marker selects loopback
  tests; the registered `integration` marker covers protocol/auth or real-service
  integration paths (may use network) and is excluded by both the ordinary and
  coverage selectors and never selected here.
- **Inputs and configuration:** `tests/support/protocol_server.py` harness.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (loopback only).
- **Replication checks:** hermetic tests pass without network.

#### `make.test-property-policy`: Property manifest parity

- **Purpose:** enforce exact bidirectional parity between the property inventory
  and the Make-declared property source files.
- **Authoritative source:** `Makefile` `test-property-policy`;
  `tests/test_property_policy.py`; `quality/property-inventory.toml`.
- **Canonical invocation:** `uv run pytest tests/test_property_policy.py -q`.
- **Trigger and scope:** prerequisite of every property target (`test-property`,
  `test-property-push`, `test-property-ci`, `ci-property`).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** blocks the caller on any stale/missing/duplicate
  property ID in the manifest. Source scope is owned by Make
  (`override PROPERTY_TEST_FILES := tests/test_property.py`), so the manifest
  cannot shrink its own discovery universe.
- **Skip semantics:** none.
- **Inputs and configuration:** `quality/property-inventory.toml`
  (`schema_version=1`, `node_id` + `oracle_type` + `rationale`); `PROPERTY_TEST_FILES`.
- **Ordering and concurrency:** prerequisite of property lanes.
- **Outputs and evidence:** terminal parity report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exact parity passes; manifest-only or source-only IDs
  fail.

#### `make.test-property`: Property tests (dev profile)

- **Purpose:** run property tests with the Hypothesis `dev` profile.
- **Authoritative source:** `Makefile` `test-property`.
- **Canonical invocation:** `make test-property`
  (`uv run pytest $(PROPERTY_TEST_FILES) -v --tb=short -m property
  --hypothesis-profile=dev`); prerequisite `test-property-policy`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on property failure or manifest mismatch.
- **Skip semantics:** none.
- **Inputs and configuration:** dev profile: 10 examples, 500 ms deadline.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output; `.hypothesis/`.
- **Requirements:** uv environment; hypothesis.
- **Side effects:** `.hypothesis/` database.
- **Replication checks:** clean => 0; counterexample => 1.

#### `make.test-property-push`: Property tests (push profile)

- **Purpose:** pre-push property lane with 50 examples.
- **Authoritative source:** `Makefile` `test-property-push`.
- **Canonical invocation:** `make test-property-push` (`--hypothesis-profile=push`).
- **Trigger and scope:** pre-push stage 4; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on property failure or manifest mismatch.
- **Skip semantics:** none.
- **Inputs and configuration:** push profile: 50 examples, 500 ms deadline.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** `.hypothesis/`.
- **Replication checks:** clean => 0; counterexample => 1.

#### `make.test-property-ci`: Property tests (CI profile)

- **Purpose:** thorough property lane with 1000 examples.
- **Authoritative source:** `Makefile` `test-property-ci`.
- **Canonical invocation:** `make test-property-ci` (`--hypothesis-profile=ci`).
- **Trigger and scope:** CI property job (`PROPERTY_PROFILE=ci`); release lane.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on property failure or manifest mismatch.
- **Skip semantics:** none.
- **Inputs and configuration:** ci profile: 1000 examples, 500 ms deadline.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** `.hypothesis/`.
- **Replication checks:** clean => 0; counterexample => 1.

#### `make.diff-coverage`: Changed-line coverage

- **Purpose:** require `DIFF_COVERAGE_THRESHOLD` coverage on changed lines.
- **Authoritative source:** `Makefile` `diff-coverage`; `DIFF_COVERAGE_THRESHOLD`.
- **Canonical invocation:** `make diff-coverage` (defaults `BASE_SHA ?= origin/main`,
  `TESTED_SHA ?= HEAD`; CI passes PR base/head SHAs).
- **Trigger and scope:** CI `diff-coverage` (PR only); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails (diff-cover exit) below 90% on changed
  lines; exit 2 when `coverage.xml` is missing.
- **Skip semantics:** none.
- **Inputs and configuration:** `coverage.xml` (produced by
  `make test-coverage-report`); `DIFF_COVERAGE_THRESHOLD=90`.
- **Ordering and concurrency:** consumes `coverage.xml`.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment; diff-cover.
- **Side effects:** none.
- **Replication checks:** >= 90% passes; below fails; missing XML exits 2.

#### `make.safety`: Authenticated Safety scan (local, skip when credentials unavailable)

- **Purpose:** run the pinned Safety 3.8.1 scan when credentials are available.
- **Authoritative source:** `Makefile` `safety`; `scripts/agent_check.py safety`.
- **Canonical invocation:** `make safety` — resolves credentials from
  `SAFETY_API_KEY` or `infisical run --env dev`; runs `uv run python
  scripts/agent_check.py safety`.
- **Trigger and scope:** pre-push stage 6; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** once authenticated scanning starts, any Safety or
  Infisical child failure propagates and blocks. Missing credentials produce an
  informational skip (NOT a pass, NOT a block).
- **Skip semantics:** the ONE legal local skip: credentials unavailable.
- **Inputs and configuration:** `SAFETY_API_KEY` or Infisical; Safety pinned
  3.8.1; staging copy of `pyproject.toml`, `uv.lock`, `src`, `tests`, `scripts`,
  `vulture_whitelist.py`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** credentials for a real scan; network.
- **Side effects:** temporary staging directory (cleaned up).
- **Replication checks:** credentialed findings block; credentialed clean passes;
  missing credentials skip informationally.

#### `make.safety-gate`: Fail-closed authenticated Safety

- **Purpose:** authenticated Safety that FAILS when credentials are unavailable.
- **Authoritative source:** `Makefile` `safety-gate`; `ci.yml` safety job;
  `publish-to-pypi.yml`.
- **Canonical invocation:** `make safety-gate`.
- **Trigger and scope:** CI `safety` job — **push events only**
  (`if: github.event_name == 'push'`); tag release via `make ci-trusted`;
  never on PRs.
- **Execution context:** Local developer workstation or trusted CI (push event / tag release
  workflow) with `SAFETY_API_KEY`; repository checkout; trusted (credentialed) boundary.
- **Contextual enforcement:** fails when credentials are missing (exit 2) or the
  authenticated scan fails.
- **Skip semantics:** none.
- **Inputs and configuration:** `SAFETY_API_KEY` secret; Safety pinned 3.8.1.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** `SAFETY_API_KEY` in the trusted push/release context.
- **Side effects:** temporary staging directory; network read of Safety API.
- **Replication checks:** missing key => exit 2; scan findings => block.

#### `make.infisical-scan`: Uncommitted-change secret scan

- **Purpose:** scan uncommitted git changes for secrets.
- **Authoritative source:** `Makefile` `infisical-scan`.
- **Canonical invocation:** `infisical scan git-changes --verbose --exit-code 1`.
- **Trigger and scope:** pre-commit stage 2 `infisical-scan`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the commit when the scan finds secrets
  (exit 1).
- **Skip semantics:** skips gracefully when the infisical CLI is missing — the
  ONE legal local skip in pre-commit. Setup (`make setup`) still requires the
  CLI.
- **Inputs and configuration:** infisical workspace for git-changes scan.
- **Ordering and concurrency:** stage 2 parallel; no stdin.
- **Outputs and evidence:** terminal output.
- **Requirements:** infisical CLI.
- **Side effects:** none.
- **Replication checks:** clean => 0; secrets found => 1; CLI missing => skip
  notice.

#### `make.gitleaks`: Standalone gitleaks scan

- **Purpose:** on-demand gitleaks scan (stdin or local range depending on
  invocation context).
- **Authoritative source:** `Makefile` `gitleaks`; `scripts/gitleaks_check.sh`.
- **Canonical invocation:** `make gitleaks`
  (`scripts/gitleaks_check.sh`, no args: stdin mode when piped, local range
  otherwise).
- **Trigger and scope:** on-demand. Pre-push uses the DIRECT script invocation,
  NOT this target (see `hook.pre-push.gitleaks-detect`).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 10 on secrets, 3 on missing/wrong-version/
  input/git/config/scanner errors. Fails closed on missing gitleaks.
- **Skip semantics:** deleted refs skipped; no refs/commits => exit 0.
- **Inputs and configuration:** `REQUIRED_GITLEAKS_VERSION=8.30.1`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal scan summary.
- **Requirements:** gitleaks 8.30.1.
- **Side effects:** network read only when querying remotes in stdin mode.
- **Replication checks:** clean => 0; secrets => 10; wrong version => 3.

#### `make.gitleaks-ci`: CI full-history gitleaks

- **Purpose:** full-history secret scan for CI, failing when gitleaks is
  missing/wrong-version.
- **Authoritative source:** `Makefile` `gitleaks-ci`;
  `scripts/gitleaks_check.sh ci-full`.
- **Canonical invocation:** `make gitleaks-ci`
  (`CI_NO_SKIP=1 scripts/gitleaks_check.sh ci-full`).
- **Trigger and scope:** CI `secret-scan` job (gitleaks 8.30.1 installed by the
  workflow first); on-demand.
- **Execution context:** GitHub Actions `ubuntu-latest` (CI `secret-scan` job, permissions
  `contents: read`); also runnable on a local workstation on-demand.
- **Contextual enforcement:** fails the job on secrets (exit 10) or when
  gitleaks is missing/not 8.30.1 (exit 3).
- **Skip semantics:** none (`CI_NO_SKIP=1`).
- **Inputs and configuration:** full repo history (`gitleaks detect --source .
  --verbose --redact --exit-code 10`).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal scan summary.
- **Requirements:** gitleaks 8.30.1.
- **Side effects:** none.
- **Replication checks:** clean => 0; secrets => 10; missing tool => 3.

#### `make.build`: Build sdist and wheel

- **Purpose:** build distributions.
- **Authoritative source:** `Makefile` `build`.
- **Canonical invocation:** `make build` (`rm -rf dist; uv build`).
- **Trigger and scope:** `make ci-package`, `make ci`, release lane; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on build error.
- **Skip semantics:** none.
- **Inputs and configuration:** `pyproject.toml` build-system (setuptools).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `dist/*.whl`, `dist/*.tar.gz`.
- **Requirements:** uv environment.
- **Side effects:** deletes and rewrites `dist/`.
- **Replication checks:** distributions produced.

#### `make.verify`: Verify built distributions

- **Purpose:** `twine check` + wheel verification.
- **Authoritative source:** `Makefile` `verify`; `scripts/verify_wheel.py`.
- **Canonical invocation:** `make verify`
  (`uvx twine check dist/*`, `uv run python scripts/verify_wheel.py`).
- **Trigger and scope:** `make ci-package`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on malformed distributions.
- **Skip semantics:** none.
- **Inputs and configuration:** `dist/`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal verification.
- **Requirements:** uv environment; twine via uvx.
- **Side effects:** none.
- **Replication checks:** valid dist passes; malformed fails.

#### `make.smoke-test`: Installed-wheel smoke test

- **Purpose:** install the newest wheel in an isolated venv and exercise the CLI
  entry point, config subsystem, and packaged resources.
- **Authoritative source:** `Makefile` `smoke-test`; `scripts/smoke_test.sh`.
- **Canonical invocation:** `make smoke-test`.
- **Trigger and scope:** `make ci`; CI `wheel-smoke-linux` and
  `wheel-smoke-macos` (download the package wheel first); on-demand.
- **Execution context:** Local developer workstation; repository checkout; isolated temp
  venv; untrusted-local (developer) trust boundary.
- **Contextual enforcement:** fails when the wheel is missing or the smoke
  checks fail.
- **Skip semantics:** none.
- **Inputs and configuration:** newest `dist/pxcli-*.whl`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output; isolated temp venv/config.
- **Requirements:** uv; a built wheel in `dist/`.
- **Side effects:** creates a temp venv/config dir (cleaned up).
- **Replication checks:** `--version`, `config show`, query-endpoint resolution,
  `urls.json` creation.

#### `make.package-contract`: Build and verify the distribution contract

- **Purpose:** build, verify, test and smoke the distribution contract
  end-to-end against the current source.
- **Authoritative source:** `Makefile` `package-contract`;
  `scripts/verify_wheel.py`; `scripts/smoke_test.py`;
  `tests/test_distribution_contract.py`.
- **Canonical invocation:** `make package-contract` (`uv build`, then
  `scripts/verify_wheel.py`, then `uv run pytest
  tests/test_packaging.py tests/test_distribution_contract.py -q`, then
  `scripts/smoke_test.py`).
- **Trigger and scope:** member of `make ci-conventional`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; offline-capable
  build; untrusted-local (developer) trust boundary.
- **Contextual enforcement:** fails on build, verification, packaging-test, or
  smoke-test failure.
- **Skip semantics:** none.
- **Inputs and configuration:** `pyproject.toml`; `dist/` rebuilt by `uv build`.
- **Ordering and concurrency:** strict order: build → verify → packaging tests
  → installed-wheel smoke.
- **Outputs and evidence:** `dist/*.whl`, `dist/*.tar.gz`; terminal verification.
- **Requirements:** uv environment; network on first build-backend fetch.
- **Side effects:** rewrites `dist/`; creates a temp venv/config (cleaned up).
- **Replication checks:** artefacts build, verify, test and smoke cleanly.

#### `make.release`: Local release (bump, lock, CI, commit, tag, push)

- **Purpose:** perform a versioned release.
- **Authoritative source:** `Makefile` `release`.
- **Canonical invocation:** `make release V=x.y.z` (requires `V`).
- **Trigger and scope:** on-demand, human-invoked.
- **Execution context:** Local developer workstation; repository checkout; developer trust
  boundary; mutates git and pushes (network-write).
- **Contextual enforcement:** aborts if `V` unset or any step fails.
- **Skip semantics:** none.
- **Inputs and configuration:** `V`; version line in `pyproject.toml`.
- **Ordering and concurrency:** `sed` version bump, `uv lock`, `make ci-trusted`,
  `git add`, `git commit`, `git tag -a vX.Y.Z`, `git push origin master`, `git
  push origin vX.Y.Z`.
- **Outputs and evidence:** release commit, tag, remote pushes; the tag drives
  the remote publish workflow.
- **Requirements:** full local toolchain; credentials for push.
- **Side effects:** **mutates-git** and **network-write** (commit, tag, push).
- **Replication checks:** version bump, lock update, CI pass, commit/tag/push.

#### `make.clean`: Remove build artefacts

- **Purpose:** delete generated artefacts.
- **Authoritative source:** `Makefile` `clean`.
- **Canonical invocation:** `make clean`
  (`rm -rf dist build .coverage coverage.json coverage.xml .pytest_cache
  .mypy_cache .ruff_cache`).
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** none.
- **Skip semantics:** none.
- **Inputs and configuration:** none.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** removed directories.
- **Requirements:** none.
- **Side effects:** deletes ignored build/cache artefacts.
- **Replication checks:** artefacts removed.

#### `make.check`: Configured static checks

- **Purpose:** run every analyser whose `CHECK_*` toggle is `true`.
- **Authoritative source:** `Makefile` `check`; `quality/gates.conf`.
- **Canonical invocation:** `make check`.
- **Trigger and scope:** on-demand; documented as the local static gate.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on the first failing prerequisite (Make
  prerequisite chain).
- **Skip semantics:** toggles off would drop members; currently ALL toggles are
  `true`. `module-coverage` is NOT a member — per-module coverage lives in
  `make test-coverage`.
- **Inputs and configuration:** every `CHECK_*` from `quality/gates.conf`.
- **Ordering and concurrency:** Make prerequisite order (see
  [Composite And Topology Reference](#9-composite-and-topology-reference)).
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (read-only analysers).
- **Replication checks:** with current toggles, prerequisite set equals
  format-check lint typecheck-all security complexity semgrep arch-check
  coupling-check ratchets import-linter arch-check-dynamic suppression-reasons
  deptry.

#### `make.ci-static`: CI static lane

- **Purpose:** static analysis aggregate for the CI `static` job.
- **Authoritative source:** `Makefile` `ci-static`.
- **Canonical invocation:** `make ci-static`
  (`format-check lint typecheck-all bandit vulture complexity actionlint`).
- **Trigger and scope:** CI `static` job; `make ci`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on any member.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential prerequisites.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment; actionlint resolvable via uvx.
- **Side effects:** none.
- **Replication checks:** members behave as documented.

#### `make.ci-test-coverage`: CI coverage lane

- **Purpose:** coverage lane for CI `test-coverage` job.
- **Authoritative source:** `Makefile` `ci-test-coverage`.
- **Canonical invocation:** `make ci-test-coverage` (`test-coverage`).
- **Trigger and scope:** CI `test-coverage`; `make ci`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** as `make.test-coverage`.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** as `make.test-coverage`.
- **Requirements:** uv environment.
- **Side effects:** coverage artefacts.
- **Replication checks:** as `make.test-coverage`.

#### `make.ci-test-compat`: CI compatibility lane

- **Purpose:** compatibility tests without coverage.
- **Authoritative source:** `Makefile` `ci-test-compat`.
- **Canonical invocation:** `make ci-test-compat` (`test`).
- **Trigger and scope:** CI `test-compat` matrix (3.13/3.14) and `test-macos`
  (3.12); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** as `make.test`.
- **Skip semantics:** as `make.test`.
- **Inputs and configuration:** as `make.test`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment for the target Python.
- **Side effects:** as `make.test`.
- **Replication checks:** as `make.test`.

#### `make.ci-fuzz-status`: CI fuzz lane (authoritative)

- **Purpose:** authoritative fuzz status for CI.
- **Authoritative source:** `Makefile` `ci-fuzz-status`.
- **Canonical invocation:** `make ci-fuzz-status` (`test-fuzz`).
- **Trigger and scope:** CI `fuzz-status` job — BLOCKING (no
  `continue-on-error`); `make ci`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails the job on fuzz failure; atheris required
  (no skip).
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.test-fuzz`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** atheris on linux x86_64.
- **Side effects:** as `make.test-fuzz`.
- **Replication checks:** as `make.test-fuzz`.

#### `make.ci-property`: CI property lane

- **Purpose:** property lane driven by `PROPERTY_PROFILE`.
- **Authoritative source:** `Makefile` `ci-property`.
- **Canonical invocation:** `make ci-property` (`test-property-$(PROPERTY_PROFILE)`).
- **Trigger and scope:** CI `property` job (Python 3.13, `PROPERTY_PROFILE=ci`);
  `make ci` (default `ci` profile).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on property failure or manifest mismatch.
- **Skip semantics:** none.
- **Inputs and configuration:** `PROPERTY_PROFILE ?= ci`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** `.hypothesis/`.
- **Replication checks:** as the selected property lane.

#### `make.ci-package`: CI package lane

- **Purpose:** build and verify distributions for CI.
- **Authoritative source:** `Makefile` `ci-package`.
- **Canonical invocation:** `make ci-package` (`build verify`).
- **Trigger and scope:** CI `package` job (uploaded as
  `wheel-dist-<run_id>-<run_attempt>`, 7-day retention); `make ci`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on build or verification error.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** `dist/`; workflow artefact for smoke jobs.
- **Requirements:** uv environment.
- **Side effects:** writes `dist/`.
- **Replication checks:** distributions built and verified.

#### `make.ci`: Local credential-free CI aggregate

- **Purpose:** the credential-free local CI pipeline.
- **Authoritative source:** `Makefile` `ci`.
- **Canonical invocation:** `make ci`
  (`ci-static ci-test-coverage ci-fuzz-status pip-audit sonar-reports
  ci-property ci-package smoke-test`).
- **Trigger and scope:** on-demand; local pre-release sanity.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on any member.
- **Skip semantics:** none.
- **Inputs and configuration:** as members; `PROPERTY_PROFILE` default `ci`.
- **Ordering and concurrency:** sequential prerequisites. Runs `sonar-reports`
  and `smoke-test` DIRECTLY (workflow CI omits sonar and splits jobs).
- **Outputs and evidence:** terminal output; coverage/build/report artefacts.
- **Requirements:** uv environment; prior coverage producer handled internally.
- **Side effects:** writes coverage artefacts, `dist/`, `build/reports/`.
- **Replication checks:** members behave as documented.

#### `make.ci-trusted`: Credential-free CI plus fail-closed Safety

- **Purpose:** the trusted pipeline used on push CI and release.
- **Authoritative source:** `Makefile` `ci-trusted`.
- **Canonical invocation:** `make ci-trusted` (`ci safety-gate`).
- **Trigger and scope:** push CI `safety` job is separate; release workflow runs
  `make ci-trusted` with `SAFETY_API_KEY`.
- **Execution context:** Local developer workstation; repository checkout; also run by push
  CI and the tag release workflow with `SAFETY_API_KEY`; trusted (credentialed) boundary.
- **Contextual enforcement:** fails if `ci` fails or Safety credentials are
  unavailable / the scan fails.
- **Skip semantics:** none (fail-closed).
- **Inputs and configuration:** `SAFETY_API_KEY` where invoked.
- **Ordering and concurrency:** `ci` then `safety-gate`.
- **Outputs and evidence:** terminal output.
- **Requirements:** credentials in trusted contexts.
- **Side effects:** as `make.ci`.
- **Replication checks:** members behave as documented.

#### `make.ci-quality`: Deterministic offline quality-gate inventory

- **Purpose:** run every deterministic offline quality gate in one composite.
- **Authoritative source:** `Makefile` `ci-quality`.
- **Canonical invocation:** `make ci-quality` (`format-check lint typecheck-all
  bandit vulture complexity semgrep arch-check arch-check-dynamic
  import-linter coupling-check ratchets analyser-contract-tests deptry
  make-policy workflow-policy actionlint`).
- **Trigger and scope:** member of `make ci-conventional`; enforced by the
  `ci.ci.repository-policy` CI job; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on any member.
- **Skip semantics:** none.
- **Inputs and configuration:** as members; no tests, no build, no coverage.
- **Ordering and concurrency:** sequential prerequisites in the inventory
  order above.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment; pinned semgrep/actionlint resolvable via
  `uvx` (offline-cached after first use).
- **Side effects:** none (read-only analysers; semgrep fetches the pinned
  binary via uvx on first use).
- **Replication checks:** every member gate runs and passes; members behave as
  documented.

#### `make.ci-conventional`: Serial final gate list

- **Purpose:** the deterministic, offline, single-target final gate sequence.
- **Authoritative source:** `Makefile` `ci-conventional`.
- **Canonical invocation:** `make ci-conventional` (one serial recipe; each
  command runs in order with `UV_OFFLINE=1` and `npm_config_offline=true`).
- **Trigger and scope:** on-demand; authoritative local end-to-end signal.
- **Execution context:** Local developer workstation; repository checkout; offline (no
  network reads); untrusted-local (developer) trust boundary.
- **Contextual enforcement:** fails at the first failing command (`set -e`).
- **Skip semantics:** none.
- **Inputs and configuration:** the exact gate order: `make format-check`;
  `make lint`; `make typecheck-all`; `uv run pytest
  tests/test_network_guard.py tests/test_test_isolation.py -q`;
  `make test-coverage`; `make test-integration`; `make ci-quality`;
  `uv run pytest tests/test_mcp_server.py tests/test_mcp_protocol.py -q`;
  `make test-fuzz`; `npm --prefix .opencode run test:coverage`;
  `npm --prefix .opencode run check`; `make package-contract`;
  `make gitleaks-ci`; `uv run python scripts/architecture_model.py` and
  `uv run python scripts/check_architecture.py`.
- **Ordering and concurrency:** strictly serial.
- **Outputs and evidence:** terminal output; coverage/build artefacts.
- **Requirements:** uv environment; npm deps installed; gitleaks 8.30.1 on
  `PATH`.
- **Side effects:** writes coverage artefacts, `dist/`, `.pytest_cache`,
  `.hypothesis/`.
- **Replication checks:** each gate in the documented order; a failing gate
  aborts the chain.

#### `make.analyser-contract-validate`: Validate the production analyser contract registry

- **Purpose:** prove the production `quality/analyser-contracts.toml` is valid
  without executing any analyser.
- **Authoritative source:** `Makefile` `analyser-contract-validate`;
  `scripts/check_analyser_contracts.py --validate`.
- **Canonical invocation:** `uv run python scripts/check_analyser_contracts.py --validate`.
- **Trigger and scope:** prerequisite of `make analyser-contract-tests`; CI
  `static` job via `analyser-contract-tests`.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on invalid/missing/duplicate/unsafe
  contracts. `--validate` NEVER executes analysers; `--validate` and `--run`
  are mutually exclusive.
- **Skip semantics:** none.
- **Inputs and configuration:** `quality/analyser-contracts.toml` (schema v1).
- **Ordering and concurrency:** before contract unit tests.
- **Outputs and evidence:** terminal validation.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** valid production file passes; unknown keys/duplicate
  IDs/missing targets/escaped test refs fail.

#### `make.analyser-contract-tests`: Validate and test analyser contracts

- **Purpose:** production validation followed by the contract unit tests.
- **Authoritative source:** `Makefile` `analyser-contract-tests`;
  `tests/test_analyser_contracts.py`.
- **Canonical invocation:** `make analyser-contract-tests`
  (`analyser-contract-validate` then `uv run pytest tests/test_analyser_contracts.py -q`).
- **Trigger and scope:** CI `static` job; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on validation or test failure.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** members behave as documented.

#### `make.agent-check`: Agent unified pre-commit report

- **Purpose:** run the agent-oriented full pre-commit pipeline (fixers, linters,
  tests) as one aggregated report.
- **Authoritative source:** `Makefile` `agent-check`;
  `scripts/agent_check.py pre-commit`.
- **Canonical invocation:** `uv run python scripts/agent_check.py pre-commit`.
- **Trigger and scope:** on-demand for coding agents.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 if any analyser fails.
- **Skip semantics:** none.
- **Inputs and configuration:** `PRE_COMMIT_FIXERS`, `PRE_COMMIT_LINTERS`,
  `PRE_COMMIT_TESTS` in `scripts/agent_check.py`.
- **Ordering and concurrency:** fixers sequential, then linters parallel, then
  tests.
- **Outputs and evidence:** aggregated terminal/JSON report.
- **Requirements:** uv environment.
- **Side effects:** fixers write the working tree.
- **Replication checks:** aggregated pass/fail matches members.

#### `make.agent-check-no-tests`: Agent read-only linter subset

- **Purpose:** the read-only pre-commit linter set (no fixers, no tests).
- **Authoritative source:** `Makefile` `agent-check-no-tests`.
- **Canonical invocation:** `uv run python scripts/agent_check.py --no-tests --no-fix pre-commit`.
- **Trigger and scope:** pre-push `static-checks`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** blocks the push when any member fails.
- **Skip semantics:** none.
- **Inputs and configuration:** `PRE_COMMIT_LINTERS` (pyright, ty, bandit,
  vulture, radon-cc, radon-mi, semgrep, format-check, lint).
- **Ordering and concurrency:** parallel.
- **Outputs and evidence:** aggregated report.
- **Requirements:** uv environment.
- **Side effects:** none (read-only).
- **Replication checks:** clean passes; member failure blocks.

#### `make.agent-check-push`: Agent pre-push subset

- **Purpose:** the agent pre-push subset: coverage, safety, fuzz, architecture,
  coupling, property.
- **Authoritative source:** `Makefile` `agent-check-push`.
- **Canonical invocation:** `uv run python scripts/agent_check.py pre-push`.
- **Trigger and scope:** on-demand — **NOT wired into `lefthook.yml` or
  `make ci`** (Lefthook schedules those jobs directly).
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 if any member fails.
- **Skip semantics:** none.
- **Inputs and configuration:** `PRE_PUSH_ALL` in `scripts/agent_check.py`.
- **Ordering and concurrency:** parallel.
- **Outputs and evidence:** aggregated report.
- **Requirements:** uv environment; Safety credentials for a real scan.
- **Side effects:** coverage artefacts; safety temp staging.
- **Replication checks:** aggregated pass/fail matches members.

#### `make.ratchets`: Ratchet composite (six members)

- **Purpose:** run all six ratchet/hard-gate members.
- **Authoritative source:** `Makefile` `ratchets`.
- **Canonical invocation:** `make ratchets`
  (`file-size suppression-ratchet suppression-reasons ruff-architecture
  typecheck-strict-ratchet semgrep-architecture`).
- **Trigger and scope:** pre-push `static-checks` (`quality-ratchets`); `make
  check` (`CHECK_RATCHETS`); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on any member. Four baseline-aware ratchets
  (file-size, suppression, suppression-reasons, semgrep-architecture) and two
  whole-tree hard gates (ruff-architecture, typecheck-strict-ratchet).
- **Skip semantics:** none.
- **Inputs and configuration:** as members; `FILE_SIZE_CAP`, baselines in
  `quality/baselines/`.
- **Ordering and concurrency:** sequential prerequisites.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (read-only; semgrep-architecture fetches pinned semgrep
  via uvx on first use).
- **Replication checks:** members behave as documented.

#### `make.file-size`: File-size ratchet

- **Purpose:** block new or grown source files over `FILE_SIZE_CAP`.
- **Authoritative source:** `Makefile` `file-size`; `scripts/check_file_size.py`;
  `quality/baselines/file-size.json`.
- **Canonical invocation:** `uv run python scripts/check_file_size.py --max-lines $(FILE_SIZE_CAP)`.
- **Trigger and scope:** member of `make ratchets` / `make check`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 on new/grown oversized files; exit 2 usage.
- **Skip semantics:** baseline-accepted oversized files are not findings.
- **Inputs and configuration:** `FILE_SIZE_CAP=1000`; counts baseline
  `file-size.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** new oversized file fails; growth fails; shrink
  suggests `--update-baseline`; unchanged passes.

#### `make.suppression-ratchet`: Suppression ratchet

- **Purpose:** block new/moved/broadened inline suppressions.
- **Authoritative source:** `Makefile` `suppression-ratchet`;
  `scripts/check_suppressions.py`; `quality/baselines/suppressions.json`.
- **Canonical invocation:** `uv run python scripts/check_suppressions.py`.
- **Trigger and scope:** member of `make ratchets` / `make check`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 when any identity in the tracked set
  changes. Tracks exact `file:line:type[:detail]` identities for `# noqa`,
  `# nosec`, `# nosemgrep`, `# type: ignore`, `# pyright: ignore`, pragmas
  `no cover/branch/mutate`, coverage config (`omit`, `exclude_lines`,
  `exclude_also`, `partial_branches`), and mutmut `do_not_mutate`.
- **Skip semantics:** none.
- **Inputs and configuration:** fingerprint baseline `suppressions.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report of new/removed identities.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** adding/removing/broadening an identity fails; no
  change passes; `--update-baseline` records current set.

#### `make.suppression-reasons`: Suppression owner/reason enforcement

- **Purpose:** require `owner:` and `reason:` fields on NEW inline suppressions.
- **Authoritative source:** `Makefile` `suppression-reasons`;
  `scripts/check_suppression_reasons.py`; `quality/baselines/suppression-reasons.json`.
- **Canonical invocation:** `uv run python scripts/check_suppression_reasons.py`.
- **Trigger and scope:** member of `make ratchets` / `make check`
  (`CHECK_SUPPRESSION_REASONS`); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 when a new suppression lacks
  `owner:`/`reason:`. Existing un-annotated suppressions are grandfathered via
  the fingerprint baseline.
- **Skip semantics:** none.
- **Inputs and configuration:** format
  `# noqa: X; owner: name; reason: explanation`; baseline
  `suppression-reasons.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** formatted/new suppression passes; new unformatted
  fails; grandfathered passes.

#### `make.ruff-architecture`: Ruff architecture hard gate

- **Purpose:** whole-tree hard gate over `src/` for C901, PLR0913, PLR2004,
  ARG001, ARG002.
- **Authoritative source:** `Makefile` `ruff-architecture`.
- **Canonical invocation:** `uv run ruff check --select C901,PLR0913,PLR2004,ARG001,ARG002
  --config "lint.mccabe.max-complexity = 5" --config "lint.pylint.max-args = 4"
  --output-format concise src/`.
- **Trigger and scope:** member of `make ratchets` / `make check`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit non-zero on any finding. HARD gate — no
  baseline. (The dormant wrapper `scripts/check_ruff_architecture.py` and
  `quality/baselines/ruff-architecture.json` are test-only shadows, NOT wired
  here.)
- **Skip semantics:** none.
- **Inputs and configuration:** selectors + inline config above.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; any finding => non-zero.

#### `make.typecheck-strict-ratchet`: Pyright strict hard gate

- **Purpose:** strict Pyright over all of `src/`.
- **Authoritative source:** `Makefile` `typecheck-strict-ratchet`;
  `[tool.pyright]`.
- **Canonical invocation:** `uv run pyright src/`.
- **Trigger and scope:** member of `make ratchets` / `make check`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit non-zero on any diagnostic. HARD gate — no
  baseline. (The dormant wrapper `scripts/check_pyright_strict.py` and
  `quality/baselines/pyright-strict.json` are test-only shadows, NOT wired
  here.)
- **Skip semantics:** none.
- **Inputs and configuration:** strict mode, Python 3.12.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; diagnostics => non-zero.

#### `make.semgrep-architecture`: Semgrep architecture ratchet

- **Purpose:** block new structural findings from the architecture Semgrep
  rules.
- **Authoritative source:** `Makefile` `semgrep-architecture`;
  `scripts/check_semgrep_architecture.py`; `.semgrep.yml`;
  `quality/baselines/semgrep-architecture.json`.
- **Canonical invocation:** `uv run python scripts/check_semgrep_architecture.py`.
- **Trigger and scope:** member of `make ratchets` / `make check`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 on new fingerprints; exit 2 (fail-closed)
  on tool/config errors. Tracks `ARCH_RULE_IDS` (function-local-import,
  retry-sleep-outside-canonical, ad-hoc-http-status-classification,
  sys-exit-outside-boundary, http-client-outside-transport,
  write-then-chmod-toctou, getter-with-side-effects,
  click-echo-outside-presentation).
- **Skip semantics:** none.
- **Inputs and configuration:** pinned semgrep 1.171.0; fingerprint baseline
  `semgrep-architecture.json`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment; pinned semgrep via `uvx`.
- **Side effects:** network read for tool fetch.
- **Replication checks:** new finding fails; unchanged passes; scanner error
  fails closed (exit 2).

#### `make.sonar-reports`: Generate SonarQube reports

- **Purpose:** generate `build/reports/bandit-report.json` for SonarQube
  import.
- **Authoritative source:** `Makefile` `sonar-reports`;
  `scripts/generate_sonar_reports.py`.
- **Canonical invocation:** `uv run python scripts/generate_sonar_reports.py`.
- **Trigger and scope:** pre-push stage 4; `make ci` (direct); on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exit 1 when a report cannot be generated.
- **Skip semantics:** none.
- **Inputs and configuration:** bandit tool spec.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** `build/reports/bandit-report.json`.
- **Requirements:** uv environment; network for `uvx --from bandit`.
- **Side effects:** writes `build/reports/`.
- **Replication checks:** report produced; bandit findings do not fail (report
  existence is what matters).

#### `make.quality-architecture`: Architecture composite

- **Purpose:** run import-linter + arch-check + advisory coupling report.
- **Authoritative source:** `Makefile` `quality-architecture`.
- **Canonical invocation:** `make quality-architecture`
  (`import-linter arch-check coupling-report`).
- **Trigger and scope:** on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails if import-linter or arch-check fails;
  coupling-report is advisory.
- **Skip semantics:** none.
- **Inputs and configuration:** as members.
- **Ordering and concurrency:** sequential.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** members behave as documented.

#### `make.actionlint`: Validate GitHub Actions workflows

- **Purpose:** lint all workflow files.
- **Authoritative source:** `Makefile` `actionlint`;
  `ACTIONLINT_PY_VERSION := 1.7.12.24`.
- **Canonical invocation:** `$(ACTIONLINT)`
  (`uvx --from actionlint-py==1.7.12.24 actionlint`).
- **Trigger and scope:** member of `make ci-static`, `make ci-quality`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** fails on workflow syntax/policy errors.
- **Skip semantics:** none.
- **Inputs and configuration:** pinned actionlint-py 1.7.12.24.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal lint.
- **Requirements:** network for uvx on first use.
- **Side effects:** none.
- **Replication checks:** valid workflows pass; malformed fails.

#### `make.make-policy`: Make target ownership and dependency policy

- **Purpose:** statically validate Make target ownership and dependency shape
  against the canonical repository Makefile.
- **Authoritative source:** `Makefile` `make-policy`;
  `scripts/validate_make_policy.py`.
- **Canonical invocation:** `uv run python scripts/validate_make_policy.py`.
- **Trigger and scope:** member of `make ci-quality`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 1 on missing targets / missing
  prerequisites; exits 2 on usage errors.
- **Skip semantics:** none.
- **Inputs and configuration:** the repository Makefile via `make -p`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal policy report.
- **Requirements:** uv environment; `make`.
- **Side effects:** none.
- **Replication checks:** clean => 0; missing target/dependency => 1.

#### `make.workflow-policy`: GitHub Actions workflow policy (strict)

- **Purpose:** validate every workflow against the YAML 1.2 semantic policy in
  strict mode.
- **Authoritative source:** `Makefile` `workflow-policy`;
  `scripts/validate_workflow_policy.py`.
- **Canonical invocation:** `uv run python scripts/validate_workflow_policy.py
  --strict` against `.github/workflows/`.
- **Trigger and scope:** member of `make ci-quality`; on-demand.
- **Execution context:** Local developer workstation; repository checkout; untrusted-local
  (developer) trust boundary.
- **Contextual enforcement:** exits 1 on any hard error OR any warning (strict
  mode promotes warnings to errors); exits 2 on usage errors.
- **Skip semantics:** none.
- **Inputs and configuration:** `.github/workflows/*.yml` via ruamel.yaml
  (duplicate keys rejected).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal policy report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** clean => 0; unpinned action / missing timeout under
  strict => 1.


### CI workflow cards

`ci.yml` has exactly seventeen jobs. Workflow-level concurrency: group
`ci-<workflow>-<pr-number | dispatch-run-id | ref>`, `cancel-in-progress:
true` except for `workflow_dispatch`. Each job runs in a clean checkout with
`uv sync --all-extras --locked --group dev` and delegates to Make targets.
The `test-coverage` job installs gitleaks 8.30.1 before running the suite
because the authoritative gitleaks tests fail when the binary is absent. The
`repository-policy` job is the required source of truth for the deterministic
offline quality gates: it warms the pinned uvx tool cache (semgrep/actionlint)
so `make ci-quality` does not stall on first-use downloads, then runs the
full inventory.

#### `ci.ci.secret-scan`: Secret Scan (gitleaks)

- **Purpose:** full-history secret scan in CI.
- **Authoritative source:** `.github/workflows/ci.yml` job `secret-scan`.
- **Canonical invocation:** installs gitleaks 8.30.1 then `make gitleaks-ci`.
- **Trigger and scope:** all CI events (push master, pull_request,
  workflow_dispatch). Ubuntu; timeout 5 min.
- **Execution context:** clean-room Ubuntu; fetch-depth 0 (full history).
- **Contextual enforcement:** fails the job on secrets (exit 10) or
  missing/wrong gitleaks (exit 3).
- **Skip semantics:** none.
- **Inputs and configuration:** gitleaks 8.30.1 pinned by the workflow install
  step.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal scan output.
- **Requirements:** network to download gitleaks 8.30.1.
- **Side effects:** none.
- **Replication checks:** clean => pass; seeded secret => fail.

#### `ci.ci.static`: Static Analysis (Python 3.12)

- **Purpose:** static analysis plus OpenCode/config/contract/semgrep lanes.
- **Authoritative source:** `.github/workflows/ci.yml` job `static`.
- **Canonical invocation:** steps run `make ci-static`, `make opencode-check`,
  `make opencode-audit`, `make analyser-contract-tests`, `make semgrep`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 10 min; Python 3.12;
  `npm --prefix .opencode ci` step.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events (push master,
  pull_request, workflow_dispatch); permissions `contents: read`; Python 3.12; clean-room
  checkout.
- **Contextual enforcement:** fails the job on any step failure.
- **Skip semantics:** `opencode-check` resolved-config step skips when the
  OpenCode CLI is absent.
- **Inputs and configuration:** as the Make targets.
- **Ordering and concurrency:** sequential steps.
- **Outputs and evidence:** terminal output.
- **Requirements:** network for npm ci / uvx tool fetch.
- **Side effects:** none.
- **Replication checks:** each step behaves as its Make card.

#### `ci.ci.test-coverage`: Test Coverage (Python 3.12)

- **Purpose:** coverage-enforced test lane.
- **Authoritative source:** `.github/workflows/ci.yml` job `test-coverage`.
- **Canonical invocation:** `make ci-test-coverage`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 15 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12.
- **Contextual enforcement:** fails the job on tests, global floor, or
  per-module floor.
- **Skip semantics:** as `make.test`.
- **Inputs and configuration:** as `make.test-coverage`.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment; gitleaks 8.30.1 (installed by the job
  before the suite runs, because the authoritative gitleaks tests fail when
  the binary is absent).
- **Side effects:** coverage artefacts in the job workspace.
- **Replication checks:** as `make.test-coverage`.

#### `ci.ci.hermetic-integration`: Hermetic Integration (Python 3.12)

- **Purpose:** run the loopback-only hermetic integration lane under the
  fail-closed network guard (default-on; no bypass).
- **Authoritative source:** `.github/workflows/ci.yml` job
  `hermetic-integration`; `make test-integration`.
- **Canonical invocation:** `make test-integration`
  (`uv run pytest tests/ -q --tb=short -m hermetic_integration`, plus the
  `MUTATION_PROPERTY_FILES` `--ignore` manifest).
- **Trigger and scope:** all CI events; Ubuntu; timeout 10 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12; the network guard is default-on, so only
  loopback destinations are reachable.
- **Contextual enforcement:** fails the job on failing hermetic tests.
- **Skip semantics:** none. The registered `integration` marker is excluded
  from both the ordinary and coverage selectors and is not selected here.
- **Inputs and configuration:** `tests/support/protocol_server.py` harness.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (loopback only).
- **Replication checks:** hermetic tests pass offline under the default-on
  guard.

#### `ci.ci.repository-policy`: Repository Policy (Python 3.12)

- **Purpose:** enforce the full deterministic offline quality-gate inventory
  (`make ci-quality`) in CI, after warming the pinned uvx tool cache so the
  required job does not stall on first-use tool downloads.
- **Authoritative source:** `.github/workflows/ci.yml` job `repository-policy`;
  `make ci-quality`.
- **Canonical invocation:** warms the uvx tool cache (`uvx --from
  semgrep==1.171.0 semgrep --version` and `uvx --from
  actionlint-py==1.7.12.24 actionlint --version`), then `make ci-quality`
  (`format-check lint typecheck-all bandit vulture complexity semgrep
  arch-check arch-check-dynamic import-linter coupling-check ratchets
  analyser-contract-tests deptry make-policy workflow-policy actionlint`).
- **Trigger and scope:** all CI events; Ubuntu; timeout 30 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12.
- **Contextual enforcement:** fails the job on any inventory member failure.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.ci-quality`; the uvx warm-cache step
  pre-fetches the pinned semgrep 1.171.0 and actionlint-py 1.7.12.24 binaries
  (package-job tools such as twine stay with the package job).
- **Ordering and concurrency:** independent required job; the warm-cache step
  precedes the inventory run.
- **Outputs and evidence:** terminal output from every inventory member.
- **Requirements:** uv environment; network to fetch the pinned uvx tools on
  first use; no repository secrets.
- **Side effects:** uvx tool cache in the job workspace.
- **Replication checks:** `make ci-quality` passes locally with the same warm
  uvx precondition; the guide's `make.ci-quality` membership matches the
  Makefile prerequisites.

#### `ci.ci.test-compat`: Compatibility matrix (3.13, 3.14)

- **Purpose:** run the ordinary suite on newer CPython versions.
- **Authoritative source:** `.github/workflows/ci.yml` job `test-compat`.
- **Canonical invocation:** `make ci-test-compat`; matrix
  `python-version: ['3.13', '3.14']`, `fail-fast: false`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 15 min.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.13/3.14 matrix.
- **Contextual enforcement:** fails the matrix cell on failing tests
  (`fail-fast: false` so both versions run).
- **Skip semantics:** as `make.test`.
- **Inputs and configuration:** as `make.test`.
- **Ordering and concurrency:** independent matrix.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment per Python.
- **Side effects:** none.
- **Replication checks:** as `make.test`.

#### `ci.ci.property`: Property Tests (Python 3.13)

- **Purpose:** thorough property lane.
- **Authoritative source:** `.github/workflows/ci.yml` job `property`.
- **Canonical invocation:** `make ci-property` with `PROPERTY_PROFILE: ci`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 20 min; Python 3.13
  ONLY (property lane does not run on 3.12/3.14/macOS).
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.13 only.
- **Contextual enforcement:** fails the job on property failure or manifest
  mismatch.
- **Skip semantics:** none.
- **Inputs and configuration:** ci profile (1000 examples, 500 ms deadline).
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** `.hypothesis/`.
- **Replication checks:** as `make.test-property-ci`.

#### `ci.ci.fuzz-status`: Fuzz Status (Python 3.12)

- **Purpose:** authoritative fuzz lane.
- **Authoritative source:** `.github/workflows/ci.yml` job `fuzz-status`.
- **Canonical invocation:** `make ci-fuzz-status`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 10 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12; atheris linux x86_64.
- **Contextual enforcement:** BLOCKING — no `continue-on-error`; fails the job
  on fuzz failure or missing atheris.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.test-fuzz`; atheris linux x86_64.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** atheris on linux x86_64.
- **Side effects:** harness temp state.
- **Replication checks:** as `make.test-fuzz`.

#### `ci.ci.package`: Build & Package (Python 3.12)

- **Purpose:** build and verify distributions, then upload them.
- **Authoritative source:** `.github/workflows/ci.yml` job `package`.
- **Canonical invocation:** `make ci-package`; uploads
  `dist/*.whl` + `dist/*.tar.gz` as `wheel-dist-<run_id>-<run_attempt>`
  (`if-no-files-found: error`, 7-day retention).
- **Trigger and scope:** all CI events; Ubuntu; timeout 10 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12.
- **Contextual enforcement:** fails the job on build/verify failure or missing
  artefacts.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.ci-package`.
- **Ordering and concurrency:** independent job; producer for the two smoke
  jobs.
- **Outputs and evidence:** workflow artefact consumed by
  `wheel-smoke-linux`/`wheel-smoke-macos`.
- **Requirements:** uv environment.
- **Side effects:** writes `dist/`.
- **Replication checks:** distributions built, verified, uploaded.

#### `ci.ci.wheel-smoke-linux`: Wheel Smoke (Linux)

- **Purpose:** smoke-test the installed wheel on Linux.
- **Authoritative source:** `.github/workflows/ci.yml` job `wheel-smoke-linux`.
- **Canonical invocation:** downloads `wheel-dist-<run_id>-<run_attempt>` to
  `dist/`, then `make smoke-test`.
- **Trigger and scope:** all CI events; `needs: [package]`; Ubuntu; timeout
  5 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12; depends on the `package` job artefact.
- **Contextual enforcement:** fails the job when the smoke test fails.
- **Skip semantics:** none.
- **Inputs and configuration:** package-job wheel.
- **Ordering and concurrency:** depends on `ci.ci.package`.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv.
- **Side effects:** temp venv/config.
- **Replication checks:** as `make.smoke-test`.

#### `ci.ci.wheel-smoke-macos`: Wheel Smoke (macOS)

- **Purpose:** smoke-test the installed wheel on macOS.
- **Authoritative source:** `.github/workflows/ci.yml` job `wheel-smoke-macos`.
- **Canonical invocation:** downloads the package wheel, then `make smoke-test`.
- **Trigger and scope:** all CI events; `needs: [package]`; macos-latest;
  timeout 5 min; Python 3.12.
- **Execution context:** GitHub Actions `macos-latest`; all CI events; permissions
  `contents: read`; Python 3.12; depends on the `package` job artefact.
- **Contextual enforcement:** fails the job when the smoke test fails.
- **Skip semantics:** none.
- **Inputs and configuration:** package-job wheel.
- **Ordering and concurrency:** depends on `ci.ci.package`.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv.
- **Side effects:** temp venv/config.
- **Replication checks:** as `make.smoke-test`.

#### `ci.ci.windows_packaging_smoke`: Windows Packaging Smoke (Python 3.12)

- **Purpose:** prove the wheel installs and all three console entry points run
  on Windows with network-free, bounded commands.
- **Authoritative source:** `.github/workflows/ci.yml` job
  `windows_packaging_smoke`; `tests/test_distribution_contract.py` topology
  spec.
- **Canonical invocation:** downloads `wheel-dist-<run_id>-<run_attempt>` to
  `dist/`, installs the wheel into an isolated venv, then runs the bounded
  smoke commands `pxcli --version`, `pxcli config show`, `pxcli skill show`,
  `perplexity-cli --version`, `pxcli-mcp --help`.
- **Trigger and scope:** all CI events; `needs: [package]`; windows-latest;
  timeout 15 min; Python 3.12.
- **Execution context:** GitHub Actions `windows-latest`; all CI events; permissions
  `contents: read`; Python 3.12; depends on the `package` job artefact.
- **Contextual enforcement:** fails the job when the wheel cannot install or
  any bounded smoke command fails.
- **Skip semantics:** none.
- **Inputs and configuration:** package-job wheel; the smoke command set from
  `tests/test_distribution_contract.py` (`_WINDOWS_CI_SMOKE_COMMANDS`), which
  forbids network-triggering subcommands and forces `pxcli-mcp --help` (never
  daemonises).
- **Ordering and concurrency:** depends on `ci.ci.package`.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv; network to fetch wheel dependencies on first install.
- **Side effects:** isolated venv in the job workspace.
- **Replication checks:** the five bounded commands pass against the installed
  wheel.

#### `ci.ci.safety`: Safety (trusted)

- **Purpose:** fail-closed authenticated Safety on trusted pushes only.
- **Authoritative source:** `.github/workflows/ci.yml` job `safety`.
- **Canonical invocation:** `make safety-gate` with `SAFETY_API_KEY` from
  secrets.
- **Trigger and scope:** **push events only** (`if: github.event_name ==
  'push'`). NOT run for PRs (external forks and PRs have no secret). Ubuntu;
  timeout 15 min; Python 3.13.
- **Execution context:** GitHub Actions `ubuntu-latest`; trusted push events only;
  permissions `contents: read`; Python 3.13; `SAFETY_API_KEY` from repository secrets.
- **Contextual enforcement:** fails the job when credentials are missing or the
  authenticated scan fails.
- **Skip semantics:** job skipped when the event is not a push (a workflow
  skip, distinct from a pass).
- **Inputs and configuration:** `SAFETY_API_KEY` secret; Safety pinned 3.8.1.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** repository secret. The repository never uses
  `pull_request_target`, so secrets are never exposed to PR or fork contexts.
- **Side effects:** network read of Safety API.
- **Replication checks:** as `make.safety-gate`.

#### `ci.ci.pip-audit`: Pip Audit (Python 3.12)

- **Purpose:** credential-free vulnerability audit on every event.
- **Authoritative source:** `.github/workflows/ci.yml` job `pip-audit`.
- **Canonical invocation:** `make pip-audit`.
- **Trigger and scope:** all CI events; Ubuntu; timeout 10 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; all CI events; permissions
  `contents: read`; Python 3.12; credential-free (forks included).
- **Contextual enforcement:** fails the job on known vulnerabilities or audit
  errors.
- **Skip semantics:** none.
- **Inputs and configuration:** as `make.pip-audit`.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** network.
- **Side effects:** network read.
- **Replication checks:** as `make.pip-audit`.

#### `ci.ci.test-macos`: macOS (Python 3.12)

- **Purpose:** Darwin compatibility signal (ordinary suite, no coverage).
- **Authoritative source:** `.github/workflows/ci.yml` job `test-macos`.
- **Canonical invocation:** `make ci-test-compat`.
- **Trigger and scope:** all CI events; macos-latest; timeout 20 min;
  Python 3.12. This is a compatibility lane, NOT a full pipeline; wheel-level
  macOS coverage comes from `wheel-smoke-macos`.
- **Execution context:** GitHub Actions `macos-latest`; all CI events; permissions
  `contents: read`; Python 3.12.
- **Contextual enforcement:** fails the job on failing tests.
- **Skip semantics:** as `make.test`.
- **Inputs and configuration:** as `make.test`.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** as `make.test`.

#### `ci.ci.diff-coverage`: Diff Coverage (Python 3.12)

- **Purpose:** enforce changed-line coverage on PRs.
- **Authoritative source:** `.github/workflows/ci.yml` job `diff-coverage`.
- **Canonical invocation:** `make test-coverage-report`, then
  `make diff-coverage BASE_SHA=<pr base.sha> TESTED_SHA=<pr head.sha>`.
- **Trigger and scope:** **PR events only** (`if: github.event_name ==
  'pull_request'`); fetch-depth 0. Ubuntu; timeout 10 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; PR events only; permissions
  `contents: read`; Python 3.12; fetch-depth 0.
- **Contextual enforcement:** fails the job below 90% on changed lines or when
  `coverage.xml` is missing.
- **Skip semantics:** job skipped for non-PR events.
- **Inputs and configuration:** PR base/head SHAs; `DIFF_COVERAGE_THRESHOLD=90`.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** terminal report.
- **Requirements:** uv environment.
- **Side effects:** coverage artefacts.
- **Replication checks:** as `make.diff-coverage`.

#### `ci.ci.mutation-diff`: Mutation Diff (Python 3.12)

- **Purpose:** diff-scoped mutation testing on PRs.
- **Authoritative source:** `.github/workflows/ci.yml` job `mutation-diff`.
- **Canonical invocation:** `make mutate-diff BASE_SHA=<pr base.sha>
  TESTED_SHA=<pr head.sha>`.
- **Trigger and scope:** **PR events only**; fetch-depth 0. Ubuntu; timeout
  45 min; Python 3.12.
- **Execution context:** GitHub Actions `ubuntu-latest`; PR events only; permissions
  `contents: read`; Python 3.12; fetch-depth 0.
- **Contextual enforcement:** fails the job on surviving diff mutants.
- **Skip semantics:** no changed production source files => script prints a
  skip and exits 0 (not-applicable).
- **Inputs and configuration:** PR base/head SHAs; `[tool.mutmut]`.
- **Ordering and concurrency:** independent job.
- **Outputs and evidence:** `.mutmut-cache`.
- **Requirements:** uv environment; mutmut.
- **Side effects:** `.mutmut-cache`.
- **Replication checks:** as `make.mutate-diff`.

### Scheduled and supporting workflow cards

#### `automation.mutation-scheduled.mutation`: Full Mutation Policy

- **Purpose:** run the full mutation policy weekly and report the result.
- **Authoritative source:** `.github/workflows/mutation-scheduled.yml` job
  `mutation`; `make mutate-full-policy`.
- **Canonical invocation:** `make mutate-full-policy` on Python 3.12.
- **Trigger and scope:** schedule `0 2 * * 0` (Sunday 02:00 UTC) or
  `workflow_dispatch`. Timeout 360 min.
- **Execution context:** Ubuntu; contents: read.
- **Contextual enforcement:** the mutation step is a BLOCKING producer — it can
  fail the job (exit 1/2). Summary and upload steps use `if: always()`.
- **Skip semantics:** none.
- **Concurrency:** group `mutation-{scheduled|dispatch-<run_id>}`;
  `cancel-in-progress: true` for dispatches ONLY — scheduled runs are never
  cancelled.
- **Inputs and configuration:** as `make.mutate-full-policy`;
  `quality/schemas/mutation-report.json`.
- **Outputs and evidence:** `build/reports/mutation-report.json` + `mutants/`
  metadata uploaded with 30-day retention (`if-no-files-found: warn`); job
  summary with the policy verdict.
- **Requirements:** uv environment; mutmut; 6-hour ceiling.
- **Side effects:** writes `.mutmut-cache`, `mutants/`, `build/reports/`.
- **Replication checks:** clean/findings/tool-error exit mapping; summary and
  upload always run; missing report tolerated.

#### `automation.scorecard.scorecard`: Scorecard (producer)

- **Purpose:** run OpenSSF Scorecard and publish results/SARIF.
- **Authoritative source:** `.github/workflows/scorecard.yml` job `scorecard`.
- **Canonical invocation:** `ossf/scorecard-action` (pinned) with
  `publish_results: true`.
- **Trigger and scope:** schedule `0 6 * * 1` (Monday 06:00 UTC) or
  `workflow_dispatch`; `if: always()`. Timeout 10 min.
- **Execution context:** Ubuntu; permissions contents: read, id-token: write,
  security-events: write (least privilege for publishing).
- **Contextual enforcement:** the job runs the Scorecard action; failures fail
  the job.
- **Skip semantics:** none.
- **Concurrency:** group `scorecard-{scheduled|dispatch-<run_id>}`;
  `cancel-in-progress: true` for dispatches only.
- **Inputs and configuration:** Scorecard action pinned by SHA.
- **Outputs and evidence:** `results.sarif` uploaded as a 30-day artefact
  (`if-no-files-found: error`) for the validator.
- **Requirements:** network.
- **Side effects:** none.
- **Replication checks:** SARIF produced; artefact uploaded.

#### `automation.scorecard.scorecard-validate`: Scorecard (validator)

- **Purpose:** validate the SARIF and upload it to code scanning.
- **Authoritative source:** `.github/workflows/scorecard.yml` job
  `scorecard-validate`.
- **Canonical invocation:** downloads the producer SARIF, validates shape, and
  uploads via `github/codeql-action/upload-sarif` with
  `category: openssf-scorecard`.
- **Trigger and scope:** `needs: [scorecard]`; `if: always()`.
- **Execution context:** Ubuntu; permissions contents: read,
  security-events: write.
- **Contextual enforcement:** fails when the SARIF is missing/empty/invalid.
- **Skip semantics:** none.
- **Concurrency:** same workflow group as the producer.
- **Inputs and configuration:** producer artefact.
- **Outputs and evidence:** code scanning findings under `openssf-scorecard`.
- **Requirements:** network.
- **Side effects:** none.
- **Replication checks:** valid SARIF uploaded; invalid fails.

#### `automation.semgrep-advisory.semgrep-advisory`: Latest Community Rules

- **Purpose:** scan the latest community packs as an advisory signal.
- **Authoritative source:** `.github/workflows/semgrep-advisory.yml` job
  `semgrep-advisory`; `make semgrep-advisory-report`.
- **Canonical invocation:** `make semgrep-advisory-report` on Python 3.13.
- **Trigger and scope:** schedule `0 7 * * 2` (Tuesday 07:00 UTC) or
  `workflow_dispatch`. Timeout 30 min.
- **Execution context:** Ubuntu; permissions contents: read,
  security-events: write.
- **Contextual enforcement:** findings are advisory (Semgrep exit 1 does not
  fail); scanner/infrastructure errors CAN fail the job; upload uses
  `if-no-files-found: error`.
- **Skip semantics:** none.
- **Concurrency:** group `semgrep-advisory-{scheduled|dispatch-<run_id>}`;
  `cancel-in-progress: true` for dispatches only.
- **Inputs and configuration:** latest `p/python`, `p/comment`,
  `p/r2c-best-practices` packs. The reviewed blocking snapshot
  (`quality/semgrep-snapshot.json`) is NOT modified.
- **Outputs and evidence:** `build/reports/semgrep-advisory.json` +
  `semgrep-advisory.sarif` uploaded (30-day retention); code scanning under
  `semgrep-advisory`.
- **Requirements:** network.
- **Side effects:** writes `build/reports/`.
- **Replication checks:** report produced; findings advisory; scanner error
  fails; snapshot untouched.

#### `automation.release-drafter.update_release_draft`: Update Release Draft

- **Purpose:** maintain draft GitHub Release notes for the next tag.
- **Authoritative source:** `.github/workflows/release-drafter.yml`;
  `.github/release-drafter.yml`.
- **Canonical invocation:** `release-drafter/release-drafter` (pinned v7.6.0).
- **Trigger and scope:** push to `main`/`master`; PR `opened`, `reopened`,
  `synchronize`, `closed`. NOT a quality gate.
- **Execution context:** GitHub Actions `ubuntu-latest`; push to main/master or PR lifecycle
  events; permissions `contents: write`, `pull-requests: read`.
- **Contextual enforcement:** none (does not block merges or publish).
- **Skip semantics:** label-only events do not rerun it.
- **Concurrency:** group `release-drafter-<ref>`, `cancel-in-progress: true`.
- **Inputs and configuration:** `.github/release-drafter.yml` label-to-category
  map and version resolver (`v$RESOLVED_VERSION`).
- **Outputs and evidence:** draft release notes on GitHub.
- **Requirements:** GITHUB_TOKEN.
- **Side effects:** updates a draft GitHub Release.
- **Replication checks:** draft updated on qualifying events.

### Release workflow cards

#### `release.publish-to-pypi.publish`: Publish Distribution

- **Purpose:** validate, run trusted CI, publish to PyPI via OIDC, and create a
  GitHub Release.
- **Authoritative source:** `.github/workflows/publish-to-pypi.yml` job
  `publish`.
- **Canonical invocation:** tag `v*` push; Python 3.13; `make ci-trusted` with
  `SAFETY_API_KEY`.
- **Trigger and scope:** push tags matching `v*`. Timeout 30 min.
- **Execution context:** Ubuntu; workflow permissions `contents: write`,
  `id-token: write`.
- **Contextual enforcement:** fails on version-agreement mismatch, CI failure,
  or publish error. Version agreement: tag == `pyproject.toml` version ==
  runtime `__version__`.
- **Skip semantics:** none.
- **Concurrency:** group `publish-<tag-ref>`, `cancel-in-progress: true`
  (same-tag re-pushes cancel superseded runs).
- **Inputs and configuration:** OIDC trusted publishing;
  `pypa/gh-action-pypi-publish` v1.14.1 with `skip-existing: true`;
  `softprops/action-gh-release` v3.0.2 with `draft: false`,
  `prerelease: false`, `files: dist/*`.
- **Outputs and evidence:** PyPI package; non-draft GitHub Release with `dist/*`
  attached.
- **Requirements:** PyPI OIDC trust configured; `SAFETY_API_KEY` secret.
- **Side effects:** **network-write** (PyPI upload, Release creation).
- **Replication checks:** version agreement enforced; trusted CI passes; OIDC
  publish; release created with artefacts; skip-existing honoured.

### Test lanes

#### `test.unit`: Ordinary unit lane

- **Purpose:** the safe ordinary test suite.
- **Authoritative source:** `Makefile` `test`; marker set in `pyproject.toml`.
- **Canonical invocation:** `make test` (see `make.test`).
- **Trigger and scope:** pre-commit stage 5; compat/macOS CI; on-demand.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer/CI) trust boundary.
- **Contextual enforcement:** fails on any failing test.
- **Skip semantics:** excludes `property`, `hermetic_integration`, `real_api`,
  `manual`, `real_user_config`, `fuzz`.
- **Inputs and configuration:** as `make.test`.
- **Ordering and concurrency:** xdist `-n auto`, fail-fast.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** `.pytest_cache`.
- **Replication checks:** as `make.test`.

#### `test.coverage`: Coverage lane

- **Purpose:** enforce global and per-module coverage.
- **Authoritative source:** `Makefile` `test-coverage`; `pyproject.toml`
  `[tool.coverage]`.
- **Canonical invocation:** `make test-coverage` / `make test-coverage-report`.
- **Trigger and scope:** pre-push stage 3; CI coverage/diff-coverage jobs;
  on-demand.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer/CI) trust boundary.
- **Contextual enforcement:** global `fail_under` 85, per-module 85, branch
  coverage, diff coverage 90 (PR).
- **Skip semantics:** as `make.test` exclusions.
- **Inputs and configuration:** `MIN_COVERAGE`, `fail_under`, branch on.
- **Ordering and concurrency:** consumes/produces coverage artefacts.
- **Outputs and evidence:** `coverage.json`, `coverage.xml`, `.coverage`.
- **Requirements:** uv environment.
- **Side effects:** coverage artefacts.
- **Replication checks:** as `make.test-coverage` / `make.diff-coverage`.

#### `test.hermetic-integration`: Hermetic integration lane

- **Purpose:** loopback-only integration tests.
- **Authoritative source:** `Makefile` `test-integration`; marker
  `hermetic_integration`.
- **Canonical invocation:** `make test-integration`.
- **Trigger and scope:** on-demand.
- **Execution context:** Local/CI test runner; repository checkout; loopback-only (no real
  network); untrusted-local.
- **Contextual enforcement:** fails on failing hermetic tests.
- **Skip semantics:** none.
- **Inputs and configuration:** `tests/support/protocol_server.py`; network
  guard fixtures.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none (loopback).
- **Replication checks:** hermetic tests pass offline.

#### `test.property`: Property lane

- **Purpose:** Hypothesis property tests with profile-controlled examples.
- **Authoritative source:** `Makefile` `test-property[-push|-ci]`;
  `tests/conftest.py` profiles; `quality/property-inventory.toml`.
- **Canonical invocation:** `make test-property` (dev 10), `make
  test-property-push` (50), `make test-property-ci` (1000).
- **Trigger and scope:** pre-push stage 4 (push profile); CI property job
  (Python 3.13, ci profile); release (ci profile).
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local; CI runs
  it on Python 3.13 only (`ci.ci.property`); the tag release lane also runs the ci profile
  inside `make ci-trusted`.
- **Contextual enforcement:** blocks on property failure or manifest parity
  (`test-property-policy` prerequisite).
- **Skip semantics:** none.
- **Inputs and configuration:** all Hypothesis profiles use a **500 ms
  deadline**; `fast` (3 examples) is registered but unwired; per-test
  `@settings` may override.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output; `.hypothesis/`.
- **Requirements:** uv environment; hypothesis.
- **Side effects:** `.hypothesis/`.
- **Replication checks:** as the selected lane.

#### `test.fuzz`: Fuzz lane

- **Purpose:** atheris fuzz harnesses.
- **Authoritative source:** `Makefile` `test-fuzz`; `tests/test_fuzz.py`.
- **Canonical invocation:** `make test-fuzz`.
- **Trigger and scope:** pre-push stage 6; CI `fuzz-status` (blocking).
- **Execution context:** Local/CI test runner; repository checkout; atheris linux x86_64
  only; untrusted-local.
- **Contextual enforcement:** fails loudly (no skip) on harness failure or
  missing atheris.
- **Skip semantics:** none; atheris only on linux x86_64.
- **Inputs and configuration:** `-m fuzz`.
- **Ordering and concurrency:** `-x`; subprocess per harness.
- **Outputs and evidence:** terminal output.
- **Requirements:** atheris linux x86_64.
- **Side effects:** harness temp state.
- **Replication checks:** as `make.test-fuzz`.

### Test-enforced meta-gates

These test modules enforce repository policy through tests. They are part of
the ordinary suite unless infrastructure-excluded from Mutmut.

#### `test.policy-help-doc-drift`: CLI help / README / guide drift

- **Purpose:** guard CLI help, `README.md`, and `QUALITY_GATES.md` against
  drift from the implementation.
- **Authoritative source:** `tests/test_help_doc_drift.py`.
- **Canonical invocation:** run as part of `make test`.
- **Trigger and scope:** ordinary suite; Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails the test run on documented-contract drift.
- **Skip semantics:** none.
- **Inputs and configuration:** CLI help output; README; guide.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** help/README claims match implementation.

#### `test.policy-quality-gates-documentation`: Quality-guide semantic drift

- **Purpose:** parse `QUALITY_GATES.md` structure and cross-check cards against
  executable sources (thresholds/toggles, Lefthook topology, Make composites,
  workflow/job sets, plugin registration, profiles, paths, stale phrases).
- **Authoritative source:** `tests/test_quality_gates_documentation.py`;
  Mutmut-excluded in `pyproject.toml`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`).
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails the test run on documented vs executable
  mismatch.
- **Skip semantics:** none — a card or guide claim that drifts from the
  executable sources fails the test run.
- **Inputs and configuration:** this guide; executable sources.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment; strict YAML parser.
- **Side effects:** none.
- **Replication checks:** negative synthetic cases prove parsers fail closed.

#### `test.policy-quality-pipeline`: Analyser/Make pipeline wiring

- **Purpose:** regression-test canonical analyser and Make pipeline wiring.
- **Authoritative source:** `tests/test_quality_pipeline_configuration.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails on wiring regressions.
- **Skip semantics:** none.
- **Inputs and configuration:** Makefile/Lefthook text and scripts.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** declared topology matches sources.

#### `test.policy-workflow-configuration`: Workflow topology policy

- **Purpose:** static policy tests for workflow configuration (pinning,
  concurrency, needs, trusted Safety, Scorecard permissions).
- **Authoritative source:** `tests/test_workflow_configuration.py`.
- **Canonical invocation:** pre-commit `workflow-policy` job on workflow
  changes; part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); pre-commit `workflow-policy` job on
  staged workflow changes; Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite and the
  pre-commit `workflow-policy` job.
- **Contextual enforcement:** fails on workflow policy violations.
- **Skip semantics:** none.
- **Inputs and configuration:** `.github/workflows/*.yml` parsed via
  `ruamel.yaml`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** external-action pinning and topology invariants.

#### `test.policy-make`: Make ownership and dependency policy

- **Purpose:** validate Make target ownership and dependency structure.
- **Authoritative source:** `tests/test_make_policy.py`;
  `scripts/validate_make_policy.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails on invalid Make target/dependency metadata.
- **Skip semantics:** none.
- **Inputs and configuration:** Makefile `.PHONY` and prerequisite parsing.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment; make.
- **Side effects:** none.
- **Replication checks:** parser negatives and end-to-end CLI tests.

#### `test.policy-property`: Property manifest policy

- **Purpose:** enforce exact inventory parity and marker policy.
- **Authoritative source:** `tests/test_property_policy.py`.
- **Canonical invocation:** `make test-property-policy` (prerequisite of every
  property target); part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); prerequisite of every property lane
  (`make test-property[-push|-ci]`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite and as a
  prerequisite of every property lane.
- **Contextual enforcement:** blocks property lanes on stale/missing/duplicate
  IDs.
- **Skip semantics:** none.
- **Inputs and configuration:** `quality/property-inventory.toml`;
  `PROPERTY_TEST_FILES`.
- **Ordering and concurrency:** prerequisite.
- **Outputs and evidence:** terminal parity report.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** exact bidirectional parity.

#### `test.policy-schema-drift`: Schema-drift ratchet

- **Purpose:** fail if a new hand-written command-result schema dict appears.
- **Authoritative source:** `tests/test_schema_drift.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails on new hand-written `*SCHEMA*` dicts.
- **Skip semantics:** accepted debt (grandfathered
  `COMMAND_RESULT_SCHEMAS`) is allowed; shrinking the debt is encouraged.
- **Inputs and configuration:** `_ACCEPTED_DEBT` set; AST scan of `src/`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** new dict fails; removed accepted-debt entry fails with
  shrink guidance.

#### `test.policy-repository-hygiene`: Repository hygiene

- **Purpose:** forbid tracked paths that should be ignored (reports, caches,
  build output).
- **Authoritative source:** `tests/test_repository_hygiene.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails when a forbidden path is tracked.
- **Skip semantics:** none.
- **Inputs and configuration:** `FORBIDDEN_PATHS` (incl. `build/**`,
  `dist/**`, `mutants/**`, `coverage.*`, `.safety-project.ini`).
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** git.
- **Side effects:** none.
- **Replication checks:** forbidden tracked path fails.

#### `test.policy-init`: `__init__.py` structural policy

- **Purpose:** keep production `__init__.py` files declarative.
- **Authoritative source:** `tests/test_init_policy.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails on executable logic in `__init__.py`.
- **Skip semantics:** `KNOWN_VIOLATIONS` accepted debt.
- **Inputs and configuration:** AST analysis.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** declarative passes; executable fails.

#### `test.policy-removed-plan-gate`: Removed plan-compliance mechanism

- **Purpose:** ensure the deleted plan-compliance gate mechanism does not
  resurface.
- **Authoritative source:** `tests/test_removed_plan_gate.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails if deleted-mechanism keywords appear in
  tracked files.
- **Skip semantics:** none.
- **Inputs and configuration:** `_DELETED_MECHANISM_KEYWORDS`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** git.
- **Side effects:** none.
- **Replication checks:** removed mechanism absent.

#### `test.policy-quality-ratchets`: Ratchet gate tests

- **Purpose:** run the fast ratchet gates against their baselines.
- **Authoritative source:** `tests/test_quality_ratchets.py`.
- **Canonical invocation:** part of `make test`; Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); Mutmut-excluded; the slower
  pyright-strict and semgrep-architecture ratchets run via `make check`/CI, not here.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite.
- **Contextual enforcement:** fails when a fast ratchet gate regresses.
- **Skip semantics:** slower pyright-strict and semgrep-architecture ratchets
  are exercised by `make check`/CI, not re-run here.
- **Inputs and configuration:** baselines under `quality/baselines/`.
- **Ordering and concurrency:** none.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** gates pass against their tracked baselines.

#### `test.policy-analyser-contracts`: Analyser contract meta-checks

- **Purpose:** exercise contract schema validation and meta-check logic.
- **Authoritative source:** `tests/test_analyser_contracts.py`;
  `scripts/check_analyser_contracts.py`.
- **Canonical invocation:** `make analyser-contract-tests`; part of `make test`;
  Mutmut-excluded.
- **Trigger and scope:** ordinary suite (`make test`); `make analyser-contract-tests` (CI
  `static` job); Mutmut-excluded.
- **Execution context:** Local/CI test runner; repository checkout; untrusted-local
  (developer trust boundary); runs as part of the ordinary `make test` suite and `make
  analyser-contract-tests` (CI `static` job).
- **Contextual enforcement:** fails on invalid contract metadata; production
  `--validate` runs first.
- **Skip semantics:** none.
- **Inputs and configuration:** fixtures under `tests/fixtures/analyser_contracts/`.
- **Ordering and concurrency:** after production validation.
- **Outputs and evidence:** terminal output.
- **Requirements:** uv environment.
- **Side effects:** none.
- **Replication checks:** accepted/rejected forms per the contract schema.

---

## 9. Composite And Topology Reference

### `make check` vs `make ci` vs workflow CI vs `make ci-trusted` vs hooks vs agent subsets

| Surface | Contains | Notes |
|---|---|---|
| `make check` | `format-check lint typecheck-all security complexity semgrep arch-check coupling-check ratchets import-linter arch-check-dynamic suppression-reasons deptry` (all toggles true) | Static only; no coverage consumption |
| Pre-commit stage 2/4 | subset of the same Make targets (globs) + inline guards/fixers | 22 + 8 jobs |
| Pre-push stages | gitleaks, agent-check-no-tests, arch-check, coupling-check, ratchets, test-coverage, test-property-push, sonar-reports, mutate-diff, safety, test-fuzz | Staged, bounded parallelism |
| `make ci` | `ci-static ci-test-coverage ci-fuzz-status pip-audit sonar-reports ci-property ci-package smoke-test` | Local credential-free aggregate; runs sonar-reports and smoke-test DIRECTLY |
| `make ci-quality` | `format-check lint typecheck-all bandit vulture complexity semgrep arch-check arch-check-dynamic import-linter coupling-check ratchets analyser-contract-tests deptry make-policy workflow-policy actionlint` | Deterministic offline quality gates; no tests/build |
| `make ci-conventional` | serial: format-check, lint, typecheck-all, network-guard/isolation tests, test-coverage, test-integration, ci-quality, MCP tests, test-fuzz, OpenCode test:coverage + check, package-contract, gitleaks-ci, architecture model + check | Offline (`UV_OFFLINE=1`); fails at first error |
| `make ci-trusted` | `make ci` + `safety-gate` | Fail-closed authenticated Safety |
| Workflow CI | 17 jobs (see section 6.4 / cards) | Omit sonar-reports; adds gitleaks, opencode, analyser-contracts, semgrep, repository-policy (full ci-quality), compat matrix, macOS, Windows packaging smoke, push-only safety, pip-audit, PR diff-coverage and mutation-diff |
| `make agent-check-no-tests` | pyright, ty, bandit, vulture, radon-cc, radon-mi, semgrep, format-check, lint | Pre-push static group member |
| `make agent-check-push` | test-coverage, safety, fuzz, arch-check, coupling-check, test-property-push | NOT wired into lefthook or make ci |

Key topology facts:

- **Local `make ci` includes `sonar-reports` and `smoke-test` directly**;
  workflow CI omits Sonar and splits the pipeline into isolated jobs.
- **Workflow CI adds** gitleaks full-history, OpenCode plugin/config checks,
  analyser-contract validation/tests, blocking semgrep, the repository-policy
  job (full `make ci-quality` inventory with warmed uvx cache), 3.13/3.14
  compatibility, macOS, Windows packaging smoke, push-only Safety, pip-audit,
  PR diff-coverage, PR mutation-diff.
- **Architecture, coupling, ratchets, deptry, import-linter, and
  dynamic-imports run pre-push/on-demand and in the `repository-policy` CI job
  via `make ci-quality` — NOT as separate CI jobs.**
- **`make test` is the documented safe ordinary test command.** Marker
  exclusions live in the Make recipes (`not property and not
  hermetic_integration and not integration and not real_api and not manual and
  not real_user_config and not fuzz`) plus the literal `MUTATION_PROPERTY_FILES`
  `--ignore` manifest, not in `pyproject.toml` `addopts`.
- `make ci`, `make ci-quality`, `make ci-conventional`, and workflow CI are
  related but NOT equivalent; never claim otherwise.

---

## 10. Tests And Meta-Gates

### Ordinary and coverage lanes

- **`make test`** — the safe default: `-x -n auto`, marker exclusions plus the
  literal `MUTATION_PROPERTY_FILES` manifest, no coverage.
- **`make test-coverage`** — ordinary suite plus global `fail_under` (85) and
  per-module enforcement (`module-coverage`); branch coverage on.
- **`make test-coverage-report`** — produces `coverage.json`/`coverage.xml`
  without per-module enforcement (used by the PR diff-coverage job).
- **`make diff-coverage`** — 90% floor on changed lines (PR only in CI);
  **diff-cover is the sole changed-line authority**.
- **`make test-integration`** — the hermetic lane (`-m hermetic_integration`),
  also run by the `hermetic-integration` CI job under the default-on network
  guard.

### Marker taxonomy

Registered in `pyproject.toml` `[tool.pytest.ini_options] markers` with
`--strict-markers`:

| Marker | Meaning | Excluded from `make test` |
|---|---|---|
| `hermetic_integration` | Loopback-only integration (no real network) | yes |
| `integration` | Protocol/auth or real-service integration paths (may use network) | yes |
| `security` | Security tests | no |
| `slow` | Slow-running | no |
| `real_api` | Calls the real Perplexity API | yes |
| `manual` | Requires interactive input | yes |
| `real_user_config` | Uses the real user config directory | yes |
| `fuzz` | Atheris fuzz tests | yes |
| `property` | Hypothesis property tests | yes |

The registered `integration` marker covers protocol/auth or real-service
integration paths (may use network); loopback-only hermetic tests use
`hermetic_integration`. Both the ordinary (`make test`) and coverage
(`make test-coverage-report`) selectors exclude `integration`. The property
and mutation families are additionally excluded by exact path via
`MUTATION_PROPERTY_FILES` (`--ignore`), per plan decision A003.

### Hypothesis profiles (`tests/conftest.py`)

| Profile | Examples | Deadline | Wiring |
|---|---|---|---|
| `dev` | 10 | 500 ms | `make test-property` |
| `push` | 50 | 500 ms | pre-push stage 4 |
| `ci` | 1000 | 500 ms | CI property job (Python 3.13), `make ci`/release |
| `fast` | 3 | 500 ms | Registered but UNWIRED (no target uses it) |

Every profile has a **500 ms deadline** (there is no "no deadline" profile).
Per-test `@settings` may override.

### Platform placement

- **Property** runs only on Python 3.13 in CI (`ci.ci.property`); never on the
  compat/macOS lanes (which run `make test` and exclude the property marker).
- **macOS** runs `ci.ci.test-macos` (compat, Python 3.12) and
  `ci.ci.wheel-smoke-macos`; nothing else runs there.
- **Fuzz** requires atheris, which installs only on
  `sys_platform == 'linux' and platform_machine == 'x86_64'`. Fuzz CI is a
  blocking job.

### Mutation testing

- **Diff scope:** `make mutate-diff` pre-push (stage 4) and the PR-only
  `ci.ci.mutation-diff` job.
- **Full policy:** `make mutate-full-policy` scheduled weekly (Sunday 02:00
  UTC) and on-demand. Exits: **0** clean, **1** findings, **2** tool-error.
- **Actionable** categories: `survived`, `timeout`, `suspicious`. Waivers are
  NOT supported.
- **Evidence:** live schema is `quality/schemas/mutation-report.json` (the only
  live mutation schema). The generated report is `build/reports/mutation-report.json`
  — a run artefact under the ignored `build/` directory, uploaded by the
  scheduled workflow with 30-day retention. It is NOT tracked in git.
- **Historical figures** (e.g. first-run killed/survived counts and a
  "mutation score") are superseded; live reports are run artefacts, so no
  normative prose carries counts. See [Evidence](#11-evidence-baselines-and-schemas).

### Coverage policy

- **Global floor:** `pyproject.toml` `[tool.coverage.report] fail_under = 85`
  (the `gates.conf` `FAIL_UNDER` is a reference mirror).
- **Per-module floor:** 85 via `scripts/check_module_coverage.py`
  (`MIN_COVERAGE`), including full report integrity validation (all executable
  modules present, branch data present, no duplicate/outside-root entries).
  Owned by `make test-coverage`; never consumed by `make check`.
- **Branch coverage:** enabled (`[tool.coverage.run] branch = true`).
- **Diff coverage:** 90 on changed lines (`DIFF_COVERAGE_THRESHOLD`), PR only.
  **diff-cover is the sole changed-line authority** — exactly one
  diff-coverage consumer exists.

---

## 11. Evidence, Baselines, And Schemas

### Producer/consumer paths

| Evidence | Producer | Consumer(s) | Retention / tracked |
|---|---|---|---|
| `coverage.json` | `make test-coverage-report` | `module-coverage` (`make test-coverage` only — not `make check`) | ignored |
| `coverage.xml` | `make test-coverage-report` | `make diff-coverage` (PR job; sole changed-line authority) | ignored |
| `build/reports/bandit-report.json` | `make sonar-reports` | SonarQube import (external) | ignored |
| `build/reports/semgrep-advisory.{json,sarif}` | `make semgrep-advisory-report` | scheduled workflow artefact + code scanning | ignored; 30-day workflow artefact |
| `build/reports/mutation-report.json` | `make mutate-full-policy` (`scripts/mutation_policy.py`) | scheduled workflow summary/upload; live schema `quality/schemas/mutation-report.json` | ignored; 30-day workflow artefact |
| `mutants/` metadata | mutmut | scheduled workflow upload | ignored; 30-day workflow artefact |
| `dist/*` | `make build` | `verify`, `smoke-test`, CI smoke jobs, release | ignored; 7-day CI artefact |
| `results.sarif` | Scorecard action | validator → code scanning | 30-day artefact |

### Provenance guidance

- Mutable quality observations (mutant counts, timings, coverage percentages
  over time) are run artefacts, not policy. Normative text in this guide
  deliberately avoids embedding current counts.
- Historical first-run mutation figures are superseded and live only in git
  history or explicitly historical evidence under `quality/evidence/` and
  `quality/remediation/`.
- Live schemas under `quality/schemas/` describe evidence shape; producers and
  their tests are the executable contract.

### Baseline refresh protocol

Baselines record **reviewed accepted debt**. Refreshing one MUST be deliberate:

1. Run the gate to see the exact new/removed identities or counts.
2. Review the diff: every added identity is newly accepted debt; every removed
   identity should be a genuine improvement.
3. Refresh with the gate's canonical update command (`--update-baseline`, e.g.
   `uv run python scripts/check_suppressions.py --update-baseline`). Each gate
   has its OWN update command — there is no universal refresh.
4. Do NOT refresh to silence a failure without review; a refreshed baseline is a
   policy decision, not a fix.

### Baselines inventory

| File | Status | Notes |
|---|---|---|
| `quality/baselines/file-size.json` | **active** | counts baseline for `make file-size` |
| `quality/baselines/suppressions.json` | **active** | fingerprint baseline for `make suppression-ratchet` |
| `quality/baselines/suppression-reasons.json` | **active** | fingerprint baseline for `make suppression-reasons` |
| `quality/baselines/semgrep-architecture.json` | **active** | fingerprint baseline for `make semgrep-architecture` |
| `quality/baselines/ruff-architecture.json` | test-only shadow | backs dormant `scripts/check_ruff_architecture.py`; the active gate is `make ruff-architecture` (direct ruff), no baseline |
| `quality/baselines/pyright-strict.json` | test-only shadow | backs dormant `scripts/check_pyright_strict.py`; the active gate is `make typecheck-strict-ratchet` (direct pyright), no baseline |
| `quality/baselines/coupling-report.json` | advisory trend | consumed by `make coupling-report`; advisory, not a ratchet |

Additional repository-root baselines: `.architecture-baseline.json`
(`make arch-check`, applied by default) and `.dynamic-imports-baseline.json`
(`make arch-check-dynamic`, applied by default).

### Schemas inventory

| File | Purpose |
|---|---|
| `quality/schemas/mutation-report.json` | THE live mutation report schema (produced by `scripts/mutation_policy.py`) |
| `quality/schemas/coupling-report-v1.json` | Coupling report shape (advisory evidence) |
| `quality/schemas/differential-context-v1.json` | Differential context shape (`scripts/differential_context.py`) |

Command-result schemas derive from Pydantic models via `model_json_schema()`;
hand-written schema dicts are accepted-debt ratcheted by
`tests/test_schema_drift.py` (see `test.policy-schema-drift`).

### Historical / non-normative evidence

`quality/evidence/` (e.g. `gitleaks-verification.md`, `scorecard-verification.md`,
`quality-remediation-v2.json`, dated remediation subdirectories) and
`quality/remediation/` contain historical records and plans. They are
non-normative; do not treat them as current policy.

---

## 12. Change Protocol

### Add, rename, or retire a gate ID

- **Add:** choose an ID in the appropriate namespace, add the card with all 13
  fields, reference it from the relevant lifecycle/runbook table and the
  catalogue, and keep the semantic-drift tests in agreement (see below).
- **Rename an authority locator:** update the card and ALL references
  atomically. Keep an alias only if an external consumer needs it.
- **Retire:** never reuse a retired ID. Remove the card and its references.

### Change a threshold or toggle

1. Temporarily remove the `deny` rule for `**/quality/gates.conf` from
   `opencode.jsonc`.
2. Edit `quality/gates.conf`.
3. Restore the `deny` rule.
4. **Agents MAY only tighten** thresholds (for example pass a stricter
   `--max-flagged` in the Makefile); they MAY NOT loosen them below the
   `gates.conf` floor.
5. Update this guide's policy tables and the semantic-drift tests atomically.

### Update a baseline

Follow the [Baseline refresh protocol](#baseline-refresh-protocol)
for the specific gate. Never refresh to hide a real regression.

### Modify a workflow

Edit `.github/workflows/*.yml`, then:

- Run `make actionlint` and the workflow-policy tests
  (`tests/test_workflow_configuration.py`).
- Update this guide's workflow cards, the lifecycle map, and the topology
  reference atomically with the change.

### Update the guide and drift tests atomically

`QUALITY_GATES.md` is descriptive. When an executable authority changes:

- Update the executable source first.
- Update the guide (policy tables, runbooks, cards) in the same change.
- Update the semantic-drift tests so they encode the new contract. **The rule
  is: newly discovered documentation/comment/test drift is recorded before it
  is fixed** — journal the drift, then assign and fix it.
- Do not ship a guide that contradicts its own drift tests.

---

## 13. Appendices

### 13.1 Source index

| Concern | File(s) |
|---|---|
| Git hooks | `lefthook.yml` |
| Runnable commands and composites | `Makefile` |
| Thresholds and toggles | `quality/gates.conf`, `scripts/_gates.py` |
| Python tool settings | `pyproject.toml` |
| Blocking Semgrep rules | `.semgrep.yml`, `.semgrep-community-*.yml`, `quality/semgrep-snapshot.json`, `quality/semgrep-policy.toml` |
| Architecture rules | `quality/architecture.toml`, `.architecture-baseline.json`, `.dynamic-imports-baseline.json` |
| Analyser contracts | `quality/analyser-contracts.toml`, `scripts/check_analyser_contracts.py` |
| Property inventory | `quality/property-inventory.toml`, `tests/test_property_policy.py` |
| Mutation policy | `scripts/mutation_policy.py`, `quality/schemas/mutation-report.json` |
| Baselines | `quality/baselines/*`, repository-root baselines |
| Custom analysers | `scripts/*.py`, `scripts/*.sh` |
| OpenCode wiring | `opencode.jsonc`, `.opencode/plugins/*.ts`, `.opencode/scripts/check-config.ts`, `.opencode/package.json` |
| CI workflows | `.github/workflows/ci.yml`, `mutation-scheduled.yml`, `scorecard.yml`, `semgrep-advisory.yml` |
| Release workflows | `.github/workflows/publish-to-pypi.yml`, `release-drafter.yml`, `.github/release-drafter.yml` |
| Tests and meta-gates | `tests/` (see section 10) |
| This guide | `QUALITY_GATES.md` |

### 13.2 Command index

| Command | Purpose |
|---|---|
| `make setup` | Bootstrap env (uv/gitleaks/infisical required) |
| `make configure-opencode` | npm ci + plugin/config validation |
| `make test` | Safe ordinary tests |
| `make test-coverage` | Tests + global/per-module coverage |
| `make test-integration` | Hermetic loopback integration lane |
| `make check` | All enabled `CHECK_*` gates (static only) |
| `make ci` | Local credential-free CI aggregate |
| `make ci-quality` | Deterministic offline quality-gate inventory |
| `make ci-conventional` | Serial offline final gate list |
| `make ci-trusted` | `make ci` + fail-closed Safety |
| `make ratchets` | Six ratchet/hard-gate members |
| `make semgrep` | Blocking immutable Semgrep |
| `make gitleaks-ci` | CI full-history secret scan |
| `make safety-gate` | Fail-closed authenticated Safety (push CI/release) |
| `make pip-audit` | Credential-free vulnerability audit |
| `make mutate-full-policy` | Full mutation + canonical policy |
| `make package-contract` | Build + verify + test + smoke the distribution contract |
| `make release V=x.y.z` | Versioned release (mutates git, pushes) |
| `make actionlint` | Validate workflows |
| `make analyser-contract-tests` | Validate + test analyser contracts |
| `make make-policy` | Validate Make target ownership/dependencies |
| `make workflow-policy` | Validate workflow policy (strict) |

### 13.3 Glossary

- **atomic gate** — a single analyser/guard with one canonical invocation and
  one outcome policy (e.g. `make complexity-cc`).
- **composite** — a Make/hook/workflow aggregate that runs several gates and
  fails if any member fails (e.g. `make ci`, `hook.pre-commit.lint-and-validate`).
- **blocking scoped** — a gate that fails a specific caller (a hook, a job, a
  release). Blocking is always caller-scoped; merge-required status is unknown
  unless repository evidence exists.
- **advisory** — reports findings but never blocks on them (e.g.
  `make refurb`, `make coupling-report`). Scanner/tool errors may still fail.
- **authoritative** — the caller whose failure is enforced (CI job, hook,
  release); distinct from advisory/session feedback.
- **universal** — applies to every CI event including external forks
  (e.g. `pip-audit`).
- **trusted** — applies only to pushes/releases with repository secrets
  (e.g. `make safety-gate`).
- **pass** — the gate ran and found no actionable findings.
- **finding** — an actionable defect reported by a gate.
- **skipped** — the gate did not run (legal skip conditions only). Skipped is
  never called pass.
- **not-applicable** — the gate's scope is empty (e.g. no changed source files
  for diff mutation); treated as success without evidence.
- **tool error** — the gate's tooling failed (missing binary, wrong version,
  unparseable output). Fail-closed gates treat this as failure.
- **fail-closed** — missing/wrong tooling or credentials fails the gate
  (e.g. gitleaks, `safety-gate`, semgrep-architecture).
- **fail-open** — missing tooling degrades to a skip (only the two documented
  legal local skips: infisical CLI missing; Safety credentials unavailable).
- **baseline** — a reviewed record of accepted debt that a ratchet compares
  against; growth is a regression, shrinkage is allowed.
- **threshold** — a numeric floor/cap in `quality/gates.conf` or
  `pyproject.toml`.
- **evidence** — a reproducible artefact (report, schema, exit code) that a gate
  produces or consumes.
- **side effect** — a change to workspace/index/git/cache/temp/network/remote
  state caused by running a gate.
- **replication-equivalent** — two invocations produce the same outcome
  semantics for the same input (used when a card's canonical invocation differs
  from a caller's direct command, e.g. gitleaks pre-push vs `make gitleaks`).

### 13.4 Historical / non-normative references

- Historical remediation and evidence records: `quality/evidence/`,
  `quality/remediation/`, `tests/fixtures/` (analyser-contract fixtures are
  normative for their tests; mutation fixtures were removed with the waiver-era
  schema).
- Older revisions of this guide contained claims that contradicted the
  executable sources, covering: the number and structure of pre-commit stages,
  the coupling budget value, gitleaks failure behaviour, fuzz authority in CI,
  Safety's CI event scope, Hypothesis deadlines, the scope of the analyser
  contract registry, the number of ratchet members, the tracked mutation report
  location, and the hermetic integration marker name. Those claims are
  intentionally absent from this revision: the executable sources are the
  authority, and this guide documents them as they are now.
