# Path to the monorepo .dist/ wheel directory, relative to core/storefront/.
# Used by uv when resolving pure-Python internal packages distributed as wheels.
# The rule is: no [tool.uv.sources] path entries with ../ in this file; all
# cross-package internal dependencies resolve exclusively from .dist/ wheels
# via --find-links on the CLI.
# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: init reinit test

init: reinit

# Refresh every internal wheel this project's lock installs; the set is derived
# from the lock. Run `make dist` from the repository root first so .dist/ holds
# fresh wheels.
reinit:
	python3 ../../scripts/uv_project.py reinit

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests/unit tests/integration -q
