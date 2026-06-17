DIST_DIR ?= $(abspath $(CURDIR)/../../../.dist)

.PHONY: test

test:
	uv run --find-links $(DIST_DIR) pytest tests -q
