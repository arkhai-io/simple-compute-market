export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit first-use

build:
	uv build --wheel --out-dir $(DIST_DIR)

reinit:
	python3 ../../scripts/uv_project.py reinit

first-use: reinit
	uv run --find-links $(DIST_DIR) python examples/first_use.py
	uv run --find-links $(DIST_DIR) python examples/end_first_use.py
