# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init reinit test test-unit

build: ## Build the double's wheel into dist/; its image is built by tools/Makefile (make build-payments-lane-double there)
	uv build --wheel --out-dir dist

init: reinit ## Create or update the environment

reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../scripts/uv_project.py reinit

# The lane CA and the double's certificate are the controls project's, whose own
# make test holds them to their generator.
test: reinit test-unit ## Run every gate: the unit and application integration suite

test-unit: ## Run the unit and application integration suite
	uv run --find-links $(DIST_DIR) pytest tests -q
