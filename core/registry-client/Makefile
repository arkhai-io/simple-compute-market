DIST_DIR ?= ../../.dist

.PHONY: build reinit test typecheck

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Refresh released identity, core, and registry-client packages
	uv sync --dev --find-links $(DIST_DIR) --upgrade-package arkhai-core --reinstall-package arkhai-core --upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity --reinstall-package arkhai-core-registry-client

test: reinit ## Run the test suite
	uv run --find-links $(DIST_DIR) pytest tests -q

typecheck: reinit ## Run static type checks
	uv run mypy src
