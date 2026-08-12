DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.13
HOSTED_RELEASE_TRUST ?= ../../manifests/hosted-settlement-v0.1.0-trust.json
HOSTED_RELEASE_MANIFEST ?= $(DIST_DIR)/release-manifest.json
HOSTED_CLIENT_WHEEL ?= $(DIST_DIR)/arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl
VERIFY_HOSTED_RELEASE = uv run --no-project --with 'eth-account>=0.13,<0.14' \
	python ../../scripts/verify-hosted-release.py \
	--trust $(HOSTED_RELEASE_TRUST) \
	--manifest $(HOSTED_RELEASE_MANIFEST) \
	--wheel $(HOSTED_CLIENT_WHEEL)

.PHONY: build init reinit test verify-hosted-release

verify-hosted-release:
	$(VERIFY_HOSTED_RELEASE)

build: verify-hosted-release ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: verify-hosted-release ## Create or update the environment
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit: verify-hosted-release ## Reinstall the local package environment
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-hosted-settlement-client \
		--reinstall-package arkhai-hosted-settlement-client \
		--upgrade-package arkhai-kit-identity \
		--reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-settlement-runtime \
		--reinstall-package arkhai-kit-settlement-runtime

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
