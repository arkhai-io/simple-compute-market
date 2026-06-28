DIST_DIR ?= ../../.dist

.PHONY: build test

build:
	uv build --wheel --out-dir $(DIST_DIR)

test:
	uv run --find-links $(DIST_DIR) pytest tests -q
