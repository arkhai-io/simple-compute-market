DIST_DIR ?= ../../../.dist

.PHONY: reinit test

reinit: ## Reinstall internal dependencies from the shared wheel directory
	uv sync --dev --find-links $(DIST_DIR) \
		--upgrade-package arkhai-bare-metal --reinstall-package arkhai-bare-metal \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-buyer --reinstall-package arkhai-core-buyer \
		--upgrade-package arkhai-core-registry-client --reinstall-package arkhai-core-registry-client \
		--upgrade-package arkhai-kit-alkahest --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-kit-config --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-contact-exchange --reinstall-package arkhai-kit-contact-exchange \
		--upgrade-package arkhai-kit-delivery --reinstall-package arkhai-kit-delivery \
		--upgrade-package arkhai-kit-hosted-settlement --reinstall-package arkhai-kit-hosted-settlement \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-policy --reinstall-package arkhai-kit-policy \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime \
		--upgrade-package arkhai-kit-capability-shape --reinstall-package arkhai-kit-capability-shape \
		--upgrade-package arkhai-compute --reinstall-package arkhai-compute

test: reinit ## Run the bare-metal buyer tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q
