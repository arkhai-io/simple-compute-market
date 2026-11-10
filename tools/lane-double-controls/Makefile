# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))

DIST_DIR ?= ../../.dist
# The committed certificates. The leaf keys the generator also writes are never
# committed (the secret gate refuses a private key block); each double's image
# builds its own.
TLS_FILES := lane-ca.pem payments-double.pem mediation-double.pem

.PHONY: build init reinit test test-unit typecheck check-tls tls

build: ## Build the controls wheel into the repository wheelhouse
	uv build --wheel --out-dir $(DIST_DIR)

init: reinit ## Create or update the environment

reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../scripts/uv_project.py reinit

test: reinit check-tls typecheck test-unit ## Run every gate: the committed TLS files, the type check, then the unit and integration suite

test-unit: ## Run the unit and integration suite
	uv run --find-links $(DIST_DIR) pytest tests -q

typecheck: ## Type-check the package
	uv run --find-links $(DIST_DIR) mypy src --strict

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

tls: ## Regenerate the committed certificates, and the uncommitted leaf keys beside them for running a double outside its image
	uv run --find-links $(DIST_DIR) python tls/generate.py
