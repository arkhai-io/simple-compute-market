export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
DIST_DIR ?= ../../.dist

.PHONY: build reinit test check-contract check-generated generate-models typecheck demo
build:
	uv build --wheel --out-dir $(DIST_DIR)
reinit:
	python3 ../../scripts/uv_project.py reinit
test: reinit check-contract check-generated typecheck
	uv run --find-links $(DIST_DIR) pytest -q
check-contract:
	uv run python scripts/check_contract.py
check-generated:
	uv run python scripts/generate_models.py --check
generate-models:
	uv run python scripts/generate_models.py
typecheck:
	uv run mypy src examples --check-untyped-defs
demo: reinit
	uv run --find-links $(DIST_DIR) python examples/first_use.py
