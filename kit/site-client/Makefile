# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init reinit test

init: reinit

reinit: ## Refresh the pinned same-version identity wheel during local iteration
	python3 ../../scripts/uv_project.py reinit

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: reinit ## Run the test suite against freshly rebuilt internal wheels
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
