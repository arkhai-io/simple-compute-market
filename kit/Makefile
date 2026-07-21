.PHONY: test test-alkahest test-config test-identity test-policy test-physical-settlement dist dist-site dist-resource-pools dist-physical-settlement

DIST_DIR ?= $(abspath ../.dist)

# NOTE: this aggregate target has never run kit/site's or
# kit/resource-pools' own test suites (pre-existing, not introduced by
# this change) -- test-physical-settlement is added as a standalone
# target for the same reason, matching that existing convention rather
# than silently changing it. Flagged for a future cleanup pass.
test: test-alkahest test-config test-identity test-policy

test-alkahest:
	cd alkahest && make test

test-config:
	cd config && make test

test-identity:
	cd identity && make test

test-policy:
	cd policy && make test

test-physical-settlement:
	cd physical-settlement && make test

dist: dist-site dist-resource-pools dist-physical-settlement

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

dist-physical-settlement: dist-site dist-resource-pools
	-mkdir -p $(DIST_DIR)
	cd physical-settlement && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_physical_settlement-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-physical-settlement produced a platform-specific wheel — must build inside Docker" && exit 1)
