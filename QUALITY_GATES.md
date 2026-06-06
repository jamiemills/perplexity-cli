# Quality Gates, Analysers, Checkers, and Hooks

This document explains the repository's local and CI quality gates: what is
analysed, which tool performs the analysis, what the gate protects against,
what value it provides, and why it runs at its current point in the workflow.

## How to Read This Document

This is a description of the gates currently configured in the repository, not
a wish list. The canonical sources of truth are `lefthook.yml` for local Git
hook placement, `Makefile` for runnable targets, `pyproject.toml` for Python
tool configuration, `.semgrep.yml` for custom Semgrep rules, `tests/conftest.py`
for Hypothesis profiles, `scripts/` for custom checks, and `.github/workflows/`
for CI and publishing. When a gate changes, update the command in the canonical
config first, then update this document. This document does not describe GitHub
branch protection settings, PyPI project settings, local IDE checks, operating
system keychain policy, or any external scanner that is not visible in this
repository.

## Big Picture

The repository uses a layered defence model. Cheap and deterministic checks run
before a commit is created. More expensive whole-project checks run before code
is pushed. CI repeats the important checks in a clean environment and adds build
and packaging validation. The release workflow then proves that the tag, source
metadata, runtime package, and distributable artefacts all agree before upload.

```text
edit code
  |
  v
pre-commit, stage 1: read-only analysers and validators
  |
  v
pre-commit, stage 2: staged-file auto-fixers
  |
  v
pre-commit, stage 3: fail-fast unit tests without coverage
  |
  v
pre-push: expensive whole-project checks in parallel
  |
  v
CI: clean Ubuntu and macOS verification
  |
  v
release: tag/version validation, CI, publish, GitHub Release
```

The ordering matters:

- **Pre-commit stage 1** is read-only and parallel. It finds semantic, security,
  type, syntax, and repository-hygiene failures before any formatter modifies
  files. This gives fast feedback on issues that cannot be auto-fixed.
- **Pre-commit stage 2** is mutating and sequential. It formats and fixes staged
  files, then re-stages them. Sequential execution avoids file races between
  formatters and whitespace fixers.
- **Pre-commit stage 3** runs the safe unit suite without coverage. It is later
  than static checks because tests are slower, and it omits coverage because
  coverage is a quality threshold for a push, not for every individual commit.
- **Pre-push** runs expensive checks that need whole-project context or are too
  slow/noisy for every commit: coverage, dependency vulnerabilities, fuzzing,
  property tests, mutation testing, secret scanning over commit ranges, and
  architecture/coupling checks.
- **CI** repeats the pipeline from a clean checkout and clean dependency sync.
  It defends against machine-specific success and validates supported Python and
  operating-system combinations.
- **Release** adds version consistency and packaging publication checks. It is
  the last barrier before irreversible external distribution.

## Quick Reference

| Gate | Phase | Tool | Canonical command/config |
|---|---|---|---|
| Pyright type check | Pre-commit, CI | `pyright` | `make typecheck-pyright`, `[tool.pyright]` |
| ty type check | Pre-commit, CI | `ty` | `make typecheck` |
| Bandit security lint | Pre-commit, CI | `bandit` | `make bandit`, `[tool.bandit]` |
| Vulture dead-code scan | Pre-commit, CI | `vulture` | `make vulture`, `[tool.vulture]` |
| Radon cyclomatic complexity | Pre-commit, CI | `radon` | `make complexity-cc` |
| Radon maintainability index | Pre-commit, CI | `radon` | `make complexity-mi` |
| Semgrep static analysis | Pre-commit, CI | `semgrep` | `make semgrep`, `.semgrep.yml` |
| YAML/JSON/TOML validation | Pre-commit | `pre-commit-hooks` | `lefthook.yml` |
| `.env` file block | Pre-commit | shell/Git | `lefthook.yml` |
| Large-file block | Pre-commit | `pre-commit-hooks` | `check-added-large-files --maxkb=1000` |
| Merge/case/docstring/test-name checks | Pre-commit | `pre-commit-hooks` | `lefthook.yml` |
| Infisical git-change scan | Pre-commit | `infisical` | `make infisical-scan` |
| Ruff format | Pre-commit, CI | `ruff` | `ruff format`, `[tool.ruff]` |
| Ruff lint/fix | Pre-commit, CI | `ruff` | `ruff check`, `[tool.ruff.lint]` |
| Whitespace and EOF fixers | Pre-commit | `pre-commit-hooks` | `lefthook.yml` |
| Unit tests | Pre-commit, CI | `pytest` | `make test`, `[tool.pytest.ini_options]` |
| Gitleaks commit-range scan | Pre-push | `gitleaks` | `make gitleaks`, `scripts/gitleaks_check.sh` |
| Agent unified check | Pre-push | custom Python | `make agent-check-no-tests` |
| Coverage and per-module coverage | Pre-push, CI | `pytest-cov`, custom Python | `make test-coverage` |
| Safety dependency scan | Pre-push, CI | `safety` via custom runner | `make safety` |
| Fuzz tests | Pre-push, CI | `pytest`, `atheris` harnesses | `make test-fuzz` |
| Sonar reports | Pre-push, CI | Bandit JSON via custom script | `make sonar-reports` |
| Architecture check | Pre-push, CI | custom AST analyser | `make arch-check` |
| Coupling check | Pre-push, CI | custom AST analyser | `make coupling-check` |
| Diff mutation testing | Pre-push | `mutmut`, custom discovery | `make mutate-diff` |
| Property tests | Pre-push, CI | `hypothesis` | `make test-property-push`, `make test-property-ci` |
| Build, verify, smoke test | CI, release | `uv`, `twine`, custom scripts | `make build verify smoke-test` |
| Version/tag validation and publish | Release | GitHub Actions, PyPI OIDC | `.github/workflows/publish-to-pypi.yml` |

## Exact Local Hook Topology

The local hook topology is intentionally explicit. The hook names below are the
names shown by Lefthook, while most commands delegate to Make targets so that CI
and local development do not drift.

| Lefthook phase | Job name | Command | Placement reason |
|---|---|---|---|
| Pre-commit stage 1 | `pyright-check` | `make typecheck-pyright` | Read-only type failure; cheap enough to block immediately. |
| Pre-commit stage 1 | `ty-check` | `make typecheck` | Independent type pass next to Pyright for fast semantic feedback. |
| Pre-commit stage 1 | `bandit` | `make bandit` | Source security issues should fail before formatting or tests. |
| Pre-commit stage 1 | `vulture` | `make vulture` | Dead additions should be rejected while the commit is being formed. |
| Pre-commit stage 1 | `radon-cc` | `make complexity-cc` | Branching complexity is a design issue, not a test issue. |
| Pre-commit stage 1 | `radon-mi` | `make complexity-mi` | Module maintainability should fail before accepting more code. |
| Pre-commit stage 1 | `semgrep` | `make semgrep` | Project-specific code smells need author judgement before auto-fixes. |
| Pre-commit stage 1 | `check-yaml` | `check-yaml {staged_files}` | Config syntax is cheap and staged-file scoped. |
| Pre-commit stage 1 | `check-json` | `check-json {staged_files}` | JSON syntax errors should never reach history. |
| Pre-commit stage 1 | `check-toml` | `check-toml {staged_files}` | Package/tool config syntax must be valid before commit. |
| Pre-commit stage 1 | `check-env-files` | inline Git diff script | Newly added `.env` files are usually secret-bearing and must stop immediately. |
| Pre-commit stage 1 | `check-added-large-files` | `check-added-large-files --maxkb=1000` | Large artefacts are repository-history problems, not CI problems. |
| Pre-commit stage 1 | `check-merge-conflict` | `check-merge-conflict {staged_files}` | Conflict markers are always accidental and cheap to detect. |
| Pre-commit stage 1 | `check-case-conflict` | `check-case-conflict {staged_files}` | Case collisions break contributors on case-insensitive filesystems. |
| Pre-commit stage 1 | `check-docstring-first` | `check-docstring-first {staged_files}` | Module docstring structure is a staged-file hygiene rule. |
| Pre-commit stage 1 | `name-tests-test` | `name-tests-test --pytest-test-first {staged_files}` | Test discovery naming should be fixed before test files enter history. |
| Pre-commit stage 1 | `infisical-scan` | `make infisical-scan` | Secret-looking current changes should be blocked before commit creation. |
| Pre-commit stage 2 | `ruff-format` | `ruff format {staged_files}` | Mutates staged Python, so it runs sequentially and re-stages output. |
| Pre-commit stage 2 | `ruff-check` | `ruff check --fix {staged_files}` | Mutating lint fixes must run after formatting and before tests. |
| Pre-commit stage 2 | `trailing-whitespace` | `trailing-whitespace-fixer {staged_files}` | Text clean-up is automatic and should not consume review attention. |
| Pre-commit stage 2 | `end-of-file-fixer` | `end-of-file-fixer {staged_files}` | Final-newline repair is automatic staged-file hygiene. |
| Pre-commit stage 3 | `pytest-check` | `make test` | Behavioural proof runs only after static and formatter gates pass. |
| Pre-push | `gitleaks-detect` | `make gitleaks` | Commit-range secret scanning belongs at the boundary to the remote. |
| Pre-push | `agent-check` | `make agent-check-no-tests` | Consolidated static report is useful at branch-push granularity. |
| Pre-push | `pytest-coverage` | `make test-coverage` | Coverage is a branch quality threshold, not a per-commit formatting concern. |
| Pre-push | `safety-scan` | `make safety` | Dependency vulnerability checks may need credentials and full environment context. |
| Pre-push | `fuzz-check` | `make test-fuzz` | CPU-heavy generated-input checks are valuable before sharing a branch. |
| Pre-push | `generate-sonar-reports` | `make sonar-reports` | Machine-readable reports are meaningful for branch/CI artefacts. |
| Pre-push | `arch-check` | `make arch-check` | Layer drift is a whole-source structural concern. |
| Pre-push | `coupling-check` | `make coupling-check` | Import-graph health needs whole-project context. |
| Pre-push | `mutate-diff` | `make mutate-diff` | Mutation testing is expensive, so it is scoped to branch changes. |
| Pre-push | `test-property` | `make test-property-push` | The push profile balances generated-example depth with local latency. |

## Pre-commit Stage 1: Read-only Analysers and Validators

Stage 1 is configured as a parallel group in `lefthook.yml`. These checks do not
modify files. They exist to reject commits that are structurally unsafe, invalid,
or inconsistent before any formatter runs.

### Pyright Type Check

**Summary:** Pyright analyses `src/` in Python 3.12 standard type-checking mode.
It protects the project from type-contract drift in public functions, internal
service boundaries, and model objects.

- **Tool used:** `pyright`, invoked by `make typecheck-pyright` as
  `uv run pyright src/`.
- **What is analysed:** Python source under `src/`, using `[tool.pyright]` with
  `include = ["src/"]`, `pythonVersion = "3.12"`, and
  `typeCheckingMode = "standard"`.
- **What it defends against:** calling functions with impossible argument types,
  dereferencing optional values without proving they exist, returning values that
  violate annotations, stale imports, incompatible overrides, and drift between
  declared interfaces and implementation.
- **Why analyse this:** this CLI has several API boundaries: Click command
  inputs, JSON envelopes, authentication storage, HTTP clients, MCP server
  shapes, and thread-export data. Type drift in any of those areas often appears
  first as a runtime bug in a rarely used command path.
- **Value provided:** catches whole classes of bugs without running the CLI,
  documents assumptions in function signatures, and makes refactors safer.
- **Why here:** it is read-only and quick enough for pre-commit. Running it
  before formatters means semantic errors fail immediately and are not hidden by
  a later auto-fix pass.

### ty Type Check

**Summary:** `ty` provides a second type-analysis engine over `src/`. It is used
as an independent opinion alongside Pyright.

- **Tool used:** `ty`, invoked by `make typecheck` as `uv run ty check src`.
- **What is analysed:** Python source under `src/`.
- **What it defends against:** type inconsistencies that one type engine may
  miss or choose not to report, especially while `ty` and Pyright evolve with
  different inference strategies.
- **Why analyse this:** relying on one type checker makes the codebase inherit
  that tool's blind spots. A second analyser increases confidence in interfaces
  that are consumed by CLI, MCP, tests, and packaging entry points.
- **Value provided:** redundancy without large configuration cost. It makes type
  feedback less dependent on a single implementation's interpretation.
- **Why here:** it is read-only and paired with Pyright in the fastest stage, so
  type regressions block commits before later gates spend time running tests.

### Bandit Security Lint

**Summary:** Bandit scans Python ASTs for security-sensitive coding patterns.
The repository runs it on production source and does not globally skip rules.

- **Tool used:** `bandit`, invoked by `make bandit` as
  `uvx --from bandit bandit -c pyproject.toml -r src/ -ll -ii`.
- **What is analysed:** recursive Python source under `src/`; `tests/` are
  excluded in `[tool.bandit]`.
- **What it defends against:** common Python security hazards such as unsafe
  subprocess use, weak randomness, insecure temporary files, hardcoded secrets,
  risky deserialisation, suspicious networking/TLS choices, and other Bandit AST
  patterns.
- **Why analyse this:** the CLI handles tokens, browser cookies, local config,
  network calls, attachments, and thread cache data. Security mistakes in those
  paths can expose session material or weaken local credential handling.
- **Value provided:** automated review of high-risk idioms before code leaves a
  developer machine. Targeted `# nosec BXXX` comments must carry justification
  instead of globally muting checks.
- **Why here:** security lint is cheap, deterministic, and read-only. Early
  placement prevents obvious security mistakes from being normalised in commits.

### Vulture Dead-code Detection

**Summary:** Vulture identifies likely unused Python code with a confidence
threshold of 80 and a whitelist for intentional dynamic references.

- **Tool used:** `vulture`, invoked by `make vulture` as
  `uv run vulture src/ vulture_whitelist.py --min-confidence 80`.
- **What is analysed:** production source in `src/` plus `vulture_whitelist.py`;
  configuration in `[tool.vulture]` sets `paths = ["src/"]` and
  `min_confidence = 80`.
- **What it defends against:** obsolete functions, unreachable classes, stale
  constants, forgotten command paths, and dead compatibility branches.
- **Why analyse this:** dead code increases the review surface and can preserve
  old security assumptions, old API shapes, or unused abstractions that mislead
  future contributors.
- **Value provided:** keeps the source tree smaller and makes architectural
  signals cleaner. A reviewer can trust that public-looking code is likely still
  connected to behaviour.
- **Why here:** dead-code checks are static and fast enough to run per commit;
  catching unused additions immediately is cheaper than deleting them later.

### Radon Cyclomatic Complexity

**Summary:** Radon rejects functions whose cyclomatic complexity reaches grade B
or worse according to the configured command.

- **Tool used:** `radon`, invoked by `make complexity-cc` as
  `uv run radon cc src/ -s -n B` with failure when output exists.
- **What is analysed:** source files under `src/`, with scores printed by
  function/method.
- **What it defends against:** branching-heavy functions, deeply nested command
  handling, multi-responsibility control flow, and paths that become difficult
  to test exhaustively.
- **Why analyse this:** a CLI with auth, streaming, JSON envelopes, attachment
  handling, and error mapping can easily concentrate too many branches in one
  function. Complexity correlates with missed edge cases.
- **Value provided:** pressures code toward small helpers, clearer boundaries,
  and lower testing burden.
- **Why here:** complexity is a design smell best caught while the change is
  still small. Pre-commit is the right point because the author can simplify the
  function before dependent tests and documentation accumulate around it.

### Radon Maintainability Index

**Summary:** Radon also checks maintainability index and rejects modules at grade
B or worse according to the Makefile target.

- **Tool used:** `radon`, invoked by `make complexity-mi` as
  `uv run radon mi src/ -s -n B`.
- **What is analysed:** source files under `src/`; MI combines signals such as
  volume and complexity into a maintainability score.
- **What it defends against:** files that become large, dense, or difficult to
  reason about even if no single function trips another check.
- **Why analyse this:** maintainability is a cumulative property. A file can pass
  lint and types while still becoming too hard to safely change.
- **Value provided:** gives an early warning before modules become expensive to
  review, test, and refactor.
- **Why here:** MI is static and quick; it belongs next to cyclomatic complexity
  as a pre-commit design-health guard.

### Semgrep Static Analysis

**Summary:** Semgrep applies a custom Clean Code ruleset plus community Python,
comment, and best-practice rules with warnings and errors treated as failures.

- **Tool used:** `semgrep`, invoked by `make semgrep` with `.semgrep.yml`,
  `p/python`, `p/comment`, `p/r2c-best-practices`, `--severity ERROR`,
  `--severity WARNING`, `--exclude tests/`, `--error`, and `--metrics=off`.
- **What is analysed:** repository Python and supported text patterns, excluding
  tests for the Makefile target. The custom rules cover meaningful names,
  parameter counts, boolean flags, comment hygiene, exception handling, logging,
  wildcard imports, magic numbers, equality style, `eval`/`exec`, dynamic
  attribute access, and architecture import restrictions.
- **What it defends against:** code smells that are too project-specific for
  Ruff alone: vague names, silent exception swallowing, broad `Exception`
  catches, losing tracebacks by raising without `from`, f-strings in logging,
  `print()` in library code, wildcard imports, and domain/application layer
  framework leaks.
- **Why analyse this:** static style rules encode review standards in a way that
  scales. They stop repeated review comments from becoming manual labour.
- **Value provided:** protects readability, observability, exception semantics,
  and architecture intent. It also makes the repository's conventions executable
  rather than tribal knowledge.
- **Why here:** Semgrep is read-only and runs before auto-fixers because most of
  its findings require a design choice, not formatting.

### YAML, JSON, and TOML Validation

**Summary:** These validators reject malformed configuration files before they
break hooks, package metadata, workflows, or runtime config.

- **Tool used:** `pre-commit-hooks` commands `check-yaml`, `check-json`, and
  `check-toml`, invoked through `uvx --from pre-commit-hooks` on staged files.
- **What is analysed:** staged `*.yml`, `*.yaml`, `*.json`, and `*.toml` files.
- **What it defends against:** syntax errors in `lefthook.yml`, workflow YAML,
  package metadata, JSON resources, and configuration files.
- **Why analyse this:** malformed config often fails far away from the edit that
  introduced it: in CI parsing, packaging, local setup, or runtime config load.
- **Value provided:** immediate feedback on structural validity and less time
  spent debugging parser errors in unrelated contexts.
- **Why here:** these checks are cheap and scoped to staged files, so they are
  ideal for pre-commit.

### Repository Hygiene Checks

**Summary:** Several small pre-commit hooks prevent common Git and filesystem
hazards from entering history.

- **Tool used:** inline shell plus `pre-commit-hooks`: `check-added-large-files`,
  `check-merge-conflict`, `check-case-conflict`, `check-docstring-first`, and
  `name-tests-test --pytest-test-first`.
- **What is analysed:** staged paths and staged file contents. `.env` additions
  are blocked with `git diff --cached --name-only --diff-filter=A`; large files
  are blocked above 1000 KB; merge markers and case conflicts are detected;
  Python module docstring placement and test filename conventions are checked.
- **What it defends against:** committed local secrets in `.env`, accidental
  binary/large artefacts, unresolved merge conflicts, filenames that collide on
  case-insensitive filesystems, misplaced module docstrings, and tests that are
  not discovered because of naming drift.
- **Why analyse this:** these are high-signal mistakes that do not require deep
  project context. They are easiest to fix before the commit exists.
- **Value provided:** cleaner history, fewer CI surprises, cross-platform safety,
  and more reliable test discovery.
- **Why here:** the checks depend on staged-file state and are nearly free, so
  they belong in pre-commit rather than CI.

### Infisical Secret Scan

**Summary:** Infisical scans uncommitted Git changes for secrets before the
commit is created.

- **Tool used:** `infisical`, invoked by `make infisical-scan` as
  `infisical scan git-changes --verbose --exit-code 1`.
- **What is analysed:** uncommitted Git changes.
- **What it defends against:** accidentally staged tokens, API keys, cookies,
  credentials, and other secret-looking material.
- **Why analyse this:** once a secret is committed, remediation requires history
  cleanup and credential rotation. Preventing the commit is much cheaper.
- **Value provided:** first-line secret defence close to the author's edit.
- **Why here:** it scans working changes rather than pushed commit ranges, so it
  is correctly placed before the commit. Gitleaks later re-checks commit history
  before push.

## Pre-commit Stage 2: Auto-fixers

Stage 2 is a piped group because these jobs modify files and re-stage the result.
Only one mutating tool should touch a staged file at a time.

### Ruff Format

**Summary:** Ruff format normalises Python layout to the repository's configured
target version and line length.

- **Tool used:** `ruff format`, configured by `[tool.ruff]` with
  `target-version = "py312"` and `line-length = 100`.
- **What is analysed and changed:** staged Python files in pre-commit, and
  `src tests` in `make format-check`/`make format-fix`.
- **What it defends against:** churn from personal formatting preferences,
  inconsistent wrapping, noisy reviews, and formatting-only disputes.
- **Why analyse this:** formatting is not behaviour, but inconsistent formatting
  makes behaviour changes harder to review.
- **Value provided:** stable diffs and predictable style without human debate.
- **Why here:** it mutates files, so it runs after read-only blockers and before
  tests. `stage_fixed: true` ensures the commit contains the formatter output.

### Ruff Lint and Fix

**Summary:** Ruff enforces a broad lint profile and can auto-fix safe issues in
staged files.

- **Tool used:** `ruff check --fix` in pre-commit, `ruff check src tests` in the
  `lint` target, configured by `[tool.ruff.lint]`.
- **What is analysed:** Python source and tests. Rules include pycodestyle,
  Pyflakes, isort imports, flake8-comprehensions, flake8-bugbear, pyupgrade,
  Google-style pydocstyle, `S101` assert checks for production code, debugger
  statements, and Ruff-specific rules.
- **What it defends against:** unused imports, undefined names, import disorder,
  outdated syntax, suspicious bug-prone patterns, missing docstrings outside
  ignored areas, debugger leftovers, production `assert`, and mutable class
  attribute issues.
- **Why analyse this:** Ruff catches many defects that are either runtime errors
  waiting to happen or style inconsistencies that increase review cost.
- **Value provided:** combines formatter, import organiser, bugbear-style lint,
  pyupgrade, and docstyle checks in one fast tool.
- **Why here:** many findings are auto-fixable, so the pre-commit hook repairs
  staged files before tests run. CI later runs non-mutating checks to prove the
  committed tree is clean.

### Whitespace and End-of-file Fixers

**Summary:** These fixers remove trailing whitespace and ensure final newlines.

- **Tool used:** `trailing-whitespace-fixer` and `end-of-file-fixer` from
  `pre-commit-hooks`.
- **What is analysed and changed:** staged files across the repository.
- **What it defends against:** meaningless diff noise, editor-dependent file
  endings, and tools that expect POSIX-style final newlines.
- **Why analyse this:** whitespace errors create review noise and merge churn but
  do not require human judgement.
- **Value provided:** cleaner diffs and consistent text-file hygiene.
- **Why here:** these are staged-file mutations, so they run in the sequential
  fixer stage and re-stage their changes.

## Pre-commit Stage 3: Unit Tests Without Coverage

### pytest Fail-fast Safe Suite

**Summary:** The pre-commit test gate runs the default safe test suite, fail-fast,
without coverage enforcement.

- **Tool used:** `pytest`, invoked by `make test` as
  `uv run pytest tests/ -q --tb=line -x`.
- **What is analysed:** tests under `tests/`, with default marker exclusions from
  `[tool.pytest.ini_options]`: integration, real API, manual, real user config,
  and fuzz tests are excluded by default.
- **What it defends against:** direct behavioural regressions in hermetic unit
  tests, broken CLI envelopes, command behaviour changes, config isolation
  leaks, and failures in safe local execution paths.
- **Why analyse this:** static checks cannot prove behaviour. The unit suite
  exercises the intended contracts.
- **Value provided:** fast behavioural confidence before a commit is accepted.
- **Why here:** tests are slower than static checks and should only run after
  formatting/lint/type/security gates pass. Coverage is deferred to pre-push to
  avoid making every small commit pay for threshold reporting.

## Pre-push: Expensive Whole-project Gates

Pre-push runs in parallel because these checks do not mutate files and are more
expensive. They validate a branch before it leaves the developer's machine.

### Gitleaks Commit-range Secret Detection

**Summary:** Gitleaks scans the commits being pushed, not just current staged
changes.

- **Tool used:** `gitleaks`, invoked by `make gitleaks` through
  `scripts/gitleaks_check.sh`.
- **What is analysed:** the range from the remote tracking branch to `HEAD`, or
  a suitable base branch for new branches; findings are redacted.
- **What it defends against:** secrets that were committed earlier in the branch,
  amended into history, or not present in the current working tree.
- **Why analyse this:** a pre-commit secret scan can miss history already present
  on the branch. Push is the last local moment to stop those commits from
  reaching the remote.
- **Value provided:** second-line secret defence at the history boundary.
- **Why here:** Gitleaks works on commit history, so pre-push is more valuable
  than pre-commit for this gate.

### Agent Unified Check

**Summary:** `agent_check.py` provides a unified static-analysis runner for
agent and pre-push use, excluding tests in the pre-push hook.

- **Tool used:** custom Python script, invoked as
  `uv run python scripts/agent_check.py --no-tests pre-commit`.
- **What is analysed:** the configured pre-commit analyser set, with test checks
  excluded for this target.
- **What it defends against:** fragmented quality output and missed static gates
  when an automated agent or contributor wants one consolidated report.
- **Why analyse this:** many independent tools can make feedback hard to triage.
  A unified runner turns multiple static checks into a single operational lane.
- **Value provided:** consistent local/agent feedback and a compact failure view.
- **Why here:** pre-push has enough time budget for a consolidated static pass,
  and it complements the individual pre-commit hooks.

### Coverage and Per-module Coverage

**Summary:** Coverage is enforced both globally and per module at 85 percent.

- **Tool used:** `pytest-cov` plus `scripts/check_module_coverage.py`, invoked by
  `make test-coverage`.
- **What is analysed:** the safe pytest suite with coverage for
  `perplexity_cli`; reports are generated in terminal, JSON, and XML formats.
  `[tool.coverage.run]` enables branch coverage and `[tool.coverage.report]`
  sets `fail_under = 85`. The custom module check skips files with fewer than
  five reportable statements and fails modules below 85 percent.
- **What it defends against:** untested branches, modules that hide behind good
  aggregate coverage, and changes that add behaviour without corresponding
  tests.
- **Why analyse this:** global coverage can be misleading. A well-tested module
  can mask an untested new module. Per-module enforcement prevents that hiding.
- **Value provided:** measurable regression protection and clearer accountability
  for new code.
- **Why here:** coverage is slower than a fail-fast test run and is more useful
  at branch granularity than every individual commit.

### Safety Dependency Scan

**Summary:** Safety checks dependencies for known vulnerabilities, using an API
key directly or through Infisical when available.

- **Tool used:** Safety through `scripts/agent_check.py safety`, invoked by
  `make safety`; the Makefile uses `SAFETY_API_KEY` when set or wraps the command
  with `infisical run --env dev` when Infisical is installed.
- **What is analysed:** the resolved project dependency set visible to the
  Safety runner.
- **What it defends against:** known vulnerable dependency versions and supply
  chain risk introduced by direct or transitive packages.
- **Why analyse this:** source code can be clean while a dependency contains a
  published vulnerability. This project depends on networking, cryptography,
  rich output, MCP, and HTTP libraries, so dependency health matters.
- **Value provided:** supply-chain visibility before code is pushed and again in
  CI.
- **Why here:** dependency scanning is slower and may need credentials. Pre-push
  and CI are better positions than pre-commit.

### Fuzz Tests

**Summary:** Fuzz tests exercise parser and boundary logic with generated inputs
through the `tests/test_fuzz.py` lane.

- **Tool used:** pytest running fuzz-marked tests, invoked by `make test-fuzz` as
  `uv run pytest tests/test_fuzz.py -q --tb=line -x -m fuzz`.
- **What is analysed:** fuzz harnesses marked `fuzz`; default pytest config
  excludes these from ordinary test runs.
- **What it defends against:** crashes, malformed-input failures, parser edge
  cases, and assumptions that only hold for hand-written examples.
- **Why analyse this:** CLIs process user input, JSON, files, URLs, and remote
  response shapes. Fuzzing explores unexpected shapes more cheaply than writing
  every case by hand.
- **Value provided:** resilience against weird inputs and stronger confidence in
  validation/error paths.
- **Why here:** fuzzing is CPU-intensive relative to unit tests, so it runs at
  pre-push/CI rather than on every commit.

### Sonar Reports

**Summary:** The repository generates Bandit JSON reports for SonarQube import.

- **Tool used:** custom script `scripts/generate_sonar_reports.py`, invoked by
  `make sonar-reports`.
- **What is analysed:** security report generation based on Bandit output.
- **What it defends against:** losing machine-readable security findings in
  systems that consume external reports.
- **Why analyse this:** local terminal failures are useful to developers, but CI
  and code-quality dashboards often need structured artefacts.
- **Value provided:** creates report material that can be uploaded or inspected
  by external quality tooling.
- **Why here:** report generation is not needed for every commit. It belongs in
  pre-push/CI, where whole-branch artefacts are meaningful.

### Architecture Check

**Summary:** The custom architecture checker enforces ports-and-adapters layer
rules and framework isolation.

- **Tool used:** `scripts/check_architecture.py`, invoked by `make arch-check`.
- **What is analysed:** imports in `src/perplexity_cli`, mapped to layers:
  domain, application, infrastructure, and presentation. It checks import
  direction, framework imports in domain/application layers, inter-adapter
  coupling, and utility isolation.
- **What it defends against:** framework leakage into domain models, application
  services depending directly on CLI/HTTP libraries, infrastructure adapters
  tangling with each other, and utility modules becoming backdoors into higher
  layers.
- **Why analyse this:** architecture erosion is usually incremental. A single
  convenient import can invert dependencies and make future testing or reuse
  harder.
- **Value provided:** executable architecture fitness function. It preserves the
  intended separation between core business objects, orchestration, adapters,
  and presentation.
- **Why here:** architecture checks need whole-source context and are less about
  a staged hunk than about branch-level direction. They also run in CI through
  `make check`.

### Coupling Check

**Summary:** The coupling checker calculates Robert C. Martin package metrics and
flags modules far from the main sequence.

- **Tool used:** `scripts/check_coupling.py`, invoked by `make coupling-check`.
- **What is analysed:** AST imports and class definitions under
  `src/perplexity_cli`. It computes afferent coupling (`Ca`), efferent coupling
  (`Ce`), instability (`I = Ce / (Ca + Ce)`), abstractness (`A`), and distance
  from the main sequence (`D = |A + I - 1|`). The default distance threshold is
  `0.3`.
- **What it defends against:** modules that are too concrete and too stable,
  modules that are abstract but unused, and dependency structures that are hard
  to change safely.
- **Why analyse this:** coupling problems are not always visible in a diff. They
  emerge from the graph of imports across the package.
- **Value provided:** architectural trend visibility with objective metrics.
- **Why here:** the check needs whole-repository import context, so pre-push and
  CI are better than staged-file pre-commit.

### Diff-scoped Mutation Testing

**Summary:** Mutation testing changes source code in small ways and expects tests
to fail. The pre-push gate scopes this to changed source files.

- **Tool used:** `mutmut`, invoked by `make mutate-diff` after
  `scripts/discover_mutate_diff_files.py` selects changed files.
- **What is analysed:** changed Python source files compared with the base
  branch. `[tool.mutmut]` sets `paths_to_mutate`, `tests_dir`, ignored tests for
  mutation runs, and a do-not-mutate path for `formatting/registry.py`.
- **What it defends against:** tests that execute code but do not assert the
  behaviour strongly enough to catch meaningful changes.
- **Why analyse this:** coverage can say a line ran; mutation testing asks
  whether the test would notice if the logic were wrong.
- **Value provided:** stronger test-quality signal for the files changed on the
  branch.
- **Why here:** mutation testing is expensive. Running only on changed files at
  push time balances value and developer latency.

### Property-based Tests

**Summary:** Hypothesis tests verify invariants over many generated examples,
with different profiles for development, push, CI, and fast runs.

- **Tool used:** `hypothesis` through pytest, invoked by
  `make test-property-push` and `make test-property-ci`.
- **What is analysed:** `tests/test_property.py`. Profiles in `tests/conftest.py`
  set `dev` to 10 examples, `push` to 50 examples, `ci` to 1000 examples with a
  500 ms deadline, and `fast` to 3 examples.
- **What it defends against:** edge cases that example-based tests miss,
  especially around serialisation, validation, parsing, and reversible
  transformations.
- **Why analyse this:** generated examples probe the space around invariants
  instead of only checking hand-picked cases.
- **Value provided:** broader behavioural assurance with a tunable speed/depth
  trade-off.
- **Why here:** push gets a balanced 50-example profile; CI gets the deeper
  1000-example profile where latency is acceptable and reproducibility matters.

## CI Gates

### Ubuntu CI Matrix

**Summary:** The main CI job runs `make ci` on Ubuntu for Python 3.12 and 3.13
from a clean dependency sync.

- **Tool used:** GitHub Actions with `actions/checkout`, `astral-sh/setup-uv`,
  `actions/setup-python`, `uv sync --all-extras --locked`, and `make ci`.
- **What is analysed:** the complete repository under two Python versions.
  `make ci` runs `check`, `test-coverage`, `test-fuzz`, `safety`,
  `sonar-reports`, `test-property-ci`, `build`, `verify`, and `smoke-test`.
- **What it defends against:** local-environment drift, missing lockfile updates,
  Python-version incompatibility, package build failures, hidden test failures,
  and dependency problems not present on a developer machine.
- **Why analyse this:** a local hook can be skipped or run in a dirty
  environment. CI is the shared clean-room result for pushes and pull requests.
- **Value provided:** reproducible project-level confidence and protected
  compatibility with supported Python versions.
- **Why here:** CI is slower but authoritative. It repeats local gates and adds
  packaging verification that does not belong in every pre-commit hook.

### macOS Safe Checks

**Summary:** A separate macOS job runs `make check && make test` on Python 3.12.

- **Tool used:** GitHub Actions on `macos-latest`.
- **What is analysed:** static checks and the safe test suite on macOS.
- **What it defends against:** POSIX-but-not-Linux differences, path behaviour,
  shell/script assumptions, filesystem behaviour, and platform-specific test
  failures.
- **Why analyse this:** the CLI is intended for local terminal use, and macOS is
  a likely contributor/user platform.
- **Value provided:** cross-platform confidence without duplicating the full
  expensive Ubuntu matrix.
- **Why here:** macOS runners are slower/costlier, so this lane runs safe checks
  rather than the full release-grade pipeline.

### Build, Verify, and Smoke Test

**Summary:** CI builds distributable artefacts, validates metadata, verifies
wheel contents, and installs the wheel in isolation.

- **Tool used:** `uv build`, `twine check`, `scripts/verify_wheel.py`, and
  `scripts/smoke_test.sh` through `make build`, `make verify`, and
  `make smoke-test`.
- **What is analysed:** source distribution, wheel metadata, packaged resources,
  installed console entry points, and basic installed-package behaviour.
- **What it defends against:** packages that pass tests in editable mode but fail
  after installation, missing package data, invalid distribution metadata, broken
  entry points, and accidental omission of runtime resources.
- **Why analyse this:** users install wheels, not the developer's editable
  checkout. Packaging is a separate contract from source tests.
- **Value provided:** confidence that a published package can actually be
  installed and invoked.
- **Why here:** building and smoke-testing every commit would be too heavy, but
  CI and release workflows must prove distribution integrity.

## Release Gates

### Tag, Version, Runtime, and Publish Validation

**Summary:** The PyPI workflow only runs on `v*` tags and validates that the tag,
`pyproject.toml`, and runtime `__version__` agree before publishing.

- **Tool used:** GitHub Actions workflow `.github/workflows/publish-to-pypi.yml`,
  Python `tomllib`, runtime import from `src`, `make ci`, PyPI trusted publishing
  via OIDC, and `softprops/action-gh-release`.
- **What is analysed:** tag name, package metadata version, runtime package
  version, full CI pipeline, distribution artefacts, and GitHub Release files.
- **What it defends against:** publishing the wrong version, mismatched runtime
  metadata, releasing artefacts that did not pass CI, manual credential leakage,
  and missing release files.
- **Why analyse this:** release mistakes are externally visible and harder to
  undo than local or CI failures.
- **Value provided:** a repeatable, auditable release path with OIDC instead of a
  long-lived PyPI token.
- **Why here:** only tag builds should publish. The version check has no value
  until a tag exists, and publishing must be after CI succeeds.

### Local `make release`

**Summary:** The local release target bumps the version, updates the lockfile,
runs CI, commits, tags, and pushes.

- **Tool used:** Make, `sed`, `uv lock`, `make ci`, Git commit/tag/push.
- **What is analysed:** the same full CI pipeline before local release commit and
  tag creation.
- **What it defends against:** tagging a version that has not passed the release
  pipeline locally.
- **Why analyse this:** the local target is an operator workflow; it front-loads
  validation before triggering the remote publish workflow.
- **Value provided:** a single documented path for release preparation.
- **Why here:** it belongs at release time because it mutates version metadata
  and creates Git history.

## Composite Targets and Source-of-truth Design

The `Makefile` is the command source of truth. `lefthook.yml` delegates most
checks to Make targets, while CI delegates to the composite `make ci` target.
This prevents local hooks, manual commands, and GitHub Actions from silently
diverging.

- `make check` runs static checks: `format-check`, `lint`, `typecheck-all`,
  `security`, `complexity`, `semgrep`, `arch-check`, and `coupling-check`.
- `make ci` runs `check`, coverage, fuzzing, Safety, Sonar reports, CI-depth
  property tests, build, verify, and smoke test.
- Stage-specific hooks remain inline in `lefthook.yml` only when they need Git
  staging behaviour, such as `{staged_files}` and `stage_fixed: true`.

This design has three values: contributors can run the same commands locally,
CI does not duplicate long shell recipes, and documentation can point to one
place for command semantics.

## Confirmed Non-goals and Absent Gates

Several common tools are deliberately not described as active gates because they
are not configured in this repository. The absence matters because it prevents
readers from assuming hidden coverage that does not exist.

- There is no `.pre-commit-config.yaml`; Lefthook is the local hook runner.
- There is no Husky setup; this is a Python project and hook orchestration is in
  `lefthook.yml`.
- There is no mypy configuration; Pyright and `ty` provide type analysis.
- There is no Flake8, Black, or isort configuration; Ruff covers linting,
  formatting, and import ordering.
- There is no `.coveragerc`; coverage configuration lives in `pyproject.toml`.
- There is no tox configuration; `uv`, Make targets, and GitHub Actions define
  the environment and command matrix.
- There is no Dockerfile or container scanner gate in the repository.
- There is no Dependabot or Renovate config visible in the repository.
- There is no `pip-audit` gate; dependency vulnerability scanning is routed
  through Safety.
- There is no Import Linter config; architecture policy is enforced by the
  custom `scripts/check_architecture.py` analyser and Semgrep rules.

## Why These Analyses Matter Together

No single analyser proves the repository is correct. The value comes from
overlap without total duplication:

- Type checkers protect interface contracts but do not prove runtime behaviour.
- Unit tests prove examples but do not prove untested branches or generated edge
  cases.
- Coverage proves code ran but not that assertions were meaningful.
- Mutation testing probes assertion strength but is too expensive for every
  file on every commit.
- Fuzzing and property tests explore broad input spaces but do not replace clear
  example tests.
- Bandit, Infisical, Gitleaks, and Safety cover different parts of the security
  problem: source patterns, current changes, commit history, and dependencies.
- Ruff, Semgrep, Radon, architecture checks, and coupling checks protect code
  shape at different levels: statement, pattern, function, layer, and graph.
- Build, verify, and smoke tests protect the installed package contract, which
  source-level checks cannot see.

The pipeline therefore favours fast local feedback first, deeper branch-level
confidence before push, clean-room reproducibility in CI, and distribution
correctness at release time.
