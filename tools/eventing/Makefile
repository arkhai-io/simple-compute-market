# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../../build-constraints.txt)),$(error ../../build-constraints.txt not found))

# The repository's `make dist` passes its wheelhouse; on its own the component
# builds into its own dist/.
DIST_DIR ?= dist

.PHONY: build test test-unit test-integration typecheck

build: ## Build the component's wheel into DIST_DIR, dist/ by default
	uv build --wheel --out-dir $(DIST_DIR)

test: typecheck test-unit test-integration ## Type-check the package, then run its unit and library-integration tests

test-unit: ## Run the unit tests, the structure test holding the component's boundary among them
	uv run pytest tests/unit -q

test-integration: ## Run the library-integration tests over real SQLite files: the schema steps, the recorder, consumers, pruning and the read service
	uv run pytest tests/integration -q

typecheck: ## Type-check the package
	uv run mypy src --strict
