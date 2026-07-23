DIST_DIR ?= ../../.dist

.PHONY: build test typecheck

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

typecheck: ## Run static type checks
	uv run mypy src
