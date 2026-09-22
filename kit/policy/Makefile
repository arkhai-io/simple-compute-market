DIST_DIR ?= ../../.dist

.PHONY: build test reinit

build:
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity

test: reinit ## Run the tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest tests -q
