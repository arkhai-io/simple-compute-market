.PHONY: test test-alkahest test-capability-shape test-capability-pricing test-capability-admissibility test-capacity-publication test-pool-overrides test-config test-contact-exchange test-delivery test-delivery-apprise test-identity test-policy test-site test-site-client test-resource-pools-contracts test-resource-pools test-resource-pools-client test-fulfillment test-settlement-runtime test-negotiation-runtime test-storefront dist dist-ci dist-capability-shape dist-capability-pricing dist-capability-admissibility dist-capacity-publication dist-pool-overrides dist-contact-exchange dist-delivery dist-delivery-apprise dist-site dist-site-client dist-resource-pools-contracts dist-resource-pools dist-resource-pools-client dist-fulfillment dist-settlement-runtime dist-negotiation-runtime dist-storefront test-arkhai-payments test-schema-migrations dist-schema-migrations

# Every uv command the api family's recipes run uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../.python-version 2>/dev/null),$(error ../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../build-constraints.txt)),$(error ../build-constraints.txt not found))

DIST_DIR ?= ../.dist
API_DIST_DIR = $(abspath $(DIST_DIR))

test: dist test-deal-servicing test-deal-lifecycle-client test-deal-lifecycle-buyer test-arkhai-mediation test-deal-lifecycle test-deal-lifecycle-contracts test-alkahest test-capability-shape test-capability-pricing test-capability-admissibility test-capacity-publication test-pool-overrides test-config test-contact-exchange test-delivery test-delivery-apprise test-identity test-policy test-site test-site-client test-resource-pools-contracts test-resource-pools test-resource-pools-client test-fulfillment test-settlement-runtime test-negotiation-runtime test-storefront test-arkhai-payments test-api test-schema-migrations

.PHONY: test-deal-servicing test-deal-lifecycle-client test-deal-lifecycle-buyer dist-deal-lifecycle-buyer

test-deal-servicing:
	cd deal-servicing && $(MAKE) test

test-deal-lifecycle-client:
	cd deal-lifecycle-client && $(MAKE) test

dist-deal-lifecycle-client: dist-deal-lifecycle-contracts
	cd deal-lifecycle-client && $(MAKE) build DIST_DIR=$(abspath $(DIST_DIR))

test-deal-lifecycle-buyer:
	cd deal-lifecycle-buyer && $(MAKE) test

dist-deal-lifecycle-buyer: dist-deal-lifecycle
	cd deal-lifecycle-buyer && $(MAKE) build

.PHONY: test-deal-lifecycle test-deal-lifecycle-contracts dist-deal-lifecycle dist-deal-lifecycle-contracts test-arkhai-mediation dist-arkhai-mediation

dist-deal-servicing: dist-deal-lifecycle
	cd deal-servicing && $(MAKE) build

.PHONY: dist-deal-servicing

test-arkhai-mediation:
	cd arkhai-mediation && $(MAKE) test

dist-arkhai-mediation: dist-deal-lifecycle
	cd arkhai-mediation && $(MAKE) build

test-deal-lifecycle:
	cd deal-lifecycle && $(MAKE) test

dist-deal-lifecycle: dist-deal-lifecycle-contracts
	-mkdir -p $(DIST_DIR)
	cd deal-lifecycle && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_deal_lifecycle-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: lifecycle produced a platform-specific wheel" && exit 1)

test-deal-lifecycle-contracts:
	cd deal-lifecycle-contracts && $(MAKE) test

dist-deal-lifecycle-contracts:
	-mkdir -p $(DIST_DIR)
	cd deal-lifecycle-contracts && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_deal_lifecycle_contracts-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: lifecycle contracts produced a platform-specific wheel" && exit 1)

test-alkahest:
	cd alkahest && $(MAKE) test

test-capacity-publication:
	cd capacity-publication && $(MAKE) test

test-config:
	cd config && $(MAKE) test

test-contact-exchange:
	cd contact-exchange && $(MAKE) test

test-capability-shape:
	cd capability-shape && $(MAKE) test

test-capability-pricing:
	cd capability-pricing && $(MAKE) test

test-capability-admissibility:
	cd capability-admissibility && $(MAKE) test

test-pool-overrides:
	cd pool-overrides && $(MAKE) test

test-delivery:
	cd delivery && $(MAKE) test

test-delivery-apprise:
	cd delivery-apprise && $(MAKE) test

test-identity:
	cd identity && $(MAKE) test

test-policy:
	cd policy && $(MAKE) test

test-site:
	cd site && $(MAKE) test

test-site-client:
	cd site-client && $(MAKE) test

test-resource-pools-contracts:
	cd resource-pools-contracts && $(MAKE) test

test-resource-pools:
	cd resource-pools && $(MAKE) test

test-resource-pools-client:
	cd resource-pools-client && $(MAKE) test

test-fulfillment:
	cd fulfillment && $(MAKE) test

test-settlement-runtime:
	cd settlement-runtime && $(MAKE) test

test-negotiation-runtime:
	cd negotiation-runtime && $(MAKE) test

test-storefront:
	cd storefront && $(MAKE) test

test-schema-migrations:
	cd schema-migrations && $(MAKE) test

dist: dist-ci

dist-ci: dist-api dist-api-contracts dist-api-client dist-api-authority dist-api-selling dist-api-selling-alkahest dist-api-selling-arkhai-payments dist-api-buying dist-api-buying-alkahest dist-api-buying-arkhai-payments dist-api-gate dist-api-gateway dist-deal-lifecycle-client dist-deal-lifecycle-buyer dist-deal-servicing dist-arkhai-mediation dist-deal-lifecycle dist-deal-lifecycle-contracts dist-capability-shape dist-capability-pricing dist-capability-admissibility dist-capacity-publication dist-pool-overrides dist-contact-exchange dist-delivery dist-delivery-apprise dist-site dist-site-client dist-resource-pools-contracts dist-resource-pools dist-resource-pools-client dist-fulfillment dist-settlement-runtime dist-negotiation-runtime dist-storefront dist-arkhai-payments dist-schema-migrations

dist-schema-migrations:
	-mkdir -p $(DIST_DIR)
	cd schema-migrations && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_schema_migrations-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-schema-migrations produced a platform-specific wheel" && exit 1)

dist-contact-exchange: dist-settlement-runtime
	-mkdir -p $(DIST_DIR)
	cd contact-exchange && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_contact_exchange-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-contact-exchange produced a platform-specific wheel" && exit 1)

dist-capability-shape:
	-mkdir -p $(DIST_DIR)
	cd capability-shape && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_capability_shape-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-capability-shape produced a platform-specific wheel" && exit 1)

dist-capability-pricing: dist-capability-shape
	-mkdir -p $(DIST_DIR)
	cd capability-pricing && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_capability_pricing-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-capability-pricing produced a platform-specific wheel" && exit 1)

dist-capability-admissibility: dist-capability-shape
	-mkdir -p $(DIST_DIR)
	cd capability-admissibility && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_capability_admissibility-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-capability-admissibility produced a platform-specific wheel" && exit 1)

dist-pool-overrides:
	-mkdir -p $(DIST_DIR)
	cd pool-overrides && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_pool_overrides-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-pool-overrides produced a platform-specific wheel" && exit 1)

dist-delivery:
	-mkdir -p $(DIST_DIR)
	cd delivery && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_delivery-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-delivery produced a platform-specific wheel" && exit 1)

dist-delivery-apprise: dist-delivery
	-mkdir -p $(DIST_DIR)
	cd delivery-apprise && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_delivery_apprise-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-delivery-apprise produced a platform-specific wheel" && exit 1)

dist-capacity-publication: dist-site-client
	-mkdir -p $(DIST_DIR)
	cd capacity-publication && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_capacity_publication-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-capacity-publication produced a platform-specific wheel" && exit 1)

dist-site:
	-mkdir -p $(DIST_DIR)
	cd site && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_site-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-site produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-site-client:
	-mkdir -p $(DIST_DIR)
	cd site-client && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_site_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-site-client produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-resource-pools-contracts: dist-capability-admissibility
	-mkdir -p $(DIST_DIR)
	cd resource-pools-contracts && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_resource_pools_contracts-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-resource-pools-contracts produced a platform-specific wheel" && exit 1)

dist-resource-pools: dist-resource-pools-contracts
	-mkdir -p $(DIST_DIR)
	cd resource-pools && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_resource_pools-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-resource-pools produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-resource-pools-client: dist-resource-pools-contracts
	-mkdir -p $(DIST_DIR)
	cd resource-pools-client && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_resource_pools_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-resource-pools-client produced a platform-specific wheel" && exit 1)

dist-fulfillment: dist-site dist-resource-pools
	-mkdir -p $(DIST_DIR)
	cd fulfillment && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_fulfillment-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-fulfillment produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-settlement-runtime:
	-mkdir -p $(DIST_DIR)
	cd settlement-runtime && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_settlement_runtime-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-settlement-runtime produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-negotiation-runtime:
	-mkdir -p $(DIST_DIR)
	cd negotiation-runtime && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_negotiation_runtime-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-negotiation-runtime produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-storefront:
	-mkdir -p $(DIST_DIR)
	cd storefront && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-storefront produced a platform-specific wheel — must build inside Docker" && exit 1)


test-arkhai-payments:
	cd arkhai-payments && $(MAKE) test

dist-arkhai-payments:
	-mkdir -p $(DIST_DIR)
	cd arkhai-payments && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_arkhai_payments-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-arkhai-payments produced a platform-specific wheel" && exit 1)

# The api family kit: its vocabulary, contracts, client, authority, selling and buying
# libraries, gate, and gateway. `test` above does not run it; `make test-api` does.
.PHONY: dist-api dist-api-contracts dist-api-client dist-api-authority dist-api-selling dist-api-selling-alkahest dist-api-selling-arkhai-payments dist-api-buying dist-api-buying-alkahest dist-api-buying-arkhai-payments dist-api-gate dist-api-gateway test-api test-api-client test-api-authority test-api-selling test-api-selling-alkahest test-api-selling-arkhai-payments test-api-buying test-api-buying-alkahest test-api-buying-arkhai-payments test-api-gate test-api-gateway

dist-api: ## Build arkhai-api wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-contracts: dist-api ## Build arkhai-api-contracts wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/contracts && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_contracts-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-contracts produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-client: dist-api-contracts ## Build arkhai-api-client wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/client && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-client produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-authority: dist-api-contracts ## Build arkhai-api-authority wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/authority && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_authority-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-authority produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling: dist-api-client ## Build arkhai-api-selling wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/selling && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_selling-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling-alkahest: dist-api-selling ## Build arkhai-api-selling-alkahest wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/selling-alkahest && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_selling_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling-alkahest produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-selling-arkhai-payments: dist-api-selling ## Build arkhai-api-selling-arkhai-payments wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/selling-arkhai-payments && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_selling_arkhai_payments-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-selling-arkhai-payments produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying: dist-api ## Build arkhai-api-buying wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/buying && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_buying-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying-alkahest: dist-api-buying ## Build arkhai-api-buying-alkahest wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/buying-alkahest && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_buying_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying-alkahest produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-buying-arkhai-payments: dist-api-buying ## Build arkhai-api-buying-arkhai-payments wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/buying-arkhai-payments && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_buying_arkhai_payments-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-buying-arkhai-payments produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-gate: ## Build arkhai-api-gate wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/gate && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_gate-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-gate produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-api-gateway: dist-api-gate ## Build arkhai-api-gateway wheel into .dist/
	-mkdir -p $(API_DIST_DIR)
	cd api/gateway && uv build --wheel --out-dir $(API_DIST_DIR)
	@ls $(API_DIST_DIR)/arkhai_api_gateway-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-api-gateway produced a platform-specific wheel -- must build inside Docker" && exit 1)

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
