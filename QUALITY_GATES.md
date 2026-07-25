# Quality Gates and Analysers

A progressive-disclosure reference for enforced and auxiliary quality gates,
analysers, hooks, and CI checks in the repository.

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
| Pre-commit (stage 1) | Type, security, dead-code, complexity, Semgrep, OpenCode/workflow/shell/plan validation, secret scan, repo hygiene | pyright, ty, bandit, vulture, radon, semgrep, TypeScript, pytest, pre-commit-hooks, infisical |
| Pre-commit (stage 2) | Formatting, lint auto-fix, whitespace fix | ruff, pre-commit-hooks |
| Pre-commit (stage 3) | Unit tests (fail-fast, xdist) | pytest, pytest-xdist |
| Pre-push | Secret scan, coverage, dependency vulns, fuzz, architecture, coupling, ratchets, mutation, property tests | gitleaks, pytest-cov, safety, atheris, custom scripts, mutmut, hypothesis |
| CI | Universal static, audit, coverage, fuzz, property, build, verify and smoke gates; authenticated Safety for trusted code | GitHub Actions, same tools as above |
| Release | Version validation, trusted CI, OIDC publish, GitHub Release | GitHub Actions, PyPI OIDC |
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
make configure-opencode  # reproducible npm install, type-check plugins, validate config
make test                # verify everything works
```

- `make setup` creates the virtualenv, syncs locked dependencies, installs
  lefthook git hooks, and verifies the installed development CLI can show
  help. It refuses to proceed until `uv`, `gitleaks`, and `infisical` are on
  `PATH`.
- `make configure-opencode` performs `npm ci`, strictly type-checks every
  OpenCode plugin, parses `opencode.jsonc`, verifies registered plugin paths,
  and validates the resolved OpenCode config when the CLI is installed.
- Both are idempotent — safe to re-run.

### Canonical Sources of Truth

| Artifact | File(s) | Controls |
|----------|---------|----------|
| Git hooks | `lefthook.yml` | Pre-commit and pre-push job topology |
| Runnable targets | `Makefile` | All check, test, build, and setup commands |
| Python tooling | `pyproject.toml` | pytest, ruff, coverage, bandit, vulture, pyright, mutmut |
| Blocking Semgrep rules | `.semgrep.yml`, `.semgrep-community-*.yml`, `quality/semgrep-snapshot.json` | Project rules plus reviewed immutable community snapshots |
| Architecture Semgrep rules | `.semgrep-architecture.yml` | TOCTOU, retry, layering patterns |
| Gate thresholds and toggles | `quality/gates.conf` | Numeric floors and check on/off switches |
| Gate loader | `scripts/_gates.py` | Typed runtime accessor for `gates.conf` |
| Hypothesis profiles | `tests/conftest.py` | dev (10), push (50), ci (1000), fast (3) |
| Custom analysers | `scripts/` | Architecture, coupling, ratchets, plan checker, coverage, reports |
| OpenCode wiring | `opencode.jsonc` | Plugin and agent registration, permissions |
| CI workflows | `.github/workflows/*.yml` | Universal CI, trusted Safety, scheduled advisories and release automation |
| Publish workflow | `.github/workflows/publish-to-pypi.yml` | Version validation, CI, OIDC publish |
| Release Drafter workflow | `.github/workflows/release-drafter.yml` | Draft GitHub Release notes on push/PR |
| Release Drafter config | `.github/release-drafter.yml` | Label → category mapping, version resolver |

---

## Central Threshold Configuration

The file `quality/gates.conf` is the single source of truth for the
boolean check toggles and most numeric thresholds. It is locked from agent
edits by a `deny` rule in `opencode.jsonc`. Make evaluates `CHECK_*` toggles
directly; Python analysers consume applicable numeric thresholds through
`scripts/_gates.py`.

Two entries currently duplicate a value whose active source lives elsewhere
(documented here so the duplication is not "fixed" by mistake):

- `FAIL_UNDER = 85` is a reference mirror — pytest-cov reads
  `pyproject.toml` directly. This value is for documentation only.
- `SEMGREP_SEVERITY = --severity ERROR --severity WARNING` is consumed
  by the `make semgrep` target via `$(SEMGREP_SEVERITY)`.

### Quantitative Thresholds

| Key | Default | Controls |
|-----|---------|----------|
| `MAX_FLAGGED` | 10 | Coupling: maximum allowed flagged modules |
| `DISTANCE_THRESHOLD` | 0.3 | Coupling: Martin D flagging threshold |
| `MIN_COVERAGE` | 85 | Coverage: minimum per-module coverage percentage |
| `FAIL_UNDER` | 85 | Coverage: global fail_under threshold |
| `MIN_CONFIDENCE` | 80 | Vulture: minimum confidence for dead-code reporting |
| `RADON_CC_GRADE` | B | Radon: reporting threshold; grade B and worse fail, so only A passes |
| `RADON_MI_GRADE` | B | Radon: reporting threshold; grade B and worse fail, so only A passes |
| `FILE_SIZE_CAP` | 1000 | File-size ratchet: maximum source lines per file |
| `SEMGREP_SEVERITY` | ERROR WARNING | Semgrep: minimum severity levels scanned |
| `DIFF_COVERAGE_THRESHOLD` | 90 | Diff-cover: minimum coverage on changed lines |

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
| `CHECK_RATCHETS` | true | Three baseline-aware ratchets plus two whole-tree hard gates |
| `CHECK_DEPTRY` | true | Deptry dependency hygiene |
| `CHECK_IMPORT_LINTER` | false | Import-linter contracts; available but excluded from `make check` by default |

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
| Pyright | `make typecheck-pyright` | pyright | `[tool.pyright]`, strict mode, Python 3.12 |
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
| Cyclomatic complexity | `make complexity-cc` | radon | Grade A required; B and worse are reported and fail |
| Maintainability index | `make complexity-mi` | radon | Grade A required; B and worse are reported and fail |
| Trend tracking | `make metrics-track` | `scripts/track_metrics.py` | Informational — on demand |

- **CC:** rejects functions reported at grade B or worse. Complexity
  correlates with missed edge cases and testing difficulty.
- **MI:** rejects modules reported at grade B or worse.
- **Trend tracking:** diffs CC and MI across recent git revisions to surface
  gradual erosion that individual commits hide. Not blocking.

#### Semgrep Static Analysis

| Command | Config | Rules |
|---------|--------|-------|
| `make semgrep` | `.semgrep.yml` + reviewed `.semgrep-community-*.yml` snapshots | Semgrep 1.171.0; warnings and errors fail; tests excluded |
| `make semgrep-advisory` | latest p/python + p/comment + p/r2c-best-practices | Scheduled non-blocking signal for proposed snapshot updates |

- **Custom rules cover:** meaningful names, parameter counts, boolean flags,
  comment hygiene, exception handling (no silent `pass`, always `raise X from Y`),
  f-strings in logging, wildcard imports, magic numbers, `eval`/`exec` bans,
  `print()` in library code, layer import restrictions.
- **Community rules:** standard Python best practices and Clean Code patterns.
  Blocking rule contents and hashes are recorded in
  `quality/semgrep-snapshot.json`; registry changes cannot alter a PR result.

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
| OpenCode plugins/config | `make opencode-check` | TypeScript + jsonc-parser + OpenCode CLI when available |
| Make recipe syntax | `make -n safety-gate \| bash -n` | Bash |
| Shell syntax | `bash -n {staged_files}` | Bash |
| Workflow policy | targeted workflow tests | pytest |
| Quality plan | `make plan-check PLAN=.claude/plans/quality-plan.md` when present | plan-compliance analyser |

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
| Ruff lint fix | `ruff check --fix {staged_files}` | ruff | All enabled `[tool.ruff.lint]` families, subject to configured ignores |
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
| Agent unified check (read-only pre-commit linters, no tests/fixers) | `make agent-check-no-tests` | `scripts/agent_check.py --no-tests --no-fix pre-commit`; canonical Make targets only |
| Agent unified check (full pre-push set) | `make agent-check-push` | coverage + safety + fuzz + architecture + coupling + property; **not currently wired into `lefthook.yml` or `make ci`** because Lefthook already schedules those jobs directly |
| Coverage (parallel) | `make test-coverage` | pytest-cov + pytest-xdist (`-n auto`) + `scripts/check_module_coverage.py` |
| Safety dependency scan | `make safety` | safety via `scripts/agent_check.py safety` |
| Fuzz tests | `make test-fuzz` | pytest (atheris fuzz harnesses, `-m fuzz`) |
| Sonar reports | `make sonar-reports` | `scripts/generate_sonar_reports.py` |
| Architecture check | `make arch-check` | `scripts/check_architecture.py` |
| Coupling check | `make coupling-check` | `scripts/check_coupling.py` |
| Quality gates and ratchets (5) | `make ratchets` | Baseline-aware file-size, suppression and Semgrep architecture checks; whole-tree Ruff architecture and strict Pyright hard gates |
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

Checks the resolved dependency set using pinned Safety CLI 3.8.1 and the Safety
API. Requires `SAFETY_API_KEY` environment variable or Infisical to provide
it via `infisical run --env dev`. `make safety` first probes whether Infisical
can supply the key; unavailable credentials produce an informational skip.
Once authenticated scanning starts, any Safety or Infisical child failure is
propagated and blocks the push. Treat a credential skip as informational, not
a pass. `make safety-gate` is fail-closed and is used only on trusted GitHub events and
release paths. Credential-free `make pip-audit` remains blocking everywhere,
including external fork PRs. Repository secrets are never exposed through
`pull_request_target`.

### Gitleaks

Scan pushed commit ranges for secrets using Gitleaks.  When gitleaks is not
installed, `scripts/gitleaks_check.sh` prints a skip notice and exits 0,
matching the safety skip behaviour.  CI gitleaks + the infisical pre-commit
scan still catch secrets regardless of local tool availability.

### Architecture Check

`scripts/check_architecture.py` enforces ports-and-adapters layer rules:
domain, application, infrastructure, presentation. It currently executes
import-direction, adapter-independence and external-framework-isolation checks.

### Coupling Check

`scripts/check_coupling.py` computes Robert C. Martin package metrics:
afferent coupling (Ca), efferent coupling (Ce), instability (I), abstractness
(A), and distance from main sequence (D). Modules with D >= 0.3 and Ce > 0
are flagged. Applies four filters to reduce noise:

1. **Leaf-dependency filter:** Ce=1 modules whose sole dep is a Ce=0 leaf are
   not flagged.
2. **TYPE_CHECKING guard filter:** imports under `if TYPE_CHECKING:` are excluded.
3. **Function-body filter:** lazy imports inside function bodies are excluded.
4. **Sibling-dependency heuristic:** dotted modules whose dependencies all share
   their package prefix are treated as re-export-style infrastructure and excluded.

### Quality Gates and Ratchets

`make ratchets` is a historical composite name containing three baseline-aware
ratchets and two whole-tree hard gates. Only the baseline-aware checks write
JSON under `quality/baselines/`; refresh those baselines only after an
intentional review.

| Gate | Target | Enforcement |
|------|--------|-------------|
| File-size | `make file-size` | Baseline-aware: blocks new or grown files over `FILE_SIZE_CAP` |
| Suppressions | `make suppression-ratchet` | Baseline-aware: blocks new/grown `# noqa`, `# nosec`, `# nosemgrep`, `# type: ignore`, and `# pyright: ignore` counts |
| Ruff architecture | `make ruff-architecture` | Hard gate over all `src/`: `C901`, `PLR0913`, `PLR2004`, `ARG001`, `ARG002` |
| Pyright strict | `make typecheck-strict-ratchet` | Hard gate over all `src/`; same strict Pyright configuration as `make typecheck-pyright` |
| Semgrep architecture | `make semgrep-architecture` | Baseline-aware: blocks new structural findings and fails closed on analyser errors |

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

### Universal Ubuntu Matrix

Triggered for pushes to `master`, all pull requests, and manual dispatch. Runs
`make ci` on `ubuntu-latest` for Python 3.12, 3.13, and 3.14.
Uses `PROPERTY_PROFILE=push` (50 examples) for 3.12 (fast feedback) and
`PROPERTY_PROFILE=ci` (1000 examples) for 3.13 and 3.14 (thorough,
used by PyPI publish). Test execution uses `pytest-xdist -n auto`.

`make ci` runs: `check` (including enabled Deptry), `test-coverage`, `test-fuzz`, `pip-audit`,
`sonar-reports`, `test-property-$(PROPERTY_PROFILE)`, `build`, `verify`,
`smoke-test`.

This credential-free pipeline is required for every PR, including external
forks. A separate `Safety (trusted)` job runs `make safety-gate` for pushes,
same-repository PRs and Dependabot PRs. External forks skip that job because
GitHub correctly withholds repository and Dependabot secrets. A dedicated
OpenCode job performs the reproducible plugin/config checks.

### macOS Full Pipeline

Runs the same `make ci` pipeline on `macos-latest` for Python 3.12 with
`PROPERTY_PROFILE=push`. Catches Darwin-specific path, filesystem, and
packaging issues.

### Scheduled Advisory Workflows

- `mutation-scheduled.yml` runs full mutation testing weekly and always reports results.
- `scorecard.yml` runs OpenSSF Scorecard weekly and uploads SARIF with least permissions.
- `semgrep-advisory.yml` scans the latest community packs weekly without changing or blocking the reviewed rule snapshot.
- All three can also be started manually with `workflow_dispatch`.
- Every external action reference is pinned to a full 40-character commit SHA.

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
`make ci-trusted`, then publishes via OIDC (no long-lived token) and
creates a GitHub Release.

### Draft Release Notes

The Release Drafter workflow (`.github/workflows/release-drafter.yml`) runs on
pushes to `main`/`master` and meaningful pull-request lifecycle activity.
It uses `.github/release-drafter.yml` to map PR labels onto changelog
categories and maintains a running draft GitHub Release for the next tag.
Label-only events do not rerun it.
It does not block merges or publish anything; it only prepares the notes
that the publish workflow later promotes when a tag is cut.

### Local Release

`make release V=0.7.2` bumps the version in `pyproject.toml`, updates the
lockfile, runs `make ci-trusted`, commits, tags, and pushes. The tag triggers the
remote publish workflow.

---

## OpenCode Integration

### Plugins (4)

All registered in `opencode.jsonc`. Installed via `make configure-opencode`.

Plugin dependencies and TypeScript/JSONC checks are reproducible through the
tracked `.opencode/package-lock.json` and `make opencode-check`. Restart
OpenCode after changing plugin, agent, or configuration files.

| Plugin | File | Intercepts | Behaviour |
|--------|------|-----------|-----------|
| quality-gate | `.opencode/plugins/quality-gate.ts` | write/edit/apply_patch to scripts/ and Makefile | Uses the supported before-hook arguments, blocks added bypasses and removal of its enumerated threshold/gate references, honours `OPENCODE_DISABLE_QUALITY_GATE=1`, and verifies coupling only after protected changes. It is not a general semantic proof that every Make target remains wired. |
| pxcli-quality | `.opencode/plugins/pxcli-quality.ts` | Session lifetime | Injects conventions; runs file-level ruff/radon/bandit/ty after `write` and `edit`, pinned Safety after dependency changes, and canonical immutable Semgrep plus pyright on idle for files recorded by those tools. `apply_patch` changes rely on Lefthook/Make because this reactive plugin does not record them. Tool and parser failures become visible error findings. |
| pre-push-docs-check | `.opencode/plugins/pre-push-docs-check.ts` | `git push` | First push attempt blocked with doc-review checklist (CLI help text + README). Retry passes through. |
| plan-compliance-gate | `.opencode/plugins/plan-compliance-gate.ts` | `git commit` | When `.claude/plans/quality-plan.md` exists, runs the canonical exact-path `make plan-check` on every detected commit attempt and blocks while it fails. With no canonical plan, it allows the commit. The reviewer is invoked manually; no unsupported SDK call or unchecked retry exists. |

### Agent (1)

| Agent | File | Permissions | Behaviour |
|-------|------|-------------|-----------|
| quality-plan-reviewer | `.opencode/agents/quality-plan-reviewer.md` | Read-only; Bash allows only exact-path `make plan-check` | Categorises failures and suggests fixes without editing files or updating baselines. Invoke manually when the commit gate blocks. |

---

## Quality Plan Pipeline

### Plan Generator

`make quality-plan` runs the canonical 20-gate planning set and writes a
deterministic Markdown plan to `.claude/plans/quality-plan.md` (override with
`OUT=...`). The set covers formatting, lint, both type checkers, Bandit,
Vulture, both Radon gates, blocking Semgrep, architecture, coupling, the five
quality gates/ratchets, Deptry, pip-audit, and global/per-module coverage. It
does not represent every auxiliary, hook-only, release, mutation, property,
fuzz, Safety, secret-scanning, OpenCode or reporting command. Includes:
summary, Analyser Compliance Review checklist, findings by analyser, proposed
work items, and self-review. A build phase must not consume the plan unless
both the compliance review and self-review report `PASS`.

### Plan Validator

`make plan-check` validates every exact named gate, not merely broad
categories. Every gate must appear exactly once as `[PASS]`; `[FAIL]`,
`[SKIP]`, duplicates, a failing summary, or a missing/failing self-review
rejects the plan. `make quality-plan` writes its report and exits non-zero on
any analyser or self-review failure.

### Schema-drift Guard

`tests/test_schema_drift.py` fails if a new hand-written command-result schema
dict appears. Schemas must derive from Pydantic models via `model_json_schema()`.

---

## Composite Targets Reference

Canonical whole-project checks delegate to the Makefile. Staged-file fixers,
pre-commit-hooks and a small number of workflow-specific validations remain
inline where they need Git or event context.

| Target | Purpose |
|--------|---------|
| `make setup` | Create venv, sync deps, install lefthook, verify CLI |
| `make configure-opencode` | Reproducibly install and validate OpenCode plugins/config |
| `make check` | Enabled static checks: format, lint, typecheck-all, security, complexity, semgrep, arch-check, coupling-check, ratchets, Deptry; import-linter only when toggled on |
| `make ci` | Universal credential-free pipeline: check, coverage, fuzz, pip-audit, sonar, property, build, verify, smoke |
| `make ci-trusted` | Universal CI plus fail-closed authenticated Safety |
| `make test` | Unit tests without coverage (fail-fast, xdist) |
| `make test-coverage` | Unit tests with global + per-module coverage enforcement (xdist) |
| `make quality-plan` | Run the canonical 20-gate planning set, generate compliance plan |
| `make plan-check` | Validate plan against prevention rules |
| `make release V=x.y.z` | Bump version, lock, CI, commit, tag, push |
| `make diff-coverage` | Require `DIFF_COVERAGE_THRESHOLD` coverage on changed lines after generating `coverage.xml` |
| `make dependency-hygiene` | Run the Deptry dependency-hygiene alias |
| `make import-linter` | Run import contracts; disabled in `make check` by default |
| `make refurb` | Run advisory Refurb readability checks |
| `make quality-architecture` | Run import-linter, architecture and coupling checks together |

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
| Gitleaks commit-range scan | Pre-push (graceful skip when not installed) | gitleaks | `make gitleaks` |
| Agent unified check (pre-commit linters, no tests) | Pre-push (wired via `lefthook.yml`) | `scripts/agent_check.py` | `make agent-check-no-tests` |
| Agent unified check (coverage, safety, fuzz, architecture, coupling, property) | On-demand (not wired into `lefthook.yml` or `make ci`) | `scripts/agent_check.py` | `make agent-check-push` |
| Coverage + per-module (parallel) | Pre-push, CI | pytest-cov, pytest-xdist | `make test-coverage` |
| Safety dependency scan | Pre-push (optional credentials), trusted CI/release (required) | safety | `make safety`, `make safety-gate` |
| Credential-free dependency audit | All CI and PR contexts | pip-audit | `make pip-audit` |
| Dependency declaration hygiene | CI, quality plan, on-demand | deptry | `make deptry` |
| Fuzz tests | Pre-push, CI | pytest, atheris | `make test-fuzz` |
| Sonar reports | Pre-push, CI | `scripts/generate_sonar_reports.py` | `make sonar-reports` |
| Architecture check | Pre-push, CI | `scripts/check_architecture.py` | `make arch-check` |
| Coupling check | Pre-push, CI | `scripts/check_coupling.py` | `make coupling-check` |
| File-size ratchet | Pre-push, CI | `scripts/check_file_size.py` | `make file-size` |
| Suppression ratchet | Pre-push, CI | `scripts/check_suppressions.py` | `make suppression-ratchet` |
| Ruff architecture hard gate | Pre-push, CI | Ruff whole-tree selectors | `make ruff-architecture` |
| Pyright strict hard gate | Pre-push, CI | pyright strict whole-tree check | `make typecheck-strict-ratchet` |
| Semgrep architecture ratchet | Pre-push, CI | `scripts/check_semgrep_architecture.py` | `make semgrep-architecture` |
| Diff mutation testing | Pre-push | mutmut | `make mutate-diff` |
| Property tests | Pre-push, CI | hypothesis | `make test-property-push`, `make test-property-ci` |
| Quality plan generator | On-demand | `scripts/generate_quality_plan.py` | `make quality-plan` |
| Plan compliance check | On-demand | `scripts/check_plan_compliance.py` | `make plan-check` |
| Build, verify, smoke | CI, release | uv, twine, custom | `make build verify smoke-test` |
| Release publish | Release | GitHub Actions, OIDC | `.github/workflows/publish-to-pypi.yml` |
| Release Drafter (draft notes) | Push/PR lifecycle | release-drafter v7.6.0 pinned by SHA | `.github/workflows/release-drafter.yml` |
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
| Diff coverage | On-demand | diff-cover | `make diff-coverage` |
| Dependency hygiene alias | On-demand, CI through Deptry | deptry | `make dependency-hygiene` |
| Import contracts | On-demand; disabled in `make check` by default | import-linter | `make import-linter` |
| Refurb readability | On-demand advisory | refurb | `make refurb` |
| Composite architecture checks | On-demand | import-linter + custom architecture/coupling | `make quality-architecture` |
