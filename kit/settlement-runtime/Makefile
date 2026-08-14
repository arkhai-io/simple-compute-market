DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.13

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit: ## Reinstall the local package environment
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
