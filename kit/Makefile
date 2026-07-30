.PHONY: test test-alkahest test-config test-identity test-policy test-site test-resource-pools test-fulfillment dist dist-site dist-resource-pools dist-fulfillment

DIST_DIR ?= ../.dist

test: dist test-alkahest test-config test-identity test-policy test-site test-resource-pools test-fulfillment

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

test-resource-pools:
	cd resource-pools && $(MAKE) test

test-fulfillment:
	cd fulfillment && $(MAKE) test

dist: dist-site dist-resource-pools dist-fulfillment

dist-site:
	-mkdir -p $(DIST_DIR)
	cd site && $(MAKE) build
	@ls $(DIST_DIR)/arkhai_kit_site-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-site produced a platform-specific wheel — must build inside Docker" && exit 1)

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
