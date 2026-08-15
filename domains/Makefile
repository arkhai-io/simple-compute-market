.PHONY: dist dist-vms dist-bare-metal dist-bare-metal-buyer \
	dist-bare-metal-storefront dist-storefront dist-provisioning-operator-client dist-provisioning-adapters \
	dist-apicredits-domain dist-apicredits-service dist-apicredits-storefront \
	dist-apicredits-middleware dist-apicredits-sample-app dist-apicredits-buyer \
	dist-buyer test-provisioning-iac test-provisioning-adapter test-storefront \
	test-vms-buyer test-apicredits test-apicredits-middleware

DIST_DIR ?= $(abspath ../.dist)


dist: dist-vms dist-bare-metal dist-bare-metal-buyer dist-bare-metal-storefront \
	dist-storefront dist-provisioning-operator-client dist-provisioning-adapters \
	dist-apicredits-domain dist-apicredits-service dist-apicredits-storefront \
	dist-apicredits-middleware dist-apicredits-sample-app dist-apicredits-buyer \
	dist-buyer ## Build every domains-scoped wheel

# ---------------------------------------------------------------------------
# Dist -- leaf wheel-build recipes for domains/-scoped packages, mirroring
# kit/Makefile's existing delegation pattern. Cross-directory prerequisites
# (e.g. kit/ wheels, provisioning/compute's wheel) are NOT expressed here --
# this Makefile has no business knowing about siblings outside domains/;
# they stay declared on the root Makefile's own delegating targets, which
# call `$(MAKE) -C domains <target> DIST_DIR=$(DIST_DIR)` only once those
# prerequisites are already satisfied. Only prerequisites between two
# targets both defined in this file are expressed here.
# ---------------------------------------------------------------------------

dist-vms: ## Build arkhai-vms wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/domain && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-bare-metal: ## Build arkhai-bare-metal wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd bare_metal && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_bare_metal-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-bare-metal produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-bare-metal-buyer: dist-bare-metal ## Build the bare-metal buyer contribution wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd bare_metal/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_bare_metal_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-bare-metal-buyer produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-bare-metal-storefront: dist-bare-metal ## Build the bare-metal storefront contribution wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd bare_metal/storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_bare_metal_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-bare-metal-storefront produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-storefront: dist-vms dist-bare-metal-storefront ## Build the combined compute-family storefront wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-storefront produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-provisioning-operator-client: ## Build arkhai-vms-provisioning-operator-client wheel into .dist/ (needs arkhai-compute-provisioning -- see root Makefile)
	-mkdir -p $(DIST_DIR)
	cd vms/provisioning/client && uv build --wheel --out-dir $(DIST_DIR)

dist-provisioning-adapters: dist-bare-metal dist-provisioning-operator-client ## Build VM and bare-metal provisioning adapter wheels (also needs kit + arkhai-compute-provisioning -- see root Makefile)
	-mkdir -p $(DIST_DIR)
	cd vms/provisioning/adapter && uv build --wheel --out-dir $(DIST_DIR)
	cd bare_metal/provisioning/adapter && uv build --wheel --out-dir $(DIST_DIR)

dist-apicredits-domain: ## Build arkhai-apicredits-domain wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_domain-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-domain produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-apicredits-service: ## Build arkhai-apicredits-service wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits/service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-service produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-apicredits-storefront: dist-apicredits-domain ## Build arkhai-apicredits-storefront wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits/storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-storefront produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-apicredits-middleware: ## Build arkhai-apicredits-middleware wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits/middleware/python && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_middleware-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-middleware produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-apicredits-sample-app: ## Build arkhai-apicredits-sample-app wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits/sample-app && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_sample_app-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-sample-app produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-apicredits-buyer: dist-apicredits-domain ## Build arkhai-apicredits-buyer wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd apicredits/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_apicredits_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-apicredits-buyer produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-buyer: ## Build arkhai-vms-buyer (the `market` CLI) wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-buyer produced a platform-specific wheel -- must build inside Docker" && exit 1)

# ---------------------------------------------------------------------------
# Test -- leaf test invocations for domains/-scoped packages. Same
# cross-directory-prerequisite rule as the dist targets above: none of
# these declare a dependency on anything outside domains/.
# ---------------------------------------------------------------------------

test-provisioning-iac: ## Ansible IaC shell-logic/contract tests (uv-managed, see vms/provisioning/iac/Makefile)
	cd vms/provisioning/iac && $(MAKE) test

test-storefront: ## Full storefront reinit + test
	cd vms/storefront && $(MAKE) reinit && $(MAKE) test

test-vms-buyer: ## Buyer CLI tests
	cd vms/buyer && $(MAKE) test

test-apicredits: ## Full apicredits domain test suite
	cd apicredits && $(MAKE) test

# Compatibility alias for the cross-language middleware parity suite.
test-apicredits-middleware:
	cd apicredits && $(MAKE) test-middleware


test-provisioning-adapter: ## VM provisioning adapter tests against built wheels
	cd vms/provisioning/adapter && $(MAKE) test DIST_DIR=$(abspath $(DIST_DIR))
