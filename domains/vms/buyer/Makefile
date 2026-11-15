# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

REPO_ROOT := $(shell git rev-parse --show-toplevel)
DIST_DIR ?= ../../../.dist

.PHONY: init reinit test

init: reinit

reinit:
	python3 ../../../scripts/uv_project.py reinit

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests -q
