# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

DIST_DIR ?= ../../../.dist

.PHONY: reinit test

reinit: ## Reinstall internal dependencies from the shared wheel directory
	python3 ../../../scripts/uv_project.py reinit

test: reinit ## Run the tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
