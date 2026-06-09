GIT_SUFFIX := $(shell git rev-parse --short HEAD)
FOUNDRY_VERSION := v1.5.1
DIST_DIR := ${CURDIR}/.dist

.PHONY: build build-dev build-seller dist dist-storefront-client dist-storefront dist-policy dist-provisioning dist-registry dist-identity dist-core dist-alkahest dist-config dist-service dist-buyer dist-clean init init-prerequisites init-submodules init-zero-tier init-buyer init-storefront init-registry-service push-runtime-artifacts push-images push-dev-images push-helm push-wheels push-cli clobber-wheels

# ---------------------------------------------------------------------------
# Dist — build pure-Python wheels for internal packages before image builds.
#
# These wheels are placed in .dist/ (gitignored) and consumed by downstream
# Docker images via --find-links.  Only pure-Python packages (py3-none-any
# wheels) should be built here; packages with native extensions must be built
# inside the Docker build context.
#
# Upgrade path: replace --find-links with a PEP 503 index served from .dist/
# by running gen_simple_index.py and passing --index file://${PWD}/.dist/index
# to uv sync.  Further upgrade: publish .dist/ contents to GCP Artifact
# Registry and switch to --index https://...gar.../simple.
# ---------------------------------------------------------------------------
dist: dist-storefront-client dist-identity dist-core dist-alkahest dist-config dist-service dist-storefront dist-policy dist-provisioning dist-registry dist-buyer

dist-storefront-client: ## Build arkhai-storefront-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/storefront-client && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_storefront_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-storefront-client produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-storefront: ## Build market-storefront wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-storefront produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-policy: ## Build market-policy wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/policy && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_policy-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-policy produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-provisioning: ## Build provisioning-service wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd domains/vms/provisioning/service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/provisioning_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: provisioning-service produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-registry: ## Build arkhai-registry-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/registry-client && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_registry_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-registry-client produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-identity: ## Build market-identity wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/identity && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_identity-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-identity produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-core: ## Build market-core wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_core-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-core produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-alkahest: ## Build market-alkahest wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/alkahest && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-alkahest produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-config: ## Build market-config wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/config && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_config-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-config produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-service: ## Build market-service wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-service produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-buyer: ## Build market-buyer (the `market` CLI) wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd domains/vms/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/market_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: market-buyer produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-helm: ## Package helm chart so it's ready for pushing into .dist/
	helm package helm/ --destination $(DIST_DIR)

dist-clean: ## Remove .dist/ directory
	rm -rf $(DIST_DIR)

test: test-provisioning test-registry test-storefront

test-provisioning:
	cd domains/vms/provisioning/service && make reinit && make test

test-registry:
	cd core/registry && make reinit && make test

test-storefront:
	cd storefront && make reinit && make test

#Basic flow: build (optional), init (downloads if not built), run
# `build` produces the production artifacts: the three runtime images
# (registry, storefront, provisioning) and the buyer CLI binary. `build-dev`
# adds the test chain + integration-test image needed for the local e2e stack.
build: init-prerequisites dist build-buyer
	$(MAKE) -j3 build-registry build-storefront build-provisioning

build-dev: build build-test-env build-test-image

# Seller-only build: the two runtime images a seller actually needs
# (`arkhai:storefront`, `arkhai:provisioning`) and just the wheels they
# consume via --find-links. Skips `build-registry` (sellers point at
# someone else's registry).
build-seller: init-prerequisites dist-storefront-client dist-identity dist-core dist-alkahest dist-config dist-service dist-storefront dist-policy dist-provisioning dist-registry ## Build only what a seller needs: storefront + provisioning images.
	$(MAKE) -j2 build-storefront build-provisioning

# Same as build-seller, but the provisioning image's in-container appuser
# is built with the current host user's UID/GID. Required on hosts where
# the operator's UID isn't 1000 — otherwise the seller-provisioning
# container can't read mode-0600 SSH keys bind-mounted from the operator's
# home, and ansible falls over with `Permission denied (publickey)`.
build-seller-for-host: ## build-seller with appuser UID/GID matching the current user
	$(MAKE) build-seller APPUSER_UID=$(shell id -u) APPUSER_GID=$(shell id -g)

build-buyer: init-prerequisites init-buyer
	cd domains/vms/buyer && make build

# Regenerate the baked Anvil state + Alkahest address book by running
# EnvTestManager once and snapshotting its chain (see test-env/generate_state.py).
# Runs through the storefront venv, which pins alkahest_py; the relative
# --find-links keeps storefront/uv.lock paths portable.
build-anvil-state:
	cd storefront && uv run --find-links ../.dist python ../test-env/generate_state.py

build-test-env: build-anvil-state
	cd test-env && make build

build-registry:
	cd core/registry && make build

build-storefront:
	cd storefront && make build

build-provisioning:
	cd domains/vms/provisioning/service && make build

build-test-image:
	cd integration-tests && make build

#Init should complete all deployment times set up steps required prior to your standalone run statements
#The less of these the better but sometimes you get things like helm repo add or terraform init that can't be avoided.
# `make init` resolves dependencies for all three roles. Each role's
# Makefile owns its own venv; we just delegate so a fresh clone has one
# entry point. Run `make build` separately to produce wheel/Docker artifacts.
init: init-prerequisites init-submodules init-buyer init-storefront init-registry-service

init-prerequisites:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }

init-submodules:
	GIT_TRACE=1 GIT_CURL_TRACE=1 git submodule update --init

# ZeroTier overlay install (sudo). Standalone — run by whoever sets up the
# overlay network; not pulled into `build` so a default build needs no sudo.
init-zero-tier:
	cd scripts/zerotier && make install

init-buyer:
	cd domains/vms/buyer && make init

init-storefront: dist-service dist-policy dist-provisioning dist-storefront-client dist-registry
	cd storefront && make init

init-registry-service: dist-registry
	cd core/registry && make init

deploy-compose:
	docker compose up
	docker compose ps

# Top-level deploy: runs both Helm and docker-run deployments.
# Override SSH_KEY_FILE and HOSTS_INI as needed:
#   make deploy SSH_KEY_FILE=/path/to/key HOSTS_INI=/path/to/hosts
deploy: deploy-helm

IAC_DIR      ?= $(CURDIR)/compute-provisioning-iac
HOSTS_INI    ?= $(IAC_DIR)/ansible/inventory/hosts
SSH_KEY_FILE ?= $(HOME)/.ssh/id_ed25519

## Install or upgrade the Helm release.
## Requires a reachable cluster context (kubectl) and SSH_KEY_FILE.
## HOSTS_INI defaults to the IAC submodule inventory.
deploy-helm:
	$(MAKE) -C helm deploy \
		SSH_KEY_FILE=$(SSH_KEY_FILE) \
		EXTRA_SET_FILE_ARGS="--set-file provisioning.inventory.hostsIni=$(HOSTS_INI)"

## Docker-run based local deploy (legacy, still useful for local dev without k8s).
deploy-docker: deploy-test-env deploy-registry deploy-storefront deploy-provisioning

#docker run -it --rm -v ./test-env/state:/state arkhai:test-env-$(GIT_SUFFIX) anvil --load-state /state/state.json
deploy-test-env:
	cd test-env && make deploy

deploy-registry:
	cd core/registry && make deploy

deploy-storefront:
	cd storefront && make deploy

deploy-provisioning:
	cd domains/vms/provisioning/service && make deploy

test-deployment:
	cd integration-tests && make test

stop:
	docker ps -aq | xargs -r docker stop

#We're also going to want some targets built to idempotently smoke test a deployment
stop-compose:
	docker compose down
	docker compose rm

# ---------------------------------------------------------------------------
# Artifact Registry push configuration.
#
# AR_PROJECT is the only variable operators need to override when targeting
# a different environment. All four registry URLs are derived from it.
#
# Usage:
#   make push-runtime-artifacts                          # push to dev (default)
#   make push-runtime-artifacts AR_PROJECT=compute-market-1-preprod
#   make push-runtime-artifacts AR_PROJECT=compute-market-1-prod
#
# One-time machine setup before first push (covers Docker and Helm OCI):
#   gcloud auth configure-docker us-central1-docker.pkg.dev
# ---------------------------------------------------------------------------

AR_PROJECT  ?= compute-market-1-dev
AR_LOCATION ?= us-central1
AR_PREFIX   ?= $(AR_PROJECT)

DOCKER_REGISTRY := $(AR_LOCATION)-docker.pkg.dev/$(AR_PROJECT)/$(AR_PREFIX)-docker
HELM_REGISTRY   := oci://$(AR_LOCATION)-docker.pkg.dev/$(AR_PROJECT)/$(AR_PREFIX)-helm
PYTHON_REGISTRY := https://$(AR_LOCATION)-python.pkg.dev/$(AR_PROJECT)/$(AR_PREFIX)-python/

STOREFRONT_CLIENT_VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' core/storefront-client/pyproject.toml | head -1)
REGISTRY_CLIENT_VERSION   := $(shell sed -n 's/^version = "\(.*\)"/\1/p' core/registry-client/pyproject.toml | head -1)
PROVISIONING_VERSION      := $(shell sed -n 's/^version = "\(.*\)"/\1/p' domains/vms/provisioning/service/pyproject.toml | head -1)
# ---------------------------------------------------------------------------
# Push — publish built artifacts to Artifact Registry.
#
# Prerequisites:
#   make dist              — wheels must exist in .dist/
#   make build             — Docker images must be built locally
#   make build-dev         — additionally required before push-dev-images
#   make build-buyer       — domains/vms/buyer/dist/market binary must exist
#
# Targets can be run individually or all at once via push-runtime-artifacts.
# ---------------------------------------------------------------------------

_require-ar-project:
ifndef AR_PROJECT
	$(error AR_PROJECT is required. Usage: make <target> AR_PROJECT=<name>)
endif

define publish_python_wheel
	@if gcloud artifacts versions describe "$(2)" \
	  --project="$(AR_PROJECT)" \
	  --location="$(AR_LOCATION)" \
	  --repository="$(AR_PREFIX)-python" \
	  --package="$(1)" >/dev/null 2>&1; then \
		echo "Skipping $(1)==$(2): already exists in $(AR_PREFIX)-python"; \
	else \
		uv publish \
		  --publish-url "$(PYTHON_REGISTRY)" \
		  --username oauth2accesstoken \
		  --password "$$(gcloud auth print-access-token)" \
		  "$(3)"; \
	fi
endef

define clobber_python_wheel
	@if gcloud artifacts versions describe "$(2)" \
	  --project="$(AR_PROJECT)" \
	  --location="$(AR_LOCATION)" \
	  --repository="$(AR_PREFIX)-python" \
	  --package="$(1)" >/dev/null 2>&1; then \
		echo "Deleting $(1)==$(2) from $(AR_PREFIX)-python"; \
		gcloud artifacts versions delete "$(2)" \
		  --project="$(AR_PROJECT)" \
		  --location="$(AR_LOCATION)" \
		  --repository="$(AR_PREFIX)-python" \
		  --package="$(1)" \
		  --quiet; \
	else \
		echo "No existing $(1)==$(2) in $(AR_PREFIX)-python"; \
	fi; \
	uv publish \
	  --publish-url "$(PYTHON_REGISTRY)" \
	  --username oauth2accesstoken \
	  --password "$$(gcloud auth print-access-token)" \
	  "$(3)"
endef

define push_image
	docker tag arkhai:$(2)-$(GIT_SUFFIX) $(DOCKER_REGISTRY)/arkhai:$(1)-$(GIT_SUFFIX)
	docker tag arkhai:$(2)-$(GIT_SUFFIX) $(DOCKER_REGISTRY)/arkhai:$(1)
	docker push $(DOCKER_REGISTRY)/arkhai:$(1)-$(GIT_SUFFIX)
	docker push $(DOCKER_REGISTRY)/arkhai:$(1)
endef

push-runtime-artifacts: push-images push-charts push-wheels push-cli

push-images: _require-ar-project
	$(call push_image,registry,registry)
	$(call push_image,storefront,storefront)
	$(call push_image,provisioning,provisioning)

push-dev-images: _require-ar-project
	$(call push_image,test-env,test-env)
	$(call push_image,integration-tests,integration-tests)

push-charts: _require-ar-project dist-helm
	helm push $(DIST_DIR)/arkhai-node-operator-*.tgz $(HELM_REGISTRY)
	rm $(DIST_DIR)/arkhai-node-operator-*.tgz

push-wheels: _require-ar-project
	$(call publish_python_wheel,arkhai-storefront-client,$(STOREFRONT_CLIENT_VERSION),$(DIST_DIR)/arkhai_storefront_client-$(STOREFRONT_CLIENT_VERSION)-py3-none-any.whl)
	$(call publish_python_wheel,arkhai-registry-client,$(REGISTRY_CLIENT_VERSION),$(DIST_DIR)/arkhai_registry_client-$(REGISTRY_CLIENT_VERSION)-py3-none-any.whl)
	$(call publish_python_wheel,provisioning-service,$(PROVISIONING_VERSION),$(DIST_DIR)/provisioning_service-$(PROVISIONING_VERSION)-py3-none-any.whl)

push-cli: _require-ar-project
	gcloud artifacts generic upload \
	  --project=$(AR_PROJECT) \
	  --location=$(AR_LOCATION) \
	  --repository=$(AR_PREFIX)-cli \
	  --package=market \
	  --version=$(GIT_SUFFIX) \
	  --source=domains/vms/buyer/dist/market

clobber-wheels: _require-ar-project
	$(call clobber_python_wheel,arkhai-storefront-client,$(STOREFRONT_CLIENT_VERSION),$(DIST_DIR)/arkhai_storefront_client-$(STOREFRONT_CLIENT_VERSION)-py3-none-any.whl)
	$(call clobber_python_wheel,arkhai-registry-client,$(REGISTRY_CLIENT_VERSION),$(DIST_DIR)/arkhai_registry_client-$(REGISTRY_CLIENT_VERSION)-py3-none-any.whl)
	$(call clobber_python_wheel,provisioning-service,$(PROVISIONING_VERSION),$(DIST_DIR)/provisioning_service-$(PROVISIONING_VERSION)-py3-none-any.whl)

code-snapshot: ## Zip all git-tracked files for sharing (excludes gitignored artifacts).
	@mkdir -p .snapshot
	@OUTFILE="$(CURDIR)/.snapshot/code-$(GIT_SUFFIX).zip"; \
	echo "Creating $$OUTFILE ..."; \
	git ls-files --recurse-submodules | zip -@ "$$OUTFILE"; \
	SIZE=$$(du -sh "$$OUTFILE" | cut -f1); \
	echo "Done: $$OUTFILE ($$SIZE)"
