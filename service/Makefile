# market-service Makefile
#
# This package has no internal wheel dependencies — all dependencies are
# on PyPI.  uv run / uv sync do not need --find-links for this project.

PYTHON_VERSION := 3.12

.PHONY: init reinit test test-unit test-integration

# ==============================================================================
# Installation & Setup
# ==============================================================================

init: ## Resolve deps and create .venv.
	uv sync --dev --python $(PYTHON_VERSION)

reinit: ## Force-reinstall all packages (use after uv.lock changes).
	uv sync --dev --python $(PYTHON_VERSION) --reinstall

# ==============================================================================
# Testing
# ==============================================================================

test: test-unit test-integration ## Run all tests

test-unit: ## Run unit tests only
	uv run pytest tests/unit/ -v

test-integration: ## Run integration tests only (no external infrastructure required)
	uv run pytest tests/integration/ -v
