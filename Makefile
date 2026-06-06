# =============================================================================
# Makefile -- single source of truth for all lint, test, and build commands.
#
# Used by GitHub Actions (.github/workflows/) and local git hooks
# (lefthook.yml).  Every check target is independently callable so that
# lefthook can attach glob triggers, while composite targets (check, ci)
# provide convenient one-command execution for CI and local use.
#
# Coverage threshold: pyproject.toml [tool.coverage.report] fail_under = 85
# Test markers:       pyproject.toml [tool.pytest.ini_options] addopts
# =============================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON_VERSION ?= 3.12

# ---------------------------------------------------------------------------
# Development setup
# ---------------------------------------------------------------------------

.PHONY: check-uv check-gitleaks setup

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

setup: check-uv check-gitleaks check-infisical  ## Set up a local development environment
	uv venv --python $(PYTHON_VERSION) --allow-existing
	uv sync --locked --extra dev --group dev
	uv run lefthook install
	uv run pxcli --help > /dev/null

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

typecheck-pyright:  ## Run type checker (pyright)
	uv run pyright src/

typecheck-all: typecheck typecheck-pyright  ## Run all type checkers

# ---------------------------------------------------------------------------
# Security and dead-code analysis
# ---------------------------------------------------------------------------

.PHONY: bandit vulture gitleaks security

bandit:  ## Run bandit security linter
	uvx --from bandit bandit -c pyproject.toml -r src/ -ll -ii

vulture:  ## Run vulture dead-code detector
	uv run vulture src/ vulture_whitelist.py --min-confidence 80

gitleaks:  ## Run gitleaks secret detection
	scripts/gitleaks_check.sh

security: bandit vulture  ## Run all security checks

# ---------------------------------------------------------------------------
# Complexity
# ---------------------------------------------------------------------------

.PHONY: complexity-cc complexity-mi complexity

complexity-cc:  ## Check cyclomatic complexity (radon)
	@output=$$(uv run radon cc src/ -s -n B) && \
	if [ -n "$$output" ]; then \
		echo "Cyclomatic complexity violations (B or worse):"; \
		echo "$$output"; \
		exit 1; \
	fi

complexity-mi:  ## Check maintainability index (radon)
	@output=$$(uv run radon mi src/ -s -n B) && \
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
		--severity ERROR --severity WARNING \
		--exclude-rule python.lang.maintainability.useless-innerfunction.useless-inner-function \
		--exclude tests/ \
		--error --metrics=off .

# ---------------------------------------------------------------------------
# Architecture enforcement
# ---------------------------------------------------------------------------

.PHONY: coupling-check metrics-track

coupling-check:  ## Measure coupling and stability metrics (Martin metrics)
	uv run python scripts/check_coupling.py

metrics-track:  ## Track CC and MI trends over recent git revisions
	uv run python scripts/track_metrics.py

.PHONY: mutate mutate-results mutate-module mutate-diff mutate-estimate mutate-browse

mutate:  ## Run mutation testing on the full source tree (hours — for CI/overnight)
	uv run mutmut run

mutate-estimate:  ## Estimate how long a full mutation run would take
	uv run mutmut print-time-estimates

mutate-module:  ## Run mutation testing on a specific module (usage: make mutate-module MODULE=api)
ifndef MODULE
	$(error MODULE is not set. Usage: make mutate-module MODULE=api)
endif
	uv run mutmut run src/perplexity_cli/$(MODULE)/

mutate-diff:  ## Run mutation testing on files changed vs base branch (for pre-push)
	@mapfile -t files < <(uv run python scripts/discover_mutate_diff_files.py); \
	if [ "$${#files[@]}" -eq 0 ]; then \
		echo "No source files changed — skipping mutation tests."; \
		exit 0; \
	fi; \
	echo "Mutating $${#files[@]} changed file(s):"; \
	printf '  %s\n' "$${files[@]}"; \
	uv run mutmut run "$${files[@]}"

mutate-results:  ## Show mutation testing results from last run
	uv run mutmut results

mutate-browse:  ## Browse mutation results in interactive TUI
	uv run mutmut browse

# ---------------------------------------------------------------------------
# Testing
#
# Marker exclusions (integration, real_api, manual, real_user_config, fuzz)
# are applied automatically via addopts in pyproject.toml.
# Coverage fail_under = 85 is set in pyproject.toml [tool.coverage.report].
# ---------------------------------------------------------------------------

.PHONY: test test-coverage test-fuzz test-property test-property-push test-property-ci

test:  ## Run tests without coverage (fail-fast)
	uv run pytest tests/ -q --tb=line -x

test-coverage:  ## Run tests with coverage enforcement
	uv run pytest tests/ -q --tb=line -x \
		--cov=perplexity_cli --cov-report=term-missing \
		--cov-report=json --cov-report=xml:coverage.xml
	uv run python scripts/check_module_coverage.py --min-coverage 85

test-fuzz:  ## Run fuzz tests
	uv run pytest tests/test_fuzz.py -q --tb=line -x -m fuzz

test-property:  ## Run property-based tests (fast — dev profile, 10 examples each)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=dev

test-property-push:  ## Run property-based tests (balanced — push profile, 50 examples each)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=push

test-property-ci:  ## Run property-based tests (thorough — CI profile, 1000 examples each)
	uv run pytest tests/test_property.py -v --tb=short --hypothesis-profile=ci

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

.PHONY: safety infisical-scan

safety:  ## Run safety dependency scan
	@if command -v infisical >/dev/null 2>&1; then \
		infisical run --env dev -- uv run python scripts/agent_check.py safety; \
	else \
		uv run python scripts/agent_check.py safety; \
	fi

infisical-scan:  ## Scan uncommitted changes for secrets
	infisical scan git-changes --verbose --exit-code 1

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

release:  ## Bump version, lock, commit, tag, and push (usage: make release V=0.7.2)
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
#
# All static checks are listed as prerequisites of the `check` target so
# that `make -j check` runs them in parallel (~4s wall time instead of
# ~13s sequential).  Each prerequisite is independently callable via
# `make <target>` for use in lefthook with per-file globs.
# ---------------------------------------------------------------------------

.PHONY: check ci agent-check agent-check-push agent-check-no-tests

check: format-check lint typecheck-all security complexity semgrep arch-check coupling-check  ## Run all static checks (no tests)

agent-check:  ## Run all pre-commit analysers in parallel with unified output (for agents/CI)
	uv run python scripts/agent_check.py pre-commit

agent-check-no-tests:  ## Run pre-commit analysers excluding tests (for pre-push)
	uv run python scripts/agent_check.py --no-tests pre-commit

agent-check-push:  ## Run all pre-push analysers in parallel with unified output (for agents/CI)
	uv run python scripts/agent_check.py pre-push

ci:  ## Full CI pipeline
	$(MAKE) check
	$(MAKE) test-coverage
	$(MAKE) test-fuzz
	$(MAKE) safety
	$(MAKE) sonar-reports
	$(MAKE) test-property-ci
	$(MAKE) build
	$(MAKE) verify
	$(MAKE) smoke-test

# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

.PHONY: arch-check arch-explain

arch-check:  ## Check architecture layer boundaries and import direction
	uv run python scripts/check_architecture.py

arch-explain:  ## Display the architecture layer model
	uv run python scripts/check_architecture.py --explain

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
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
