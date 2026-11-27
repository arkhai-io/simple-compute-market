# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath ../../build-constraints.txt)),$(error ../../build-constraints.txt not found))

DIST_DIR ?= ../../.dist

.PHONY: build reinit test test-middleware check-middleware-toolchains

build: ## Build the wheel into the shared .dist/
	uv build --wheel --out-dir $(DIST_DIR)

reinit: ## Reinstall internal dependencies from the shared wheel directory
	python3 ../../scripts/uv_project.py reinit

test: reinit ## Run the api-family vocabulary tests against current internal wheels
	uv run --find-links $(DIST_DIR) pytest -q

# Cross-language gate parity: the TypeScript and Rust middlewares replay the
# shared conformance/session.json that the Python reference, the family gate,
# replays in `make test-api-gate`. TS runs under Node's native type-stripping;
# Rust drives reqwest against an in-process axum mock. Each needs its own
# toolchain (node+npm / cargo).
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
	cd gate-ports/typescript && npm install --no-audit --no-fund --silent && npm run check
	cd gate-ports/rust && cargo test
