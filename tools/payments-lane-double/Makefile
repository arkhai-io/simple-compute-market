# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist
# The committed certificates. The leaf key the generator also writes is never
# committed (the secret gate refuses a private key block); the image builds it.
TLS_FILES := lane-ca.pem double.pem

.PHONY: build init reinit test test-unit check-tls tls

build: ## Build the double's wheel into dist/; its image builds from the repository root (make build-payments-lane-double there)
	uv build --wheel --out-dir dist

init: reinit ## Create or update the environment

reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../scripts/uv_project.py reinit

test: reinit check-tls test-unit ## Run every gate: the committed TLS files, then the unit and library integration suite

test-unit: ## Run the unit and library integration suite
	uv run --find-links $(DIST_DIR) pytest tests -q

# The generator's output is deterministic, so regenerating it must reproduce the
# committed files byte for byte; a difference means one was edited without the other.
check-tls: ## Fail unless tls/generate.py reproduces the committed certificates exactly
	@out=$$(mktemp -d) && trap 'rm -rf "$$out"' EXIT && \
	uv run --find-links $(DIST_DIR) python tls/generate.py "$$out" && \
	for file in $(TLS_FILES); do \
		cmp -s "$$out/$$file" "tls/$$file" || { \
			echo "tls/$$file differs from what tls/generate.py writes; run make tls and commit" >&2; \
			exit 1; }; \
	done

tls: ## Regenerate the committed certificates, and the uncommitted leaf key beside them for running the double outside its image
	uv run --find-links $(DIST_DIR) python tls/generate.py
