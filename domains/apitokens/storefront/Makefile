.PHONY: help init reinit test serve build clean

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

DIST_DIR ?= ../../../.dist

init: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev --find-links $(DIST_DIR)

reinit: ## Force-reinstall all internal wheel dependencies. Run make dist-* from the monorepo root first.
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core                 --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-storefront      --reinstall-package arkhai-core-storefront \
		--upgrade-package arkhai-core-registry-client --reinstall-package arkhai-core-registry-client \
		--upgrade-package arkhai-kit-alkahest         --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-config           --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-identity         --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-policy           --reinstall-package arkhai-kit-policy

test: reinit ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

serve: ## Run the storefront locally
	uv run --find-links $(DIST_DIR) apitokens-storefront serve

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
