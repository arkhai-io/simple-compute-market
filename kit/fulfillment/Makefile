# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: reinit ## Create or update the environment from repository-built wheels

reinit: ## Reinstall internal kit dependencies from the shared wheel directory
	python3 ../../scripts/uv_project.py reinit

test: reinit ## Run the test suite against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
