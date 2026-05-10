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

.PHONY: bandit vulture security

bandit:  ## Run bandit security linter
	uvx --from bandit bandit -c pyproject.toml -r src/ -ll -ii

vulture:  ## Run vulture dead-code detector
	uv run vulture src/ vulture_whitelist.py --min-confidence 80

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
		--error --metrics=off .

# ---------------------------------------------------------------------------
# Testing
#
# Marker exclusions (integration, real_api, manual, real_user_config, fuzz)
# are applied automatically via addopts in pyproject.toml.
# Coverage fail_under = 85 is set in pyproject.toml [tool.coverage.report].
# ---------------------------------------------------------------------------

.PHONY: test test-coverage test-fuzz

test:  ## Run tests without coverage (fail-fast)
	uv run pytest tests/ -q --tb=line -x

test-coverage:  ## Run tests with coverage enforcement
	uv run pytest tests/ -q --tb=line -x \
		--cov=perplexity_cli --cov-report=term-missing \
		--cov-report=json --cov-report=xml:coverage.xml
	uv run python scripts/check_module_coverage.py --min-coverage 85

test-fuzz:  ## Run fuzz tests
	uv run pytest tests/test_fuzz.py -q --tb=line -x -m fuzz

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

.PHONY: safety

safety:  ## Run safety dependency scan
ifdef SAFETY_API_KEY
	uvx safety --key $(SAFETY_API_KEY) --stage cicd scan --target .
else
	uvx safety scan --target .
endif

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
# Composite targets
# ---------------------------------------------------------------------------

.PHONY: check ci

check:  ## Run all static checks (no tests)
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck-all
	$(MAKE) security
	$(MAKE) complexity
	$(MAKE) semgrep

ci:  ## Full CI pipeline
	$(MAKE) check
	$(MAKE) test-coverage
	$(MAKE) test-fuzz
	$(MAKE) safety
	$(MAKE) build
	$(MAKE) verify
	$(MAKE) smoke-test

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
