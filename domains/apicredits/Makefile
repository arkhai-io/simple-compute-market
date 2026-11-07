# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist

.PHONY: reinit test test-domain test-service test-storefront test-buyer test-sample-app test-middleware check-middleware-toolchains

test: test-domain test-service test-storefront test-buyer test-sample-app test-middleware

reinit: ## Force-reinstall internal wheels without bumping versions. Run make dist from the monorepo root first.
	python3 ../../scripts/uv_project.py reinit

test-domain: reinit ## Domain-package-level tests (distribution/wheel-import + credits client contract)
	uv run --find-links $(DIST_DIR) pytest tests -q

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
	@node -e 'const v=process.versions.node.split(".").map(Number); process.exit((v[0] > 22 || (v[0] === 22 && v[1] >= 6)) && ["strip", "transform"].includes(process.features.typescript) ? 0 : 1)' 2>/dev/null || { \
		echo "ERROR: API-credits TypeScript middleware tests require Node.js >= 22.6 with native TypeScript type stripping enabled."; \
		echo "Use a Node.js build with TypeScript support; a version check alone is insufficient."; \
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
	@cargo --version >/dev/null 2>&1 && rustc --version >/dev/null 2>&1 || { \
		echo "ERROR: a working Cargo and rustc toolchain is required for API-credits Rust middleware tests."; \
		echo "Canonical Ubuntu setup from the repository root:"; \
		echo "  cd ../.."; \
		echo "  sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run"; \
		echo "  ./scripts/bootstrap-clean-host-ubuntu.sh check"; \
		exit 1; \
	}
	@command -v cc >/dev/null 2>&1 || { \
		echo "ERROR: cc is required to compile and link API-credits Rust middleware tests."; \
		echo "On Ubuntu, install the native build tools: sudo apt-get install build-essential"; \
		exit 1; \
	}

test-middleware: check-middleware-toolchains
	cd middleware/python && make test
	cd middleware/typescript && npm install --no-audit --no-fund --silent && npm run check
	cd middleware/rust && cargo test
