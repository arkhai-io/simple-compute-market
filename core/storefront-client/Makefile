DIST_DIR ?= ../../.dist

.PHONY: build test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: ## Run the test suite
	uv run --with pytest --find-links $(DIST_DIR) python -m pytest tests -q
