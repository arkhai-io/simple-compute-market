DIST_DIR ?= ../../.dist

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment
	uv sync --dev --find-links $(DIST_DIR)

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-site-client --reinstall-package arkhai-kit-site-client

test: reinit ## Run the unit and library integration suites against current internal wheels
	uv run --find-links $(DIST_DIR) pytest
