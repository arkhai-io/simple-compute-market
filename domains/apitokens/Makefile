DIST_DIR ?= $(abspath $(CURDIR)/../../.dist)

.PHONY: test test-service test-storefront test-buyer test-sample-app test-middleware

test: test-service test-storefront test-buyer test-sample-app test-middleware

test-service:
	cd service && make test

test-storefront:
	cd storefront && make test

test-buyer:
	cd buyer && make test

test-sample-app:
	cd sample-app && make test

# Cross-language middleware parity: all three implementations replay the
# shared conformance/session.json. Python is the reference; TS runs under
# Node's native type-stripping; Rust drives reqwest against an in-process
# axum mock. Each needs its own toolchain (uv / node+npm / cargo).
test-middleware:
	cd middleware/python && make test
	cd middleware/typescript && npm install --no-audit --no-fund --silent && npm run check
	cd middleware/rust && cargo test
