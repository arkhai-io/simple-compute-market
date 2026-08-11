.PHONY: help init reinit build test clean

.DEFAULT_GOAL := help

DIST_DIR ?= ../../../.dist

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

init: ## Install dependencies from public indexes and internal wheels
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev --find-links $(DIST_DIR)

reinit: ## Upgrade and reinstall changed internal wheel dependencies
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-bare-metal    --reinstall-package arkhai-bare-metal \
		--upgrade-package arkhai-core          --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-storefront --reinstall-package arkhai-core-storefront \
		--upgrade-package arkhai-kit-alkahest   --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-policy     --reinstall-package arkhai-kit-policy \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime

test: reinit ## Run the storefront package tests
	uv run --find-links $(DIST_DIR) pytest tests -q

build: ## Build the wheel into the shared .dist directory
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
