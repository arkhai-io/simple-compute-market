DIST_DIR ?= ../../.dist

.PHONY: build test test-unit test-integration

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: test-unit ## Run the default test suite

test-unit: ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-integration: ## Run integration tests that may spawn local chain processes
	uv run --find-links $(DIST_DIR) pytest tests/integration -q
