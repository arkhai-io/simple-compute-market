# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit test test-unit test-integration

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Refresh changed internal settlement dependencies.
	python3 ../../scripts/uv_project.py reinit

test: test-unit ## Run the default test suite

test-unit: reinit ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-integration: ## Run integration tests that may spawn local chain processes
	uv run --find-links $(DIST_DIR) pytest tests/integration -q
