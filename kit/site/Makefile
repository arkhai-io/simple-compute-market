DIST_DIR ?= ../../.dist

.PHONY: build reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Reinstall internal kit dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-kit-identity \
		--reinstall-package arkhai-kit-resource-pools \
		--reinstall-package arkhai-kit-identity

test: reinit ## Run the test suite against current internal wheels
	uv run --find-links $(DIST_DIR) pytest tests/unit -q
