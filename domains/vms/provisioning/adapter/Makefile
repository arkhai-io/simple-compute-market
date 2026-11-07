# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../../.python-version 2>/dev/null),$(error ../../../../.python-version not found))

DIST_DIR ?= ../../../../.dist

.PHONY: reinit test

reinit:
	python3 ../../../../scripts/uv_project.py reinit

test: reinit
	uv run --find-links $(DIST_DIR) pytest tests ../../../../provisioning/compute/service/tests/unit/services/test_vm_inventory_views.py -q
