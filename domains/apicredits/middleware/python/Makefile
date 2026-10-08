# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../../.python-version 2>/dev/null),$(error ../../../../.python-version not found))

DIST_DIR ?= ../../../../.dist

.PHONY: test reinit

reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../../../scripts/uv_project.py reinit

test: reinit
	uv run --find-links $(DIST_DIR) pytest -q
