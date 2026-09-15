.PHONY: help install reinit test serve build clean

.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

DIST_DIR ?= ../../../.dist

install: ## Install dependencies using uv
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install from https://docs.astral.sh/uv/"; exit 1; }
	uv sync --dev --find-links $(DIST_DIR)

reinit: ## Force-reinstall internal wheels without bumping versions. Run make dist-* from the monorepo root first.
# The two client packages are dev-only but are refreshed here for the same
# reason as the kits: they are built into $(DIST_DIR) without a version bump,
# so a cached same-version wheel would shadow fresh content and the
# boundary tests would prove yesterday's clients against today's authority.
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-site --reinstall-package arkhai-kit-site \
		--upgrade-package arkhai-kit-resource-pools --reinstall-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-apicredits-middleware --reinstall-package arkhai-apicredits-middleware \
		--upgrade-package arkhai-apicredits-domain --reinstall-package arkhai-apicredits-domain \
		--upgrade-package arkhai-kit-site-client --reinstall-package arkhai-kit-site-client

test: reinit ## Run the test suite
	PYTHONPATH=src uv run --find-links $(DIST_DIR) pytest tests -q

serve: ## Run the service locally (reload)
	PYTHONPATH=src uv run --find-links $(DIST_DIR) python src/main.py

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info
