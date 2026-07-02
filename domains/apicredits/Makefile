DIST_DIR ?= ../../.dist

.PHONY: test test-service test-storefront test-buyer test-sample-app test-middleware check-middleware-toolchains

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
check-middleware-toolchains:
	@node -e 'const v=process.versions.node.split(".").map(Number); if (v[0] < 22 || (v[0] === 22 && v[1] < 6)) { process.exit(1); }' 2>/dev/null || { \
		echo "ERROR: API-tokens TypeScript middleware tests require Node.js >= 22.6."; \
		echo "Canonical Ubuntu setup from the repository root:"; \
		echo "  cd ../.."; \
		echo "  sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run"; \
		echo "  ./scripts/bootstrap-clean-host-ubuntu.sh check"; \
		exit 1; \
	}
	@command -v npm >/dev/null 2>&1 || { \
		echo "ERROR: npm is required for API-tokens TypeScript middleware tests."; \
		echo "Canonical Ubuntu setup from the repository root:"; \
		echo "  cd ../.."; \
		echo "  sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run"; \
		echo "  ./scripts/bootstrap-clean-host-ubuntu.sh check"; \
		exit 1; \
	}
	@command -v cargo >/dev/null 2>&1 || { \
		echo "ERROR: cargo is required for API-tokens Rust middleware tests."; \
		echo "Canonical Ubuntu setup from the repository root:"; \
		echo "  cd ../.."; \
		echo "  sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run"; \
		echo "  ./scripts/bootstrap-clean-host-ubuntu.sh check"; \
		exit 1; \
	}

test-middleware: check-middleware-toolchains
	cd middleware/python && make test
	cd middleware/typescript && npm install --no-audit --no-fund --silent && npm run check
	cd middleware/rust && cargo test
