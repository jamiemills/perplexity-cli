# =============================================================================
# Makefile -- single source of truth for all lint, test, and build commands.
# =============================================================================

include quality/gates.conf

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON_VERSION ?= 3.12
PROPERTY_PROFILE ?= ci
SEMGREP_VERSION := 1.171.0
ACTIONLINT_PY_VERSION := 1.7.12.24
SEMGREP := uvx --from semgrep==$(SEMGREP_VERSION) semgrep
ACTIONLINT := uvx --from actionlint-py==$(ACTIONLINT_PY_VERSION) actionlint
SEMGREP_CONFIGS := \
	--config .semgrep.yml \
	--config .semgrep-community-python.yml \
	--config .semgrep-community-comment.yml \
	--config .semgrep-community-best-practices.yml
SEMGREP_TARGETS ?= .
SEMGREP_OPTIONS := \
	$(SEMGREP_SEVERITY) \
	--exclude tests/ \
	--exclude '.semgrep-community-*.yml'

# ---------------------------------------------------------------------------
# Development setup
# ---------------------------------------------------------------------------

.PHONY: check-uv check-gitleaks setup configure-opencode opencode-check opencode-audit

check-uv:  ## Verify uv is installed
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv is required to set up this project."; \
		echo "Install it from https://docs.astral.sh/uv/getting-started/installation/"; \
		echo "or run: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; \
	}

check-gitleaks:  ## Verify gitleaks is installed
	@command -v gitleaks >/dev/null 2>&1 || { \
		echo "gitleaks is required for pre-push secret detection."; \
		echo "Install: brew install gitleaks"; \
		echo "Or see: https://github.com/gitleaks/gitleaks#installing"; \
		exit 1; \
	}

check-infisical:  ## Verify infisical CLI is installed
	@command -v infisical >/dev/null 2>&1 || { \
		echo "infisical is required for pre-commit secret scanning."; \
		echo "Install: brew install infisical"; \
		echo "Or see: https://infisical.com/docs/cli/overview"; \
		exit 1; \
	}

setup: check-uv check-gitleaks check-infisical
	uv venv --python $(PYTHON_VERSION) --allow-existing
	uv sync --locked --extra dev --group dev
	uv run lefthook install
	uv run pxcli --help > /dev/null

configure-opencode:
	@echo "Installing OpenCode plugin dependencies..."
	@npm --prefix .opencode ci
	@$(MAKE) opencode-check
	@echo ""
	@echo "Verifying plugin and agent wiring..."
	@ok=true; \
	for f in quality-gate.ts pxcli-quality.ts pre-push-docs-check.ts; do \
		if [ ! -f .opencode/plugins/$$f ]; then \
			echo "  MISSING: .opencode/plugins/$$f"; ok=false; \
		else echo "  OK: .opencode/plugins/$$f"; fi; \
	done; \
	if [ ! -f opencode.jsonc ]; then \
		echo "  MISSING: opencode.jsonc"; ok=false; \
	else echo "  OK: opencode.jsonc"; fi; \
	if [ "$$ok" != "true" ]; then \
		echo ""; \
		echo "Some OpenCode files are missing."; \
		exit 1; \
	fi
	@echo ""
	@echo "OpenCode wiring verified."
	@echo ""

opencode-check:  ## Type-check OpenCode plugins and validate resolved config when available
	@npm --prefix .opencode run check
	@if command -v opencode >/dev/null 2>&1; then \
		opencode debug config >/dev/null; \
	else \
		echo "OpenCode CLI not installed; resolved-config validation skipped."; \
	fi

opencode-audit:  ## Run npm audit for OpenCode dependencies (high/critical)
	@npm --prefix .opencode audit --audit-level=high; \
	status=$$?; \
	if [ $$status -eq 0 ]; then \
		echo "npm audit: no high/critical vulnerabilities."; \
	elif [ $$status -eq 1 ]; then \
		echo "npm audit: HIGH/CRITICAL vulnerabilities found."; \
		exit 1; \
	else \
		echo "npm audit: infrastructure error (exit $$status)."; \
		exit 2; \
	fi

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

.PHONY: format-check format-fix

format-check:  ## Check code formatting (ruff)
	uv run ruff format --check src tests scripts

format-fix:  ## Auto-fix formatting and lint issues (ruff)
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------

.PHONY: lint

lint:  ## Run linter (ruff check)
	uv run ruff check src tests scripts

# ---------------------------------------------------------------------------
# Type checking
# ---------------------------------------------------------------------------

.PHONY: typecheck typecheck-pyright typecheck-scripts typecheck-all

typecheck:  ## Run type checker (ty)
	uv run ty check src

typecheck-pyright:  ## Run type checker (pyright, strict mode)
	uv run pyright src/

typecheck-scripts:  ## Run pyright on quality scripts (strict mode)
	uv run pyright scripts/

typecheck-all: typecheck typecheck-pyright typecheck-scripts  ## Run all type checkers

# ---------------------------------------------------------------------------
# Security and dead-code analysis
# ---------------------------------------------------------------------------

.PHONY: bandit vulture gitleaks gitleaks-ci security

bandit:  ## Run bandit security linter
	uv run bandit -c pyproject.toml -r src/ scripts/

vulture:  ## Run vulture dead-code detector
	uv run vulture src/ vulture_whitelist.py --min-confidence $(MIN_CONFIDENCE)

gitleaks:  ## Run gitleaks secret detection (pre-push: skips when not installed)
	scripts/gitleaks_check.sh

gitleaks-ci:  ## Run gitleaks in CI (fails if not installed)
	CI_NO_SKIP=1 scripts/gitleaks_check.sh ci-full

security: bandit vulture  ## Run all security checks

# ---------------------------------------------------------------------------
# Complexity
# ---------------------------------------------------------------------------

.PHONY: complexity-cc complexity-mi complexity

complexity-cc:  ## Check cyclomatic complexity (radon)
	@output=$$(uv run radon cc src/ -s -n $(RADON_CC_GRADE)) && \
	if [ -n "$$output" ]; then \
		echo "Cyclomatic complexity violations (B or worse):"; \
		echo "$$output"; \
		exit 1; \
	fi

complexity-mi:  ## Check maintainability index (radon)
	@output=$$(uv run radon mi src/ -s -n $(RADON_MI_GRADE)) && \
	if [ -n "$$output" ]; then \
		echo "Maintainability index violations (B or worse):"; \
		echo "$$output"; \
		exit 1; \
	fi

complexity: complexity-cc complexity-mi  ## Run all complexity checks

# ---------------------------------------------------------------------------
# Semgrep
# ---------------------------------------------------------------------------

.PHONY: semgrep semgrep-json semgrep-advisory semgrep-advisory-local semgrep-advisory-report

semgrep:  ## Run the immutable blocking Semgrep ruleset via policy wrapper
	uv run python scripts/semgrep_policy.py --blocking \
		$(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS) $(SEMGREP_TARGETS)

semgrep-json:  ## Run the immutable Semgrep ruleset with machine-readable output
	@$(SEMGREP) $(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS) --json $(SEMGREP_TARGETS)

semgrep-advisory:  ## Scan latest community packs (advisory, non-blocking)
	uvx semgrep \
		--config p/python \
		--config p/comment \
		--config p/r2c-best-practices \
		$(SEMGREP_SEVERITY) \
		--exclude tests/ \
		--metrics=off .

semgrep-advisory-local:  ## Run custom advisory Semgrep rules locally via wrapper
	uv run python scripts/semgrep_policy.py --advisory \
		$(SEMGREP_CONFIGS) $(SEMGREP_OPTIONS) $(SEMGREP_TARGETS)

semgrep-advisory-report:  ## Generate advisory Semgrep SARIF and JSON report
	@mkdir -p build/reports
	@uvx semgrep \
		--config p/python --config p/comment --config p/r2c-best-practices \
		$(SEMGREP_SEVERITY) --exclude tests/ --metrics=off \
		--json-output=build/reports/semgrep-advisory.json \
		--sarif-output=build/reports/semgrep-advisory.sarif \
		.; status=$$?; \
	if [ $$status -eq 0 ]; then echo "Semgrep advisory: no findings."; \
	elif [ $$status -eq 1 ]; then echo "Semgrep advisory: findings reported (advisory)."; \
	else echo "Semgrep advisory: scanner error (exit $$status)."; exit $$status; fi

# ---------------------------------------------------------------------------
# Architecture enforcement
# ---------------------------------------------------------------------------

.PHONY: coupling-check coupling-report metrics-track arch-check arch-check-dynamic arch-explain

coupling-check:  ## Measure coupling and stability metrics (blocking gate when --max-flagged exceeded)
	uv run python scripts/check_coupling.py --max-flagged $(MAX_FLAGGED) --blocking

coupling-report:  ## Generate advisory coupling report with trend support
	uv run python scripts/check_coupling.py --trend-compare quality/baselines/coupling-report.json

metrics-track:  ## Track CC and MI trends over recent git revisions
	uv run python scripts/track_metrics.py

arch-check:  ## Check architecture layer boundaries (hard gate, no baseline)
	uv run python scripts/check_architecture.py

arch-check-dynamic:  ## Check dynamic import architecture enforcement
	uv run python scripts/check_dynamic_imports.py

arch-explain:  ## Display the architecture layer model
	uv run python scripts/check_architecture.py --explain

# ---------------------------------------------------------------------------
# Dependency hygiene
# ---------------------------------------------------------------------------

.PHONY: deptry pip-audit dependency-hygiene

deptry:  ## Check for missing, unused, and misplaced dependencies
	uv run deptry src tests scripts

pip-audit:  ## Scan dependencies for known vulnerabilities
	uv run pip-audit .

dependency-hygiene: deptry  ## Run all dependency hygiene checks

# ---------------------------------------------------------------------------
# Mutation testing
# ---------------------------------------------------------------------------

.PHONY: mutate mutate-results mutate-module mutate-diff mutate-estimate mutate-browse mutate-full-policy

mutate:  ## Run mutation testing on the full source tree
	uv run mutmut run

mutate-full-policy:  ## Run full mutation testing then enforce the canonical policy
	uv run mutmut run
	uv run python scripts/mutation_policy.py \
		--report-path quality/evidence/mutation-report.json

mutate-estimate:  ## Estimate how long a full mutation run would take
	uv run mutmut print-time-estimates

mutate-module:  ## Run mutation testing on a specific module
ifndef MODULE
	$(error MODULE is not set. Usage: make mutate-module MODULE=api)
endif
	uv run mutmut run src/perplexity_cli/$(MODULE)/

mutate-diff:
	@mapfile -t files < <(uv run python scripts/discover_mutate_diff_files.py); \
	if [ "$${#files[@]}" -eq 0 ]; then \
		echo "No source files changed -- skipping mutation tests."; \
		exit 0; \
	fi; \
	echo "Mutating $${#files[@]} changed file(s):"; \
	printf '  %s\n' "$${files[@]}"; \
	patterns=(); \
	for f in "$${files[@]}"; do \
		p="$${f#src/}"; \
		p="$${p%.py}"; \
		p="$${p//\//.}"; \
		patterns+=("$${p}*"); \
	done; \
	uv run mutmut run "$${patterns[@]}"

mutate-results:  ## Show mutation testing results from last run
	uv run mutmut results

mutate-browse:  ## Browse mutation results in interactive TUI
	uv run mutmut browse

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

.PHONY: test test-coverage-report module-coverage test-coverage test-fuzz test-property test-property-push test-property-ci

test:  ## Run tests without coverage (fail-fast, parallel)
	uv run pytest tests/ -q --tb=line -x -n auto

test-coverage-report:  ## Run tests and produce coverage reports
	uv run pytest tests/ -q --tb=line -x -n auto \
		--cov=perplexity_cli --cov-report=term-missing \
		--cov-report=json --cov-report=xml:coverage.xml

module-coverage:  ## Enforce the minimum on every measured source module
	uv run python scripts/check_module_coverage.py --min-coverage $(MIN_COVERAGE)

test-coverage: test-coverage-report module-coverage  ## Run tests with coverage enforcement

test-fuzz:  ## Run fuzz tests
	uv run pytest tests/test_fuzz.py -q --tb=line -x -m fuzz

test-property:  ## Run property-based tests (dev profile, 10 examples)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=dev

test-property-push:  ## Run property-based tests (push profile, 50 examples)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=push

test-property-ci:  ## Run property-based tests (CI profile, 1000 examples)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=ci

# ---------------------------------------------------------------------------
# Diff coverage
# ---------------------------------------------------------------------------

.PHONY: diff-coverage

diff-coverage:  ## Check coverage on changed lines
	@if [ ! -f coverage.xml ]; then \
		echo "coverage.xml not found -- run 'make test-coverage' first."; \
		exit 2; \
	fi
	uvx diff-cover coverage.xml --fail-under=$(DIFF_COVERAGE_THRESHOLD)

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

.PHONY: safety safety-gate infisical-scan

safety:  ## Run safety dependency scan (skips locally when credentials unavailable)
	@if [ -n "$$SAFETY_API_KEY" ]; then \
		uv run python scripts/agent_check.py safety; \
	elif command -v infisical >/dev/null 2>&1; then \
		if infisical run --env dev -- bash -c 'test -n "$$SAFETY_API_KEY"' \
			>/dev/null 2>&1; then \
			infisical run --env dev -- uv run python scripts/agent_check.py safety; \
		else \
			echo "Safety scan skipped: credentials unavailable through infisical."; \
			echo "Set SAFETY_API_KEY or configure infisical."; \
		fi; \
	else \
		echo "Safety scan skipped: SAFETY_API_KEY not set and infisical not available."; \
		echo "Set SAFETY_API_KEY or install infisical (brew install infisical)."; \
		echo "CI requires safety credentials -- set SAFETY_API_KEY secret in GitHub."; \
	fi
safety-gate:  ## Run safety scan in CI mode (fails if credentials unavailable)
	@if [ -n "$$SAFETY_API_KEY" ]; then \
		uv run python scripts/agent_check.py safety; \
	elif command -v infisical >/dev/null 2>&1; then \
		infisical run --env dev -- uv run python scripts/agent_check.py safety; \
		status=$$?; \
		if [ $$status -ne 0 ]; then \
			echo "ERROR: authenticated Safety scan failed through infisical."; \
			exit $$status; \
		fi; \
	else \
		echo "ERROR: Safety scan requires SAFETY_API_KEY or infisical CLI."; \
		echo "Set SAFETY_API_KEY secret in GitHub repository settings."; \
		exit 2; \
	fi

infisical-scan:  ## Scan uncommitted changes for secrets
	@if command -v infisical >/dev/null 2>&1; then \
		infisical scan git-changes --verbose --exit-code 1; \
	else \
		echo "Infisical scan skipped: infisical CLI not installed."; \
	fi

# ---------------------------------------------------------------------------
# Build and verify
# ---------------------------------------------------------------------------

.PHONY: build verify smoke-test

build:  ## Build sdist and wheel
	rm -rf dist
	uv build

verify:  ## Verify built distributions
	uvx twine check dist/*
	uv run python scripts/verify_wheel.py

smoke-test:  ## Install wheel in isolated venv and run smoke tests
	scripts/smoke_test.sh

# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------

.PHONY: release

release:  ## Bump version, lock, commit, tag, and push
ifndef V
	$(error V is not set. Usage: make release V=0.7.2)
endif
	@echo "Releasing v$(V)..."
	sed -i '' 's/^version = ".*"/version = "$(V)"/' pyproject.toml
	uv lock
	$(MAKE) ci-trusted
	git add pyproject.toml uv.lock
	git commit -m "Release $(V)"
	git tag -a "v$(V)" -m "Release $(V)"
	git push origin master
	git push origin "v$(V)"

# ---------------------------------------------------------------------------
# Composite targets
# ---------------------------------------------------------------------------

.PHONY: check agent-check agent-check-push agent-check-no-tests

CHECK_PREREQS :=
ifeq ($(CHECK_FORMAT),true)
CHECK_PREREQS += format-check
endif
ifeq ($(CHECK_LINT),true)
CHECK_PREREQS += lint
endif
ifeq ($(CHECK_TYPECHECK_ALL),true)
CHECK_PREREQS += typecheck-all
endif
ifeq ($(CHECK_SECURITY),true)
CHECK_PREREQS += security
endif
ifeq ($(CHECK_COMPLEXITY),true)
CHECK_PREREQS += complexity
endif
ifeq ($(CHECK_SEMGREP),true)
CHECK_PREREQS += semgrep
endif
ifeq ($(CHECK_ARCH),true)
CHECK_PREREQS += arch-check
endif
ifeq ($(CHECK_COUPLING),true)
CHECK_PREREQS += coupling-check
endif
ifeq ($(CHECK_RATCHETS),true)
CHECK_PREREQS += ratchets
endif
ifeq ($(CHECK_IMPORT_LINTER),true)
CHECK_PREREQS += import-linter
endif
ifeq ($(CHECK_DYNAMIC_IMPORTS),true)
CHECK_PREREQS += arch-check-dynamic
endif

ifeq ($(CHECK_DEPTRY),true)
CHECK_PREREQS += deptry
endif

check: $(CHECK_PREREQS)  ## Run all static checks

agent-check:
	uv run python scripts/agent_check.py pre-commit

agent-check-no-tests:
	uv run python scripts/agent_check.py --no-tests --no-fix pre-commit

agent-check-push:
	uv run python scripts/agent_check.py pre-push

.PHONY: check ci ci-static ci-test-coverage ci-test-compat ci-fuzz-status ci-property ci-package ci-trusted analyser-contract-tests

analyser-contract-tests:  ## Run analyser contract validation tests
	uv run pytest tests/test_analyser_contracts.py -q

ci-static: format-check lint typecheck-all bandit vulture complexity actionlint ## CI static analysis lane

ci-test-coverage: test-coverage ## CI test lane with per-module coverage (Python 3.12)

ci-test-compat: test ## CI compatibility tests without coverage (Python 3.13/3.14)

ci-fuzz-status: test-fuzz ## CI fuzz status (non-authoritative until rank 4)

ci-property: test-property-$(PROPERTY_PROFILE) ## CI property tests

ci-package: build verify ## CI package build and verification

ci: ci-static ci-test-coverage ci-fuzz-status pip-audit sonar-reports ci-property ci-package smoke-test  ## Full local CI pipeline

ci-trusted: ci safety-gate  ## Full CI plus authenticated Safety for trusted code

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

ratchets: file-size suppression-ratchet ruff-architecture typecheck-strict-ratchet semgrep-architecture  ## Run all quality gates

file-size:  ## Hard gate: block oversized source files
	@uv run python scripts/check_file_size.py --max-lines $(FILE_SIZE_CAP); \
	if [ $$? -ne 0 ]; then \
		echo "File-size gate FAILED."; \
		echo "Split the file, or raise FILE_SIZE_CAP in quality/gates.conf."; \
		exit 1; \
	fi

suppression-ratchet:  ## Ratchet: block new/grown inline suppressions
	uv run python scripts/check_suppressions.py

ruff-architecture:  ## Hard gate: complexity/parameter findings (C901/PLR0913/ARG)
	@uv run ruff check --select C901,PLR0913,PLR2004,ARG001,ARG002 \
		--config "lint.mccabe.max-complexity = 5" \
		--config "lint.pylint.max-args = 4" \
		--output-format concise src/; \
	status=$$?; \
	if [ $$status -ne 0 ]; then \
		echo ""; \
		echo "Ruff architecture gate FAILED."; \
	fi; \
	exit $$status

typecheck-strict-ratchet:  ## Hard gate: pyright strict
	uv run pyright src/

semgrep-architecture:  ## Ratchet: block new structural findings
	uv run python scripts/check_semgrep_architecture.py

# ---------------------------------------------------------------------------
# Sonar
# ---------------------------------------------------------------------------

.PHONY: sonar-reports

sonar-reports:  ## Generate SonarQube reports
	uv run python scripts/generate_sonar_reports.py

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

.PHONY: clean

clean:  ## Remove build artefacts
	rm -rf dist build .coverage coverage.json coverage.xml \
		.pytest_cache .mypy_cache .ruff_cache

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Import Linter
# ---------------------------------------------------------------------------

.PHONY: import-linter

import-linter:  ## Check architecture import contracts
	uv run lint-imports

# ---------------------------------------------------------------------------
# Refurb
# ---------------------------------------------------------------------------

.PHONY: refurb

refurb:  ## Run Refurb readability advisory checks
	uv run refurb src/

# ---------------------------------------------------------------------------
# Composite additions for import-linter
# ---------------------------------------------------------------------------

.PHONY: quality-architecture

quality-architecture: import-linter arch-check coupling-report  ## Run all architecture checks

# ---------------------------------------------------------------------------
# Workflow validation
# ---------------------------------------------------------------------------

.PHONY: actionlint

actionlint:  ## Validate GitHub Actions workflows with actionlint
	$(ACTIONLINT)
