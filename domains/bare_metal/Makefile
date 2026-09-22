DIST_DIR ?= ../../.dist

.PHONY: build test reinit

build:
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-registry-client --reinstall-package arkhai-core-registry-client \
		--upgrade-package arkhai-core-storefront --reinstall-package arkhai-core-storefront \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-policy --reinstall-package arkhai-kit-policy

test: reinit ## Run the bare-metal domain tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
