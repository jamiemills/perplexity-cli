# Quality Gates and Analysers

A progressive-disclosure reference for every quality gate, analyser, hook,
and CI check in the repository.

---

## Overview

The repository uses a layered defence model. Cheap, deterministic checks run
before a commit. Expensive whole-project checks run before a push. CI repeats
critical checks in a clean environment and adds build validation. The release
workflow proves tag, source, metadata, and artefacts agree before upload.

```
edit code
  |
  v
pre-commit, stage 1: read-only analysers and validators (parallel)
  |
  v
pre-commit, stage 2: staged-file auto-fixers (sequential)
  |
  v
pre-commit, stage 3: unit tests (parallel, xdist)
  |
  v
pre-push: whole-project checks (parallel)
  |
  v
CI: clean-room Ubuntu + macOS, full pipeline
  |
  v
release: version validation, CI, publish

  (OpenCode session plugins run continuously across all stages)
  (quality plan loop: generate -> review runs alongside pre-push/CI)
```

### Gate Categories at a Glance

| Phase | Gates | Tools |
|-------|-------|-------|
| Pre-commit (stage 1) | Type, security, dead-code, complexity, Semgrep, config validation, secret scan, repo hygiene | pyright, ty, bandit, vulture, radon, semgrep, pre-commit-hooks, infisical |
| Pre-commit (stage 2) | Formatting, lint auto-fix, whitespace fix | ruff, pre-commit-hooks |
| Pre-commit (stage 3) | Unit tests (fail-fast, xdist) | pytest, pytest-xdist |
| Pre-push | Secret scan, coverage, dependency vulns, fuzz, architecture, coupling, ratchets, mutation, property tests | gitleaks, pytest-cov, safety, atheris, custom scripts, mutmut, hypothesis |
| CI | All static checks + coverage + fuzz + safety + property + build + verify + smoke | GitHub Actions, same tools as above |
| Release | Version validation, CI, OIDC publish, GitHub Release | GitHub Actions, PyPI OIDC |
| Session | Real-time quality feedback, commit/push interceptors | OpenCode plugins (4), agent (1) |

---

## How to Set Up

`make setup` requires three external tools to be installed first; the
`check-uv`, `check-gitleaks`, and `check-infisical` prerequisites fail fast
with install hints if any are missing.

| Tool | Check target | Purpose | Install |
|---|---|---|---|
| `uv` | `make check-uv` | Python package manager (venv, locked deps) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gitleaks` | `make check-gitleaks` | Pre-push commit-range secret scan | `brew install gitleaks` ([alternatives](https://github.com/gitleaks/gitleaks#installing)) |
| `infisical` | `make check-infisical` | Pre-commit uncommitted-change secret scan | `brew install infisical` ([docs](https://infisical.com/docs/cli/overview)) |

Then:

```bash
make setup               # Python venv, deps, lefthook hooks, CLI verification
make configure-opencode  # npm install in .opencode/, verify plugin/agent wiring
make test                # verify everything works
```

- `make setup` creates the virtualenv, syncs locked dependencies, installs
  lefthook git hooks, and verifies the CLI builds.  It refuses to proceed
  until `uv`, `gitleaks`, and `infisical` are on `PATH`.
- `make configure-opencode` installs node dependencies for the OpenCode
  quality-gate plugins and verifies all plugin files, agent definitions, and
  `opencode.jsonc` are present.
- Both are idempotent — safe to re-run.

### Canonical Sources of Truth

| Artifact | File(s) | Controls |
|----------|---------|----------|
| Git hooks | `lefthook.yml` | Pre-commit and pre-push job topology |
| Runnable targets | `Makefile` | All check, test, build, and setup commands |
| Python tooling | `pyproject.toml` | pytest, ruff, coverage, bandit, vulture, pyright, mutmut |
| Custom Semgrep rules | `.semgrep.yml` | Project-specific code-smell and architecture rules |
| Architecture Semgrep rules | `.semgrep-architecture.yml` | TOCTOU, retry, layering patterns |
| Gate thresholds and toggles | `quality/gates.conf` | Numeric floors and check on/off switches |
| Gate loader | `scripts/_gates.py` | Typed runtime accessor for `gates.conf` |
| Hypothesis profiles | `tests/conftest.py` | dev (10), push (50), ci (1000), fast (3) |
| Custom analysers | `scripts/` | Architecture, coupling, ratchets, plan checker, coverage, reports |
| OpenCode wiring | `opencode.jsonc` | Plugin and agent registration, permissions |
| CI workflows | `.github/workflows/ci.yml` | Ubuntu matrix, macOS, property profile selection |
| Publish workflow | `.github/workflows/publish-to-pypi.yml` | Version validation, CI, OIDC publish |
| Release Drafter workflow | `.github/workflows/release-drafter.yml` | Draft GitHub Release notes on push/PR |
| Release Drafter config | `.github/release-drafter.yml` | Label → category mapping, version resolver |

---

## Central Threshold Configuration

The file `quality/gates.conf` is the single source of truth for the
boolean check toggles and most numeric thresholds. It is locked from agent
edits by a `deny` rule in `opencode.jsonc`. The boolean `CHECK_*` toggles
and the coupling / vulture / radon / file-size floors are consumed at
runtime through `scripts/_gates.py`.

Two entries currently duplicate a value whose active source lives elsewhere
(documented here so the duplication is not "fixed" by mistake):

- `FAIL_UNDER = 85` mirrors `pyproject.toml [tool.coverage.report] fail_under`
  (consumed by pytest-cov directly). `gates.conf` holds the reference value.
- `SEMGREP_SEVERITY = ERROR WARNING` is the intended severity set, but the
  `make semgrep` invocation currently hard-codes `--severity ERROR --severity
  WARNING` in the `Makefile` rather than reading `gates.conf`.

### Quantitative Thresholds

| Key | Default | Controls |
|-----|---------|----------|
| `MAX_FLAGGED` | 10 | Coupling: maximum allowed flagged modules |
| `DISTANCE_THRESHOLD` | 0.3 | Coupling: Martin D flagging threshold |
| `MIN_COVERAGE` | 85 | Coverage: minimum per-module coverage percentage |
| `FAIL_UNDER` | 85 | Coverage: global fail_under threshold |
| `MIN_CONFIDENCE` | 80 | Vulture: minimum confidence for dead-code reporting |
| `RADON_CC_GRADE` | B | Radon: worst-allowed cyclomatic-complexity grade |
| `RADON_MI_GRADE` | B | Radon: worst-allowed maintainability-index grade |
| `FILE_SIZE_CAP` | 1000 | File-size ratchet: maximum source lines per file |
| `SEMGREP_SEVERITY` | ERROR WARNING | Semgrep: minimum severity levels scanned |

### Check Toggles (control which analysers run in `make check`)

| Key | Default | Gate |
|-----|---------|------|
| `CHECK_FORMAT` | true | Ruff format check |
| `CHECK_LINT` | true | Ruff lint check |
| `CHECK_TYPECHECK_ALL` | true | ty + pyright type checkers |
| `CHECK_SECURITY` | true | Bandit + Vulture |
| `CHECK_COMPLEXITY` | true | Radon CC + MI |
| `CHECK_SEMGREP` | true | Semgrep static analysis |
| `CHECK_ARCH` | true | Architecture layer check |
| `CHECK_COUPLING` | true | Coupling and stability metrics |
| `CHECK_RATCHETS` | true | All baseline ratchet gates |

### How to Change Thresholds

1. Temporarily remove the `deny` rule from `opencode.jsonc`.
2. Edit `quality/gates.conf`.
3. Restore the `deny` rule.
4. Agents may tighten (not loosen) thresholds in the Makefile without editing
   `gates.conf` — e.g. pass `--max-flagged 8` instead of 10.

---

## Pre-commit Gates

Pre-commit runs in three sequential stages via `lefthook.yml`. Stage 1 is
read-only and parallel; stage 2 mutates staged files sequentially; stage 3
runs tests.

### Stage 1 — Read-only Analysers and Validators

All stage 1 jobs are parallel, read-only, and configured in `lefthook.yml`.
They reject commits that are structurally unsafe before any formatter runs.

#### Type Checking

| Gate | Command | Tool | Config |
|------|---------|------|--------|
| Pyright | `make typecheck-pyright` | pyright | `[tool.pyright]`, standard mode, Python 3.12 |
| ty | `make typecheck` | ty | CLI-only, no config file |

- **Defends against:** type-contract drift, impossible argument types, optional
  value dereference without guards, stale imports.
- **Placement:** pre-commit, stage 1 — semantic errors fail immediately, before
  formatters or tests spend time on broken code.

#### Security and Dead Code

| Gate | Command | Tool | Config |
|------|---------|------|--------|
| Bandit | `make bandit` | bandit | `[tool.bandit]`, no global rule skips |
| Vulture | `make vulture` | vulture | `[tool.vulture]`, min_confidence 80, whitelist |

- **Bandit:** scans for unsafe subprocess use, weak randomness, hardcoded
  secrets, risky deserialisation, insecure TLS choices.
- **Vulture:** identifies likely unused code. Dead code increases review
  surface and can preserve stale security assumptions.

#### Complexity

| Gate | Command | Tool | Threshold |
|------|---------|------|-----------|
| Cyclomatic complexity | `make complexity-cc` | radon | Grade B or better |
| Maintainability index | `make complexity-mi` | radon | Grade B or better |
| Trend tracking | `make metrics-track` | `scripts/track_metrics.py` | Informational — on demand |

- **CC:** rejects functions with branching complexity >= B grade. Complexity
  correlates with missed edge cases and testing difficulty.
- **MI:** rejects modules whose maintainability index falls below B.
- **Trend tracking:** diffs CC and MI across recent git revisions to surface
  gradual erosion that individual commits hide. Not blocking.

#### Semgrep Static Analysis

| Command | Config | Rules |
|---------|--------|-------|
| `make semgrep` | `.semgrep.yml` + p/python + p/comment + p/r2c-best-practices | Warnings and errors treated as failures; tests excluded |

- **Custom rules cover:** meaningful names, parameter counts, boolean flags,
  comment hygiene, exception handling (no silent `pass`, always `raise X from Y`),
  f-strings in logging, wildcard imports, magic numbers, `eval`/`exec` bans,
  `print()` in library code, layer import restrictions.
- **Community rules:** standard Python best practices, Clean Code patterns.

#### Configuration Validation and Repository Hygiene

| Gate | Command | Tool |
|------|---------|------|
| YAML validation | `check-yaml {staged_files}` | pre-commit-hooks |
| JSON validation | `check-json {staged_files}` | pre-commit-hooks |
| TOML validation | `check-toml {staged_files}` | pre-commit-hooks |
| .env file block | inline git diff script | shell |
| Large file block | `check-added-large-files --maxkb=1000` | pre-commit-hooks |
| Merge conflict check | `check-merge-conflict {staged_files}` | pre-commit-hooks |
| Case conflict check | `check-case-conflict {staged_files}` | pre-commit-hooks |
| Docstring placement | `check-docstring-first {staged_files}` | pre-commit-hooks |
| Test naming | `name-tests-test --pytest-test-first {staged_files}` | pre-commit-hooks |
| Secret scan (uncommitted) | `make infisical-scan` | infisical |

- **.env block:** newly added `.env` files are almost always secret-bearing;
  blocked before commit creation.
- **Infisical:** scans uncommitted git changes for tokens, keys, credentials.
  Skips gracefully when the CLI is not installed.

### Stage 2 — Auto-fixers

Stage 2 runs sequentially (piped) because jobs modify staged files and
re-stage them. Only one mutating tool touches files at a time.

| Gate | Command | Tool | Notes |
|------|---------|------|-------|
| Ruff format | `ruff format {staged_files}` | ruff | Python 3.12 target, 100-char line length; `stage_fixed: true` |
| Ruff lint fix | `ruff check --fix {staged_files}` | ruff | D, E, F, I, C4, B, UP, S101, T10, RUF rules |
| Trailing whitespace | `trailing-whitespace-fixer {staged_files}` | pre-commit-hooks | `stage_fixed: true` |
| End-of-file fixer | `end-of-file-fixer {staged_files}` | pre-commit-hooks | `stage_fixed: true` |

### Stage 3 — Unit Tests

| Command | Tool | Notes |
|---------|------|-------|
| `make test` | pytest + pytest-xdist | `-n auto` (parallel), `-x` (fail-fast), marker exclusions for integration/real_api/manual/fuzz |

- **Placement:** tests run only after static and formatter gates pass.
- **Coverage deferred to pre-push:** per-commit coverage thresholds are too
  expensive for every individual commit.
- **Marker exclusions (in `addopts`):** `not integration and not real_api and
  not manual and not real_user_config and not fuzz`.

---

## Pre-push Gates

Pre-push runs in parallel via `lefthook.yml`. These checks are heavier,
need whole-project context, or are too slow/noisy per commit.

| Gate | Command | Tool(s) |
|------|---------|---------|
| Gitleaks secret scan | `make gitleaks` | gitleaks via `scripts/gitleaks_check.sh` |
| Agent unified check (pre-commit linters, no tests) | `make agent-check-no-tests` | `scripts/agent_check.py` (all stage-1 linters, excludes tests); the only `agent-check*` target wired into `lefthook.yml` pre-push |
| Agent unified check (full pre-push set) | `make agent-check-push` | `scripts/agent_check.py pre-push` (linters + coverage + safety + property); **not currently wired into `lefthook.yml` or `make ci`** — callable on demand for parity with CI |
| Coverage (parallel) | `make test-coverage` | pytest-cov + pytest-xdist (`-n auto`) + `scripts/check_module_coverage.py` |
| Safety dependency scan | `make safety` | safety via `scripts/agent_check.py safety` |
| Fuzz tests | `make test-fuzz` | pytest (atheris fuzz harnesses, `-m fuzz`) |
| Sonar reports | `make sonar-reports` | `scripts/generate_sonar_reports.py` |
| Architecture check | `make arch-check` | `scripts/check_architecture.py` |
| Coupling check | `make coupling-check` | `scripts/check_coupling.py` |
| Quality ratchets (5) | `make ratchets` | `scripts/check_file_size.py`, `check_suppressions.py`, `check_ruff_architecture.py`, `check_pyright_strict.py`, `check_semgrep_architecture.py` |
| Mutation testing (diff) | `make mutate-diff` | mutmut + `scripts/discover_mutate_diff_files.py` |
| Property tests | `make test-property-push` | pytest + hypothesis (push profile: 50 examples) |

### Gitleaks

Scans pushed commit ranges (not just staged changes). Defends against
secrets committed earlier in the branch history. Pre-push is the last
local moment to stop them from reaching the remote.

### Coverage

Enforced both globally and per module at 85%. `[tool.coverage.run]` enables
branch coverage. `scripts/check_module_coverage.py` fails any module below
85%, preventing well-tested modules from masking untested new modules.
Runs with `-n auto` (pytest-xdist) for parallel execution.

### Safety

Checks the resolved dependency set for known vulnerabilities using the Safety
API. Requires `SAFETY_API_KEY` environment variable or Infisical to provide
it via `infisical run --env dev`.  When neither is available, `make safety`
**prints a skip notice and exits 0** — the gate does not fail, but no scan
is performed, so vulnerabilities are not detected until CI (which provides
the key via Infisical).  Treat the local skip as informational, not a pass.

### Architecture Check

`scripts/check_architecture.py` enforces ports-and-adapters layer rules:
domain, application, infrastructure, presentation. Checks import direction,
framework isolation, and adapter coupling. Blocks framework leakage into
domain models and utility backdoors into higher layers.

### Coupling Check

`scripts/check_coupling.py` computes Robert C. Martin package metrics:
afferent coupling (Ca), efferent coupling (Ce), instability (I), abstractness
(A), and distance from main sequence (D). Modules with D >= 0.3 and Ce > 0
are flagged. Applies four filters to reduce noise:

1. **Leaf-dependency filter:** Ce=1 modules whose sole dep is a Ce=0 leaf are
   not flagged.
2. **TYPE_CHECKING guard filter:** imports under `if TYPE_CHECKING:` are excluded.
3. **Function-body filter:** lazy imports inside function bodies are excluded.
4. **Init-only filter:** package `__init__.py` re-export hubs are excluded.

### Quality Ratchets

Five baseline-ratchet gates capture existing structural debt and fail only on
*new* or *grown* findings. Each gate writes a JSON baseline under
`quality/baselines/`. Refresh only after intentional fixes via
`<gate> --update-baseline`.

| Gate | Target | Defends against |
|------|--------|-----------------|
| File-size | `make file-size` | New or grown oversized files (cap from `FILE_SIZE_CAP`) |
| Suppressions | `make suppression-ratchet` | `# noqa` / `# nosec` / `# type: ignore` / `# pyright: ignore` creep |
| Ruff architecture | `make ruff-architecture` | Complexity (C901) and parameter-count (PLR091*) findings |
| Pyright strict | `make typecheck-strict-ratchet` | `Any`/unknown type boundary erosion under strict mode |
| Semgrep architecture | `make semgrep-architecture` | TOCTOU, retry scatter, ad-hoc HTTP status, `sys.exit`/`click.echo` misuse |

### Mutation Testing (Diff-scoped)

`make mutate-diff` runs mutmut on files changed vs the base branch. Mutation
testing asks whether tests would notice if the logic were wrong — stricter
than coverage. Scoped to changed files to keep latency acceptable at push time.

### Property Tests

Hypothesis tests verify invariants over many generated examples. Profiles
(in `tests/conftest.py`):

| Profile | Examples | Deadline | Used in |
|---------|----------|----------|---------|
| dev | 10 | none | Local development (`make test-property`) |
| push | 50 | none | Pre-push (`make test-property-push`) |
| ci | 1000 | 500ms | CI thorough lanes (`make test-property-ci`) |
| fast | 3 | none | Quick smoke |

---

## CI Gates

### Ubuntu Matrix

Runs `make ci` on `ubuntu-latest` for Python 3.12, 3.13, and 3.14.
Uses `PROPERTY_PROFILE=push` (50 examples) for 3.12 (fast feedback) and
`PROPERTY_PROFILE=ci` (1000 examples) for 3.13 and 3.14 (thorough,
used by PyPI publish). Test execution uses `pytest-xdist -n auto`.

`make ci` runs: `check`, `test-coverage`, `test-fuzz`, `safety`,
`sonar-reports`, `test-property-$(PROPERTY_PROFILE)`, `build`, `verify`,
`smoke-test`.

### macOS Full Pipeline

Runs the same `make ci` pipeline on `macos-latest` for Python 3.12 with
`PROPERTY_PROFILE=push`. Catches Darwin-specific path, filesystem, and
packaging issues.

### Build, Verify, Smoke Test

| Step | Command | Tool |
|------|---------|------|
| Build | `make build` | `uv build` |
| Verify | `make verify` | `twine check`, `scripts/verify_wheel.py` |
| Smoke test | `make smoke-test` | `scripts/smoke_test.sh` (isolated venv install) |

---

## Release Gates

### PyPI Publish

Triggered on `v*` tags only. Runs on `ubuntu-latest`, Python 3.13. Validates
that the tag, `pyproject.toml` version, and runtime `__version__` agree. Runs
the full CI pipeline, then publishes via OIDC (no long-lived token) and
creates a GitHub Release.

### Draft Release Notes

The Release Drafter workflow (`.github/workflows/release-drafter.yml`) runs on
every push to `main`/`master`/`deep-research` and on pull-request activity.
It uses `.github/release-drafter.yml` to map PR labels onto changelog
categories and maintains a running draft GitHub Release for the next tag.
It does not block merges or publish anything; it only prepares the notes
that the publish workflow later promotes when a tag is cut.

### Local Release

`make release V=0.7.2` bumps the version in `pyproject.toml`, updates the
lockfile, runs `make ci`, commits, tags, and pushes. The tag triggers the
remote publish workflow.

---

## OpenCode Integration

### Plugins (4)

All registered in `opencode.jsonc`. Installed via `make configure-opencode`.

Known caveats (current plugin code, tracked for a follow-up cleanup):

- `pxcli-quality.ts` hard-codes the Semgrep binary path to
  `/Users/jamie.mills/.local/bin/semgrep`. On any other machine it falls back
  to whatever `semgrep` resolves to on `PATH`, or no-ops if absent.
- `pre-push-docs-check.ts` references the legacy monolithic path
  `src/perplexity_cli/commands.py` in its doc-review checklist. That file no
  longer exists (commands now live under `src/perplexity_cli/commands/`),
  so the checklist item points at a path the developer will not find. The
  reminder still surfaces, but the suggested location is stale.

| Plugin | File | Intercepts | Behaviour |
|--------|------|-----------|-----------|
| quality-gate | `.opencode/plugins/quality-gate.ts` | Write/edit to scripts/ and Makefile | Blocks edits that add bypass patterns (`# nosec`, `# type: ignore`, `--exclude`), remove gate references, or drop severity levels. Post-turn flags uncommitted protected-file changes. |
| pxcli-quality | `.opencode/plugins/pxcli-quality.ts` | Session lifetime | Injects coding conventions into system prompt. After each Python file write/edit, runs ruff, radon, bandit, ty on that file. After dep changes, runs safety. On idle, runs semgrep and pyright across session-modified files. |
| pre-push-docs-check | `.opencode/plugins/pre-push-docs-check.ts` | `git push` | First push attempt blocked with doc-review checklist (CLI help text + README). Retry passes through. |
| plan-compliance-gate | `.opencode/plugins/plan-compliance-gate.ts` | `git commit` | Reads `.claude/plans/quality-plan.md`. If `Result: FAIL`, blocks commit and auto-invokes `quality-plan-reviewer` subagent via `client.tasks()`. Retry after fixes passes through. |

### Agent (1)

| Agent | File | Permissions | Behaviour |
|-------|------|-------------|-----------|
| quality-plan-reviewer | `.opencode/agents/quality-plan-reviewer.md` | Read-only (`edit: deny *`) | Runs `make plan-check`, categorises `[FAIL]` items by rule type, suggests per-category fixes. Invoked automatically by `plan-compliance-gate` or manually. |

---

## Quality Plan Pipeline

### Plan Generator

`make quality-plan` runs every analyser and writes a deterministic Markdown
plan to `.claude/plans/quality-plan.md` (override with `OUT=...`). Includes:
summary, Analyzer Compliance Review checklist, findings by analyser, proposed
work items, and self-review. A build phase must not consume the plan unless
both the compliance review and self-review report `PASS`.

### Plan Validator

`make plan-check` validates the plan's compliance review section against the
prevention rules. Every category (file-size, type boundaries, complexity,
layering, structural patterns, suppressions) must be present and marked
`[PASS]` with a consistent `Result:` line and self-review section.

### Schema-drift Guard

`tests/test_schema_drift.py` fails if a new hand-written command-result schema
dict appears. Schemas must derive from Pydantic models via `model_json_schema()`.

---

## Composite Targets Reference

All commands delegate to the Makefile to prevent local hooks, manual commands,
and CI from silently diverging.

| Target | Purpose |
|--------|---------|
| `make setup` | Create venv, sync deps, install lefthook, verify CLI |
| `make configure-opencode` | Install OpenCode npm deps, verify all plugin/agent/config files |
| `make check` | All static checks: format, lint, typecheck-all, security, complexity, semgrep, arch-check, coupling-check, ratchets |
| `make ci` | Full pipeline: check, coverage, fuzz, safety, sonar, property tests, build, verify, smoke test |
| `make test` | Unit tests without coverage (fail-fast, xdist) |
| `make test-coverage` | Unit tests with global + per-module coverage enforcement (xdist) |
| `make quality-plan` | Run all analysers, generate compliance plan |
| `make plan-check` | Validate plan against prevention rules |
| `make release V=x.y.z` | Bump version, lock, CI, commit, tag, push |

### Test Property Profiles

| Target | Profile | Examples | Use |
|--------|---------|----------|-----|
| `make test-property` | dev | 10 | Local dev |
| `make test-property-push` | push | 50 | Pre-push, CI fast lanes (3.12, macOS) |
| `make test-property-ci` | ci | 1000 | CI thorough lanes (3.13, 3.14, PyPI publish) |
| `make ci` | `$(PROPERTY_PROFILE)` | CI default | Overridden by CI matrix per Python version |

### Mutation Targets

| Target | Scope |
|--------|-------|
| `make mutate` | Full source tree (hours — for CI/overnight) |
| `make mutate-diff` | Files changed vs base branch (pre-push) |
| `make mutate-module MODULE=api` | Single module |
| `make mutate-estimate` | Time estimate for full run |
| `make mutate-results` | Show results from last run |
| `make mutate-browse` | Interactive TUI |

---

## Quick Reference — All Gates by Phase

| Gate | Phase | Tool(s) | Canonical Command |
|------|-------|---------|-------------------|
| Pyright type check | Pre-commit, CI | pyright | `make typecheck-pyright` |
| ty type check | Pre-commit, CI | ty | `make typecheck` |
| Bandit security lint | Pre-commit, CI | bandit | `make bandit` |
| Vulture dead-code | Pre-commit, CI | vulture | `make vulture` |
| Radon cyclomatic complexity | Pre-commit, CI | radon | `make complexity-cc` |
| Radon maintainability index | Pre-commit, CI | radon | `make complexity-mi` |
| Semgrep static analysis | Pre-commit, CI | semgrep | `make semgrep` |
| YAML/JSON/TOML validation | Pre-commit | pre-commit-hooks | `lefthook.yml` |
| .env file block | Pre-commit | shell | `lefthook.yml` |
| Large-file block | Pre-commit | pre-commit-hooks | `check-added-large-files --maxkb=1000` |
| Merge/case/docstring/test-name | Pre-commit | pre-commit-hooks | `lefthook.yml` |
| Infisical git-change scan | Pre-commit | infisical | `make infisical-scan` |
| Ruff format | Pre-commit, CI | ruff | `ruff format` |
| Ruff lint/fix | Pre-commit, CI | ruff | `ruff check` |
| Whitespace/EOF fixers | Pre-commit | pre-commit-hooks | `lefthook.yml` |
| Unit tests (parallel) | Pre-commit, CI | pytest, pytest-xdist | `make test` |
| Gitleaks commit-range scan | Pre-push | gitleaks | `make gitleaks` |
| Agent unified check (pre-commit linters, no tests) | Pre-push (wired via `lefthook.yml`) | `scripts/agent_check.py` | `make agent-check-no-tests` |
| Agent unified check (full pre-push set: safety, coverage, property) | On-demand (not wired into `lefthook.yml` or `make ci`) | `scripts/agent_check.py` | `make agent-check-push` |
| Coverage + per-module (parallel) | Pre-push, CI | pytest-cov, pytest-xdist | `make test-coverage` |
| Safety dependency scan | Pre-push, CI | safety | `make safety` |
| Fuzz tests | Pre-push, CI | pytest, atheris | `make test-fuzz` |
| Sonar reports | Pre-push, CI | `scripts/generate_sonar_reports.py` | `make sonar-reports` |
| Architecture check | Pre-push, CI | `scripts/check_architecture.py` | `make arch-check` |
| Coupling check | Pre-push, CI | `scripts/check_coupling.py` | `make coupling-check` |
| File-size ratchet | Pre-push, CI | `scripts/check_file_size.py` | `make file-size` |
| Suppression ratchet | Pre-push, CI | `scripts/check_suppressions.py` | `make suppression-ratchet` |
| Ruff architecture ratchet | Pre-push, CI | `scripts/check_ruff_architecture.py` | `make ruff-architecture` |
| Pyright strict ratchet | Pre-push, CI | `scripts/check_pyright_strict.py` | `make typecheck-strict-ratchet` |
| Semgrep architecture ratchet | Pre-push, CI | `scripts/check_semgrep_architecture.py` | `make semgrep-architecture` |
| Diff mutation testing | Pre-push | mutmut | `make mutate-diff` |
| Property tests | Pre-push, CI | hypothesis | `make test-property-push`, `make test-property-ci` |
| Quality plan generator | On-demand | `scripts/generate_quality_plan.py` | `make quality-plan` |
| Plan compliance check | On-demand | `scripts/check_plan_compliance.py` | `make plan-check` |
| Build, verify, smoke | CI, release | uv, twine, custom | `make build verify smoke-test` |
| Release publish | Release | GitHub Actions, OIDC | `.github/workflows/publish-to-pypi.yml` |
| Release Drafter (draft notes) | Push/PR (continuous) | release-drafter@v6 | `.github/workflows/release-drafter.yml` |
| Setup prerequisite checks | On-demand | shell | `make check-uv`, `make check-gitleaks`, `make check-infisical` |
| Architecture layer explainer | On-demand | `scripts/check_architecture.py` | `make arch-explain` |
| Format + lint auto-fix | On-demand | ruff | `make format-fix` |
| Build artefact cleanup | On-demand | shell | `make clean` |
| OpenCode quality gate | Session | `.opencode/plugins/quality-gate.ts` | `make configure-opencode` |
| OpenCode real-time quality | Session | `.opencode/plugins/pxcli-quality.ts` | `make configure-opencode` |
| OpenCode pre-push docs | Session | `.opencode/plugins/pre-push-docs-check.ts` | `make configure-opencode` |
| OpenCode plan compliance | Session | `.opencode/plugins/plan-compliance-gate.ts` + agent | `make configure-opencode` |
| Complexity trend tracking | On-demand | `scripts/track_metrics.py` | `make metrics-track` |
| OpenCode environment setup | On-demand | `make configure-opencode` | `make configure-opencode` |
