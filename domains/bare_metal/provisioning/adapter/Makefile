DIST_DIR ?= ../../../../.dist

.PHONY: reinit test

reinit: ## Reinstall internal dependencies resolved from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-storefront-client --reinstall-package arkhai-core-storefront-client \
		--upgrade-package arkhai-kit-config --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime \
		--upgrade-package arkhai-kit-site --reinstall-package arkhai-kit-site \
		--upgrade-package arkhai-vms --reinstall-package arkhai-vms \
		--upgrade-package arkhai-kit-capability-shape --reinstall-package arkhai-kit-capability-shape

test: reinit ## Run the bare-metal provisioning adapter tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
