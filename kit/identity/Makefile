# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../../build-constraints.txt)),$(error ../../build-constraints.txt not found))

DIST_DIR ?= ../../.dist

.PHONY: build test

build:
	uv build --wheel --out-dir $(DIST_DIR)

test:
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
