export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit first-use typecheck

build:
	uv build --wheel --out-dir $(DIST_DIR)

reinit:
	python3 ../../scripts/uv_project.py reinit

typecheck: reinit
	uv run --find-links $(DIST_DIR) mypy src --check-untyped-defs

first-use: reinit
	uv run --find-links $(DIST_DIR) python examples/first_use.py
	uv run --find-links $(DIST_DIR) python examples/end_first_use.py
	uv run --find-links $(DIST_DIR) python examples/watch_first_use.py
	uv run --find-links $(DIST_DIR) python examples/seller_first_use.py
	uv run --find-links $(DIST_DIR) python examples/ingress_first_use.py
	uv run --find-links $(DIST_DIR) python examples/routes_first_use.py
