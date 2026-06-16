.PHONY: help install test serve build clean

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

DIST_DIR ?= $(abspath $(CURDIR)/../../../.dist)

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev --find-links $(DIST_DIR)

test: ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

serve: ## Run the storefront locally
	uv run --find-links $(DIST_DIR) apitokens-storefront serve

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
