DIST_DIR ?= ../../.dist

.PHONY: reinit test

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-kit-fulfillment --reinstall-package arkhai-kit-fulfillment \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-resource-pools --reinstall-package arkhai-kit-resource-pools \
		--upgrade-package arkhai-kit-site --reinstall-package arkhai-kit-site \
		--upgrade-package arkhai-kit-capability-shape --reinstall-package arkhai-kit-capability-shape

test: reinit ## Run the tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
