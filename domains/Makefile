# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../.python-version 2>/dev/null),$(error ../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../build-constraints.txt)),$(error ../build-constraints.txt not found))

.PHONY: test dist dist-release dist-compute dist-compute-delivery dist-vms dist-vms-listings dist-vms-negotiation dist-vms-settlement dist-bare-metal dist-bare-metal-buyer \
	dist-bare-metal-storefront dist-storefront dist-provisioning-operator-client dist-provisioning-adapters \
	dist-apicredits-domain dist-apicredits-service dist-apicredits-storefront \
	dist-apicredits-sample-app dist-apicredits-buyer \
	dist-inference-domain dist-inference-service dist-inference-storefront dist-inference-buyer dist-inference-gateway dist-buyer test-provisioning-iac test-provisioning-adapter test-storefront \
	test-bare-metal test-compute test-compute-delivery test-vms-domain test-vms-buyer test-apicredits test-inference test-inference-service test-inference-storefront test-inference-buyer test-inference-gateway-service \
	dist-api dist-api-contracts dist-api-client dist-api-authority dist-api-selling dist-api-selling-alkahest dist-api-selling-arkhai-payments dist-api-buying dist-api-buying-alkahest dist-api-buying-arkhai-payments dist-api-gate dist-api-gateway test-api test-api-client test-api-authority test-api-selling test-api-selling-alkahest test-api-selling-arkhai-payments test-api-buying test-api-buying-alkahest test-api-buying-arkhai-payments test-api-gate test-api-gateway

DIST_DIR ?= $(abspath ../.dist)


# The domains' part of the release set: every domains-scoped wheel but the API-credit
# sample app, the demo API the end-to-end harness drives, which no operator installs.
dist-release: dist-compute dist-compute-delivery dist-vms dist-vms-listings dist-vms-negotiation dist-vms-settlement dist-bare-metal dist-bare-metal-buyer dist-bare-metal-storefront \
	dist-storefront dist-provisioning-operator-client dist-provisioning-adapters \
	dist-api dist-api-contracts dist-api-client dist-api-authority dist-api-selling dist-api-selling-alkahest dist-api-selling-arkhai-payments dist-api-buying dist-api-buying-alkahest dist-api-buying-arkhai-payments dist-api-gate dist-api-gateway \
	dist-apicredits-domain dist-apicredits-service dist-apicredits-storefront \
	dist-apicredits-buyer \
	dist-inference-domain dist-inference-service dist-inference-storefront dist-inference-buyer dist-inference-gateway \
	dist-buyer ## Build every domains-scoped wheel the release set carries

dist: dist-release dist-apicredits-sample-app ## Build every domains-scoped wheel

test: test-storefront test-bare-metal test-compute test-compute-delivery test-vms-domain test-vms-buyer test-api test-apicredits test-inference test-provisioning-adapter test-provisioning-iac

# ---------------------------------------------------------------------------
# Dist -- leaf wheel-build recipes for domains/-scoped packages, mirroring
# kit/Makefile's existing delegation pattern. Cross-directory prerequisites
# (e.g. kit/ wheels, provisioning/compute's wheel) are NOT expressed here --
# this Makefile has no business knowing about siblings outside domains/;
# they are declared on the root Makefile's `dist-domains` aggregate, which
# builds them before invoking this directory's `dist-release` target; the root
# `dist-apicredits-sample-app` invokes that leaf alone, as it needs no sibling's
# wheel to build. Only prerequisites between two targets both defined in this
# file are expressed here.
# ---------------------------------------------------------------------------

# The compute-family vocabulary every compute domain binds; built first so a
# consumer syncing against .dist finds it beside the domains that depend on it.
dist-compute: ## Build arkhai-compute wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd compute && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute produced a platform-specific wheel -- must build inside Docker" && exit 1)

# The compute family's delivery library: the delivery order behind domain ports.
dist-compute-delivery: ## Build arkhai-compute-delivery wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd compute/delivery && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_delivery-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-delivery produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-vms: dist-compute ## Build arkhai-vms wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/domain && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms produced a platform-specific wheel -- must build inside Docker" && exit 1)

# The VM listing, negotiation, and settlement modules are each one wheel,
# mapped from their own directory. Negotiation and settlement depend on
# listings; the storefront and buyer depend on all three.
dist-vms-listings: ## Build arkhai-vms-listings wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/listings && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_listings-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-listings produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-vms-negotiation: dist-vms-listings ## Build arkhai-vms-negotiation wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/negotiation && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_negotiation-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-negotiation produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-vms-settlement: dist-vms-listings ## Build arkhai-vms-settlement wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/settlement && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_settlement-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-settlement produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-bare-metal: dist-compute ## Build arkhai-bare-metal wheel into .dist/
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

dist-storefront: dist-vms dist-vms-listings dist-vms-negotiation dist-vms-settlement dist-bare-metal-storefront ## Build the combined compute-family storefront wheel into .dist/
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

dist-inference-domain: ## Build arkhai-inference-domain wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd inference && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_inference_domain-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-inference-domain produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-inference-service: dist-inference-domain ## Build arkhai-inference-service wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd inference/service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_inference_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-inference-service produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-inference-storefront: dist-inference-domain ## Build arkhai-inference-storefront wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd inference/storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_inference_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-inference-storefront produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-inference-buyer: dist-inference-domain ## Build arkhai-inference-buyer wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd inference/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_inference_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-inference-buyer produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-inference-gateway: dist-inference-domain ## Build arkhai-inference-gateway-service wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd inference/gateway-service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_inference_gateway_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-inference-gateway-service produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-buyer: dist-vms-listings dist-vms-negotiation dist-vms-settlement ## Build arkhai-vms-buyer (the VM buyer domain of the `market` CLI) wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd vms/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_vms_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-vms-buyer produced a platform-specific wheel -- must build inside Docker" && exit 1)

# The api family's wheels: its vocabulary, contracts, client, authority, selling and
# buying libraries, gate, and gateway.
dist-api: ## Build arkhai-api wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-contracts: dist-api ## Build arkhai-api-contracts wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/contracts && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_contracts-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-contracts produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-client: dist-api-contracts ## Build arkhai-api-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/client && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-client produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-authority: dist-api-contracts ## Build arkhai-api-authority wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/authority && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_authority-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-authority produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling: dist-api-client ## Build arkhai-api-selling wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/selling && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_selling-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling-alkahest: dist-api-selling ## Build arkhai-api-selling-alkahest wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/selling-alkahest && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_selling_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling-alkahest produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling-arkhai-payments: dist-api-selling ## Build arkhai-api-selling-arkhai-payments wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/selling-arkhai-payments && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_selling_arkhai_payments-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling-arkhai-payments produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying: dist-api ## Build arkhai-api-buying wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/buying && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_buying-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying-alkahest: dist-api-buying ## Build arkhai-api-buying-alkahest wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/buying-alkahest && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_buying_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying-alkahest produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying-arkhai-payments: dist-api-buying ## Build arkhai-api-buying-arkhai-payments wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/buying-arkhai-payments && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_buying_arkhai_payments-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying-arkhai-payments produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-gate: ## Build arkhai-api-gate wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/gate && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_gate-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-gate produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-gateway: dist-api-gate ## Build arkhai-api-gateway wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd api/gateway && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_api_gateway-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-gateway produced a platform-specific wheel -- must build inside Docker" && exit 1)

# ---------------------------------------------------------------------------
# Test -- leaf test invocations for domains/-scoped packages. Same
# cross-directory-prerequisite rule as the dist targets above: none of
# these declare a dependency on anything outside domains/.
# ---------------------------------------------------------------------------

test-provisioning-iac: ## Ansible IaC shell-logic/contract tests (uv-managed, see vms/provisioning/iac/Makefile)
	cd vms/provisioning/iac && $(MAKE) test

test-storefront: ## Full storefront reinit + test
	cd vms/storefront && $(MAKE) reinit && $(MAKE) test

# Each subproject resolves the wheel directory from its own relative default:
# `uv sync` records the path it is given in the lockfile, so an absolute one
# would rewrite committed locks with the caller's filesystem layout.
test-bare-metal: test-bare-metal-iac ## Bare-metal domain, storefront, buyer, and provisioning adapter tests
	cd bare_metal && $(MAKE) test
	cd bare_metal/storefront && $(MAKE) test
	cd bare_metal/buyer && $(MAKE) test
	cd bare_metal/provisioning/adapter && $(MAKE) test

test-compute: ## Compute-family vocabulary package tests
	cd compute && $(MAKE) test

test-compute-delivery: ## Compute-family delivery library tests
	cd compute/delivery && $(MAKE) test

test-vms-domain: ## VM market-domain package tests
	cd vms/domain && $(MAKE) test

test-vms-buyer: ## Buyer CLI tests
	cd vms/buyer && $(MAKE) test

test-apicredits: ## Full apicredits domain test suite
	cd apicredits && $(MAKE) test

test-inference: ## Full inference domain test suite
	cd inference && $(MAKE) test

test-inference-service: ## Inference service tests: unit and application integration
	cd inference && $(MAKE) test-service

test-inference-storefront: ## Inference storefront tests: unit and application integration
	cd inference && $(MAKE) test-storefront

test-inference-buyer: ## Inference buyer plugin tests: unit
	cd inference && $(MAKE) test-buyer

test-inference-gateway-service: ## Inference gateway tests: unit and integration against the in-process authority
	cd inference && $(MAKE) test-gateway-service


test-provisioning-adapter: ## VM provisioning adapter tests against built wheels
	cd vms/provisioning/adapter && $(MAKE) test

.PHONY: test-bare-metal-iac
test-bare-metal-iac:
	cd bare_metal/provisioning/iac && $(MAKE) test

# The api family's tests: its vocabulary, contracts, client, authority, selling and
# buying libraries, gate and its ports, and gateway.
test-api: ## api-family vocabulary, contracts, client, authority, selling-side, buyer-side, gate and its ports, and gateway tests
	cd api && $(MAKE) test
	cd api/contracts && $(MAKE) test
	cd api/client && $(MAKE) test
	cd api/authority && $(MAKE) test
	cd api/selling && $(MAKE) test
	cd api/selling-alkahest && $(MAKE) test
	cd api/selling-arkhai-payments && $(MAKE) test
	cd api/buying && $(MAKE) test
	cd api/buying-alkahest && $(MAKE) test
	cd api/buying-arkhai-payments && $(MAKE) test
	cd api/gate && $(MAKE) test
	cd api/gateway && $(MAKE) test
	cd api && $(MAKE) test-middleware

test-api-client: ## api-family client tests
	cd api/client && $(MAKE) test

test-api-authority: ## api-family authority tests
	cd api/authority && $(MAKE) test

test-api-selling: ## api-family selling tests
	cd api/selling && $(MAKE) test

test-api-selling-alkahest: ## api-family selling-side Alkahest tests
	cd api/selling-alkahest && $(MAKE) test

test-api-selling-arkhai-payments: ## api-family selling-side Arkhai payments tests
	cd api/selling-arkhai-payments && $(MAKE) test

test-api-buying: ## api-family buying tests
	cd api/buying && $(MAKE) test

test-api-buying-alkahest: ## api-family buyer-side Alkahest tests
	cd api/buying-alkahest && $(MAKE) test

test-api-buying-arkhai-payments: ## api-family buyer-side Arkhai payments tests
	cd api/buying-arkhai-payments && $(MAKE) test

test-api-gate: ## api-family gate tests: unit, the conformance replay, and the contract parity
	cd api/gate && $(MAKE) test

test-api-gateway: ## api-family gateway tests: unit and the library's integration level
	cd api/gateway && $(MAKE) test
