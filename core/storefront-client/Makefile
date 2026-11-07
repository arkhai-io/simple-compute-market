# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit test

reinit: ## Refresh pinned same-version wheels during local iteration
	python3 ../../scripts/uv_project.py reinit

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: reinit ## Run the test suite against freshly rebuilt internal wheels
	uv run --with pytest --find-links $(DIST_DIR) python -m pytest tests -q
