.PHONY: test test-alkahest test-config test-identity test-policy dist dist-site dist-resource-pools

DIST_DIR ?= $(abspath ../.dist)

test: test-alkahest test-config test-identity test-policy

test-alkahest:
	cd alkahest && make test

test-config:
	cd config && make test

test-identity:
	cd identity && make test

test-policy:
	cd policy && make test

dist: dist-site dist-resource-pools

dist-site:
	-mkdir -p $(DIST_DIR)
	cd site && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_site-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-site produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-resource-pools:
	-mkdir -p $(DIST_DIR)
	cd resource-pools && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_resource_pools-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-resource-pools produced a platform-specific wheel — must build inside Docker" && exit 1)
