DIST_DIR ?= $(abspath $(CURDIR)/../.dist)

.PHONY: test test-alkahest test-config test-identity test-policy

test: test-alkahest test-config test-identity test-policy

test-alkahest:
	cd alkahest && uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-config:
	cd config && uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-identity:
	cd identity && uv run --find-links $(DIST_DIR) pytest tests/unit -q

test-policy:
	cd policy && uv run --find-links $(DIST_DIR) pytest tests -q
