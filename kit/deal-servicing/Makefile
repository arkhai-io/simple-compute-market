export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../../build-constraints.txt)),$(error ../../build-constraints.txt not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit first-use typecheck test

test: reinit
	uv run --find-links $(DIST_DIR) pytest -q

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
	uv run --find-links $(DIST_DIR) python examples/budget_first_use.py
	uv run --find-links $(DIST_DIR) python examples/respondent_first_use.py
	uv run --find-links $(DIST_DIR) python examples/receipt_first_use.py
