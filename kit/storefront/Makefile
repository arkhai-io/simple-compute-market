DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.12

.PHONY: build init reinit test

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit: ## Reinstall local package dependencies
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-core-storefront --reinstall-package arkhai-core-storefront \
		--upgrade-package arkhai-kit-alkahest --reinstall-package arkhai-kit-alkahest \
		--upgrade-package arkhai-core --reinstall-package arkhai-core \
		--upgrade-package arkhai-core-registry-client --reinstall-package arkhai-core-registry-client \
		--upgrade-package arkhai-kit-config --reinstall-package arkhai-kit-config \
		--upgrade-package arkhai-kit-identity --reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-policy --reinstall-package arkhai-kit-policy \
		--upgrade-package arkhai-kit-settlement-runtime --reinstall-package arkhai-kit-settlement-runtime

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
