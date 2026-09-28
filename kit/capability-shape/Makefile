# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Sync this environment from its lock
	python3 ../../scripts/uv_project.py reinit

init: reinit ## Create or update the environment

test: init ## Run the unit suite
	uv run pytest tests/unit -q
