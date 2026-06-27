DIST_DIR ?= ../.dist

.PHONY: test test-core test-core-buyer test-core-site test-core-storefront test-core-storefront-client

test: test-core test-core-buyer test-core-site test-core-storefront test-core-storefront-client

test-core:
	uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-core-buyer:
	cd buyer && make test

test-core-site:
	cd site && uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-core-storefront:
	cd storefront && make test

test-core-storefront-client:
	cd storefront-client && uv run --find-links $(DIST_DIR) pytest tests -q
