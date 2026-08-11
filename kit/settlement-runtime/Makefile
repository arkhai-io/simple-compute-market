DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.13

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION)

reinit: ## Reinstall the local package environment
	uv sync --dev --python $(PYTHON_VERSION)

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
