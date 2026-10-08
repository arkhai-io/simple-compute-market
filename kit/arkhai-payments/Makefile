# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: build init reinit test test-unit typecheck check-vectors check-generated generate-models

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: reinit ## Create or update the environment

reinit: ## Reinstall the local package environment
	python3 ../../scripts/uv_project.py reinit

test: reinit typecheck check-vectors check-generated test-unit ## Run every kit gate

test-unit: ## Run the unit suite
	uv run pytest tests -q

typecheck: ## Type-check the package and the local example
	uv run mypy src examples/local_e2e.py

check-vectors: ## Verify the published conformance vectors
	uv run python scripts/check_vectors.py

check-generated: ## Fail if the generated models differ from the published schemas
	uv run python scripts/generate_models.py --check

generate-models: ## Regenerate the models from the published schemas
	uv run python scripts/generate_models.py
