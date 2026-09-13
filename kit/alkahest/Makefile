DIST_DIR ?= ../../.dist

.PHONY: build reinit test test-unit test-integration

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Refresh changed internal settlement dependencies.
	uv sync --locked --dev --find-links $(DIST_DIR) \
		--reinstall-package arkhai-core \
		--reinstall-package arkhai-kit-settlement-runtime

test: test-unit ## Run the default test suite

test-unit: reinit ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-integration: ## Run integration tests that may spawn local chain processes
	uv run --find-links $(DIST_DIR) pytest tests/integration -q
