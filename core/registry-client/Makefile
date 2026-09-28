# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit test typecheck

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Refresh released identity, core, and registry-client packages
	python3 ../../scripts/uv_project.py reinit

test: reinit ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

typecheck: reinit ## Run static type checks
	uv run mypy src
