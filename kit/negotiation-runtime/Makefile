# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: reinit ## Create or update the environment

reinit: ## Reinstall kit dependencies from the shared wheelhouse
	python3 ../../scripts/uv_project.py reinit

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
