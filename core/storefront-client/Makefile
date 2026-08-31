DIST_DIR ?= ../../.dist

.PHONY: build reinit test

reinit: ## Refresh pinned same-version wheels during local iteration
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--reinstall-package arkhai-core-storefront-client

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

test: reinit ## Run the test suite against freshly rebuilt internal wheels
	uv run --with pytest --find-links $(DIST_DIR) python -m pytest tests -q
