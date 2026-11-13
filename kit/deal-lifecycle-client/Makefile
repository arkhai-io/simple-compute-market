export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../../build-constraints.txt)),$(error ../../build-constraints.txt not found))
DIST_DIR ?= ../../.dist
.PHONY: build reinit test
build:
	uv build --wheel --out-dir $(DIST_DIR)
reinit:
	python3 ../../scripts/uv_project.py reinit
test: reinit
	uv run --find-links $(DIST_DIR) pytest -q
