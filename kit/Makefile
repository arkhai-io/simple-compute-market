.PHONY: test test-alkahest test-config test-identity test-policy test-site test-site-client test-resource-pools test-fulfillment test-settlement-runtime test-hosted-settlement dist dist-site dist-site-client dist-resource-pools dist-fulfillment dist-settlement-runtime dist-hosted-settlement

DIST_DIR ?= ../.dist

test: dist test-alkahest test-config test-identity test-policy test-site test-site-client test-resource-pools test-fulfillment test-settlement-runtime test-hosted-settlement

test-alkahest:
	cd alkahest && $(MAKE) test

test-config:
	cd config && $(MAKE) test

test-identity:
	cd identity && $(MAKE) test

test-policy:
	cd policy && $(MAKE) test

test-site:
	cd site && $(MAKE) test

test-site-client:
	cd site-client && $(MAKE) test

test-resource-pools:
	cd resource-pools && $(MAKE) test

test-fulfillment:
	cd fulfillment && $(MAKE) test

test-settlement-runtime:
	cd settlement-runtime && $(MAKE) test

test-hosted-settlement:
	cd hosted-settlement && $(MAKE) test

dist: dist-site dist-site-client dist-resource-pools dist-fulfillment dist-settlement-runtime dist-hosted-settlement

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

dist-resource-pools:
	-mkdir -p $(DIST_DIR)
	cd resource-pools && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_resource_pools-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-resource-pools produced a platform-specific wheel — must build inside Docker" && exit 1)

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

dist-hosted-settlement:
	-mkdir -p $(DIST_DIR)
	cd hosted-settlement && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_hosted_settlement-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-hosted-settlement produced a platform-specific wheel" && exit 1)
