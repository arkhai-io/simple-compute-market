DIST_DIR ?= ../../.dist

.PHONY: build reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-capability-shape --reinstall-package arkhai-kit-capability-shape

test: reinit ## Run the test suite against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
