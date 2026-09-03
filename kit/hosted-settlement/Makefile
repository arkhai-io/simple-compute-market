DIST_DIR ?= ../../.dist
PYTHON_VERSION ?= 3.13
HOSTED_REPO_ROOT := ../..
HOSTED_RELEASE_DIR ?= $(DIST_DIR)
include $(HOSTED_REPO_ROOT)/make/hosted-release.mk

.PHONY: build init reinit test verify-hosted-release

verify-hosted-release:
	$(VERIFY_HOSTED_RELEASE)

# The hosted client is an ordinary external dependency, resolved from an index
# like any other. Verification of the producer's signed release is a
# publication-time concern and gates nothing here: a signed release describes a
# deployed authority, and nothing below deploys one.
build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

init: ## Create or update the environment
	uv venv --allow-existing --python $(PYTHON_VERSION)
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR)

reinit: ## Reinstall the local package environment
	uv sync --dev --python $(PYTHON_VERSION) --find-links $(DIST_DIR) \
		--upgrade-package arkhai-hosted-settlement-client \
		--reinstall-package arkhai-hosted-settlement-client \
		--upgrade-package arkhai-kit-identity \
		--reinstall-package arkhai-kit-identity \
		--upgrade-package arkhai-kit-settlement-runtime \
		--reinstall-package arkhai-kit-settlement-runtime

test: reinit ## Run the focused unit suite
	uv run pytest tests/unit -q
