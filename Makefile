# =============================================================================
# Makefile -- single source of truth for all lint, test, and build commands.
# =============================================================================

include quality/gates.conf

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON_VERSION ?= 3.12
PROPERTY_PROFILE ?= ci

# ---------------------------------------------------------------------------
# Development setup
# ---------------------------------------------------------------------------

.PHONY: check-uv check-gitleaks setup configure-opencode

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
	@cd .opencode && npm install
	@echo ""
	@echo "Verifying plugin and agent wiring..."
	@ok=true; \
	for f in quality-gate.ts pxcli-quality.ts pre-push-docs-check.ts plan-compliance-gate.ts; do \
		if [ ! -f .opencode/plugins/$$f ]; then \
			echo "  MISSING: .opencode/plugins/$$f"; ok=false; \
		else echo "  OK: .opencode/plugins/$$f"; fi; \
	done; \
	if [ ! -f .opencode/agents/quality-plan-reviewer.md ]; then \
		echo "  MISSING: .opencode/agents/quality-plan-reviewer.md"; ok=false; \
	else echo "  OK: .opencode/agents/quality-plan-reviewer.md"; fi; \
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

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

.PHONY: format-check format-fix

format-check:  ## Check code formatting (ruff)
	uv run ruff format --check src tests

format-fix:  ## Auto-fix formatting and lint issues (ruff)
	uv run ruff format src tests
	uv run ruff check --fix src tests

# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------

.PHONY: lint

lint:  ## Run linter (ruff check)
	uv run ruff check src tests

# ---------------------------------------------------------------------------
# Type checking
# ---------------------------------------------------------------------------

.PHONY: typecheck typecheck-pyright typecheck-all

typecheck:  ## Run type checker (ty)
	uv run ty check src

typecheck-pyright:  ## Run type checker (pyright, strict mode)
	uv run pyright src/

typecheck-all: typecheck typecheck-pyright  ## Run all type checkers

# ---------------------------------------------------------------------------
# Security and dead-code analysis
# ---------------------------------------------------------------------------

.PHONY: bandit vulture gitleaks gitleaks-ci security

bandit:  ## Run bandit security linter
	uv run bandit -c pyproject.toml -r src/

vulture:  ## Run vulture dead-code detector
	uv run vulture src/ vulture_whitelist.py --min-confidence $(MIN_CONFIDENCE)

gitleaks:  ## Run gitleaks secret detection (pre-push: skips when not installed)
	scripts/gitleaks_check.sh

gitleaks-ci:  ## Run gitleaks in CI (fails if not installed)
	CI_NO_SKIP=1 scripts/gitleaks_check.sh

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

.PHONY: semgrep

semgrep:  ## Run semgrep static analysis
	uvx semgrep \
		--config .semgrep.yml \
		--config p/python \
		--config p/comment \
		--config p/r2c-best-practices \
		$(SEMGREP_SEVERITY) \
		--exclude-rule python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure \
		--exclude tests/ \
		--error --metrics=off .

# ---------------------------------------------------------------------------
# Architecture enforcement
# ---------------------------------------------------------------------------

.PHONY: coupling-check metrics-track arch-check arch-explain

coupling-check:  ## Measure coupling and stability metrics
	uv run python scripts/check_coupling.py --max-flagged $(MAX_FLAGGED)

metrics-track:  ## Track CC and MI trends over recent git revisions
	uv run python scripts/track_metrics.py

arch-check:  ## Check architecture layer boundaries (hard gate, no baseline)
	uv run python scripts/check_architecture.py --no-baseline

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

.PHONY: mutate mutate-results mutate-module mutate-diff mutate-estimate mutate-browse

mutate:  ## Run mutation testing on the full source tree
	uv run mutmut run

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

.PHONY: test test-coverage test-fuzz test-property test-property-push test-property-ci

test:  ## Run tests without coverage (fail-fast, parallel)
	uv run pytest tests/ -q --tb=line -x -n auto

test-coverage:  ## Run tests with coverage enforcement
	uv run pytest tests/ -q --tb=line -x -n auto \
		--cov=perplexity_cli --cov-report=term-missing \
		--cov-report=json --cov-report=xml:coverage.xml
	uv run python scripts/check_module_coverage.py --min-coverage 80

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
		infisical run --env dev -- \
			uv run python scripts/agent_check.py safety \
			|| { echo "Safety scan skipped: infisical run failed."; \
			     echo "Set SAFETY_API_KEY or configure infisical."; }; \
	else \
		echo "Safety scan skipped: SAFETY_API_KEY not set and infisical not available."; \
		echo "Set SAFETY_API_KEY or install infisical (brew install infisical)."; \
		echo "CI requires safety credentials -- set SAFETY_API_KEY secret in GitHub."; \
	fi
safety-gate:  ## Run safety scan in CI mode (fails if credentials unavailable)
	@if [ -n "$$SAFETY_API_KEY" ]; then \
		uv run python scripts/agent_check.py safety; \
	elif command -v infisical >/dev/null 2>&1; then \
		infisical run --env dev -- uv run python scripts/agent_check.py safety;  || true
			echo "Set SAFETY_API_KEY or configure infisical."; 
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
	$(MAKE) ci
	git add pyproject.toml uv.lock
	git commit -m "Release $(V)"
	git tag -a "v$(V)" -m "Release $(V)"
	git push origin master
	git push origin "v$(V)"

# ---------------------------------------------------------------------------
# Composite targets
# ---------------------------------------------------------------------------

.PHONY: check ci agent-check agent-check-push agent-check-no-tests

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

ifeq ($(CHECK_DEPTRY),true)
CHECK_PREREQS += deptry
endif

check: $(CHECK_PREREQS)  ## Run all static checks

agent-check:
	uv run python scripts/agent_check.py pre-commit

agent-check-no-tests:
	uv run python scripts/agent_check.py --no-tests pre-commit

agent-check-push:
	uv run python scripts/agent_check.py pre-push

ci:  ## Full CI pipeline
	$(MAKE) check
	$(MAKE) test-coverage
	$(MAKE) test-fuzz
	$(MAKE) safety-gate
	$(MAKE) pip-audit
	$(MAKE) sonar-reports
	$(MAKE) test-property-$(PROPERTY_PROFILE)
	$(MAKE) build
	$(MAKE) verify
	$(MAKE) smoke-test

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

.PHONY: file-size suppression-ratchet ruff-architecture typecheck-strict-ratchet semgrep-architecture quality-plan

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

quality-plan:  ## Run every analyser and write a full plan
	uv run python scripts/generate_quality_plan.py --out "$${OUT:-.claude/plans/quality-plan.md}"

plan-check:  ## Validate plan against prevention rules
	uv run python scripts/check_plan_compliance.py $${PLAN:+--plan $$PLAN}

ratchets: file-size suppression-ratchet ruff-architecture typecheck-strict-ratchet semgrep-architecture  ## Run all quality gates

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

quality-architecture: import-linter arch-check coupling-check  ## Run all architecture checks
