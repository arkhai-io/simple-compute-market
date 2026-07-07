DIST_DIR ?= ../.dist

.PHONY: test test-core test-core-buyer test-core-site test-core-storefront test-core-storefront-client typecheck typecheck-core typecheck-core-registry-client

test: test-core test-core-buyer test-core-site test-core-storefront test-core-storefront-client

typecheck: typecheck-core typecheck-core-registry-client

test-core:
	uv run --find-links $(DIST_DIR) pytest tests/unit -q

typecheck-core:
	uv run mypy src

typecheck-core-registry-client:
	cd registry-client && make typecheck

test-core-buyer:
	cd buyer && make test

test-core-site:
	cd site && make test

test-core-storefront:
	cd storefront && make test

test-core-storefront-client:
	cd storefront-client && make test
