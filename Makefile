# PyPI intermittently serves 5xx where internal package names should
# 404 (they resolve from .dist); back off through the flap instead of
# failing after uv's default 3 tries.
export UV_HTTP_RETRIES ?= 10

GIT_SUFFIX := $(shell git rev-parse --short HEAD)
GIT_NAME   ?= simple-compute-market
FOUNDRY_VERSION := v1.5.1
DIST_DIR := ${CURDIR}/.dist
HOSTED_RELEASE_TRUST ?= manifests/hosted-settlement-v0.1.0-trust.json
HOSTED_RELEASE_MANIFEST ?= $(DIST_DIR)/release-manifest.json
HOSTED_CLIENT_WHEEL ?= $(DIST_DIR)/arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl
VERIFY_HOSTED_RELEASE = uv run --no-project --with 'eth-account>=0.13,<0.14' \
	python scripts/verify-hosted-release.py \
	--trust $(HOSTED_RELEASE_TRUST) \
	--manifest $(HOSTED_RELEASE_MANIFEST) \
	--wheel $(HOSTED_CLIENT_WHEEL)

.PHONY: review-wheelhouse review-wheelhouse-scope build build-dev build-seller build-apicredits-service build-apicredits-storefront build-apicredits-sample-app test test-core test-provisioning test-provisioning-iac test-registry test-storefront test-vms-buyer test-apicredits test-apicredits-middleware test-kits dist dist-storefront-client dist-policy dist-compute-provisioning dist-compute-provisioning-service dist-kits dist-hosted-client verify-hosted-release dist-registry-client dist-registry dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-alkahest dist-config dist-clean init init-prerequisites init-submodules init-zero-tier init-buyer init-storefront init-arkhai-core-registry push-runtime-artifacts push-images push-dev-images push-helm push-wheelhouse

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
dist: dist-storefront-client dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-hosted-client dist-kits dist-alkahest dist-config dist-policy dist-compute-provisioning dist-domains dist-compute-provisioning-service dist-registry-client

dist-domains: dist-kits dist-compute-provisioning ## Build every domains-scoped wheel through the domain aggregate
	cd domains && $(MAKE) dist DIST_DIR=$(DIST_DIR)

dist-storefront-client: ## Build arkhai-core-storefront-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/storefront-client && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_storefront_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-storefront-client produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-policy: ## Build arkhai-kit-policy wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/policy && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_policy-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-policy produced a platform-specific wheel -- must build inside Docker" && exit 1)

dist-compute-provisioning: dist-kits ## Build arkhai-compute-provisioning wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-provisioning produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-compute-provisioning-service: dist-kits dist-compute-provisioning dist-domains ## Build the extracted compute service wheel.
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute/service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: compute provisioning service produced a platform-specific wheel" && exit 1)

dist-registry-client: ## Build arkhai-core-registry-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/registry-client && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_registry_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-registry-client produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-registry: dist-registry-client ## Compatibility alias for dist-registry-client.

dist-identity: ## Build arkhai-kit-identity wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/identity && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_identity-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-identity produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-core: ## Build arkhai-core wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-arkhai-core-buyer: ## Build arkhai-core-buyer wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/buyer && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_buyer-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-buyer produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-arkhai-core-storefront: ## Build arkhai-core-storefront wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/storefront && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_storefront-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-storefront produced a platform-specific wheel — must build inside Docker" && exit 1)

verify-hosted-release: ## Verify the staged signed 0.1.0 release and exact client wheel.
	$(VERIFY_HOSTED_RELEASE)

dist-hosted-client: verify-hosted-release ## Consume only the verified staged client wheel.

dist-kits: dist-hosted-client ## Build kit-owned wheels into .dist/
	$(MAKE) -C kit dist DIST_DIR=$(DIST_DIR)

dist-alkahest: ## Build arkhai-kit-alkahest wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/alkahest && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_alkahest-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-alkahest produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-config: ## Build arkhai-kit-config wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/config && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_kit_config-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-kit-config produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-helm: ## Package helm chart so it's ready for pushing into .dist/
	helm package helm/ --destination $(DIST_DIR)

dist-clean: ## Remove .dist/ directory
	rm -rf $(DIST_DIR)

test: test-core test-kits test-provisioning test-provisioning-iac test-registry test-storefront test-vms-buyer test-apicredits

test-core:
	cd core && make test

test-provisioning:
	cd provisioning/compute/service && make test

test-provisioning-iac:
	$(MAKE) -C domains test-provisioning-iac

test-registry:
	cd core/registry && make reinit && make test

test-storefront:
	$(MAKE) -C domains test-storefront

test-vms-buyer:
	$(MAKE) -C domains test-vms-buyer

test-apicredits:
	$(MAKE) -C domains test-apicredits

# Compatibility alias for the cross-language middleware parity suite.
test-apicredits-middleware:
	$(MAKE) -C domains test-apicredits-middleware

test-kits:
	cd kit && make test

#Basic flow: build (optional), init (downloads if not built), run
# `build` produces the production artifacts: the three runtime images
# (registry, storefront, provisioning) and the buyer CLI binary. `build-dev`
# adds the test chain + integration-test image needed for the local e2e stack.
build: init-prerequisites dist build-buyer
	$(MAKE) -j3 build-registry build-storefront build-provisioning
	$(MAKE) -j3 build-apicredits-service build-apicredits-storefront build-apicredits-sample-app

build-dev: build build-dev-env build-test-image

# Seller-only build: the two runtime images a seller actually needs
# (`arkhai:storefront`, `arkhai:compute-provisioning`) and just the wheels they
# consume via --find-links. Skips `build-registry` (sellers point at
# someone else's registry).
build-seller: init-prerequisites dist-kits dist-storefront-client dist-identity dist-core dist-arkhai-core-storefront dist-alkahest dist-config dist-policy dist-compute-provisioning dist-domains dist-compute-provisioning-service dist-registry-client ## Build only what a seller needs: storefront + provisioning images.
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
# EnvTestManager once and snapshotting its chain (see dev-env/generate_state.py).
# Runs through the storefront venv, which pins alkahest_py; the relative
# --find-links keeps domains/vms/storefront/uv.lock paths portable.
build-anvil-state:
	cd domains/vms/storefront && uv run --find-links ../../../.dist python ../../../dev-env/generate_state.py

build-dev-env: build-anvil-state
	cd dev-env && make build

build-registry:
	cd core/registry && make build

build-storefront:
	cd domains/vms/storefront && make build

build-provisioning:
	cd provisioning/compute/service && make build

# API-credits domain images (item 6). Built from the repo root so each
# Dockerfile's `COPY .dist/` + `COPY domains/` resolve. The api-credits
# registry reuses arkhai:registry (built by build-registry) with a
# different filter-spec mounted at runtime.
build-apicredits-service:
	docker build --ulimit nofile=65536:65536 -f domains/apicredits/service/Dockerfile -t arkhai:apicredits-service .

build-apicredits-storefront:
	docker build --ulimit nofile=65536 -f domains/apicredits/storefront/Dockerfile -t arkhai:apicredits-storefront .

build-apicredits-sample-app:
	docker build --ulimit nofile=65536:65536 -f domains/apicredits/sample-app/Dockerfile -t arkhai:apicredits-sample-app .

build-test-image:
	cd e2e-tests && make build

#Init should complete all deployment times set up steps required prior to your standalone run statements
#The less of these the better but sometimes you get things like helm repo add or terraform init that can't be avoided.
# `make init` resolves dependencies for all three roles. Each role's
# Makefile owns its own venv; we just delegate so a fresh clone has one
# entry point. Run `make build` separately to produce wheel/Docker artifacts.
init: init-prerequisites init-submodules init-buyer init-storefront init-arkhai-core-registry

init-prerequisites:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }

init-submodules:
	GIT_TRACE=1 GIT_CURL_TRACE=1 git submodule update --init

# ZeroTier overlay install (sudo). Standalone — run by whoever sets up the
# overlay network; not pulled into `build` so a default build needs no sudo.
init-zero-tier:
	cd scripts/zerotier && make install

init-buyer: dist-domains
	cd domains/vms/buyer && make init

init-storefront: dist-domains dist-policy dist-compute-provisioning dist-storefront-client dist-registry-client
	cd domains/vms/storefront && make init

init-arkhai-core-registry: dist-registry-client
	cd core/registry && make init

deploy-compose:
	docker compose up
	docker compose ps

# Top-level deploy: runs both Helm and docker-run deployments.
# Override SSH_KEY_FILE and HOSTS_INI as needed:
#   make deploy SSH_KEY_FILE=/path/to/key HOSTS_INI=/path/to/hosts
deploy: deploy-helm

IAC_DIR      ?= $(CURDIR)/domains/vms/provisioning/iac
HOSTS_INI    ?= $(IAC_DIR)/ansible/inventory/hosts
SSH_KEY_FILE ?= $(HOME)/.ssh/id_ed25519

## Install or upgrade the Helm release.
## Requires a reachable cluster context (kubectl) and SSH_KEY_FILE.
## HOSTS_INI defaults to the IAC inventory.
deploy-helm:
	$(MAKE) -C helm deploy \
		SSH_KEY_FILE=$(SSH_KEY_FILE) \
		EXTRA_SET_FILE_ARGS="--set-file provisioning.inventory.hostsIni=$(HOSTS_INI)"

## Docker-run based local deploy (legacy, still useful for local dev without k8s).
deploy-docker: deploy-dev-env deploy-registry deploy-storefront deploy-provisioning

#docker run -it --rm -v ./dev-env/state:/state arkhai:dev-env-$(GIT_SUFFIX) anvil --load-state /state/state.json
deploy-dev-env:
	cd dev-env && make deploy

deploy-registry:
	cd core/registry && make deploy

deploy-storefront:
	cd domains/vms/storefront && make deploy

deploy-provisioning:
	cd provisioning/compute/service && make deploy

test-deployment:
	cd e2e-tests && make test

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
PROVISIONING_OPERATOR_CLIENT_VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' domains/vms/provisioning/client/pyproject.toml | head -1)
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
	$(call push_image,dev-env,dev-env)
	$(call push_image,e2e-tests,e2e-tests)

push-charts: _require-ar-project dist-helm
	helm push $(DIST_DIR)/arkhai-node-operator-*.tgz $(HELM_REGISTRY)
	rm $(DIST_DIR)/arkhai-node-operator-*.tgz

push-wheels: _require-ar-project
	$(call publish_python_wheel,arkhai-core-storefront-client,$(STOREFRONT_CLIENT_VERSION),$(DIST_DIR)/arkhai_core_storefront_client-$(STOREFRONT_CLIENT_VERSION)-py3-none-any.whl)
	$(call publish_python_wheel,arkhai-core-registry-client,$(REGISTRY_CLIENT_VERSION),$(DIST_DIR)/arkhai_core_registry_client-$(REGISTRY_CLIENT_VERSION)-py3-none-any.whl)
	$(call publish_python_wheel,arkhai-vms-provisioning-operator-client,$(PROVISIONING_OPERATOR_CLIENT_VERSION),$(DIST_DIR)/arkhai_vms_provisioning_operator_client-$(PROVISIONING_OPERATOR_CLIENT_VERSION)-py3-none-any.whl)

push-cli: _require-ar-project
	gcloud artifacts generic upload \
	  --project=$(AR_PROJECT) \
	  --location=$(AR_LOCATION) \
	  --repository=$(AR_PREFIX)-cli \
	  --package=market \
	  --version=$(GIT_SUFFIX) \
	  --source=domains/vms/buyer/dist/market

clobber-wheels: _require-ar-project
	$(call clobber_python_wheel,arkhai-core-storefront-client,$(STOREFRONT_CLIENT_VERSION),$(DIST_DIR)/arkhai_core_storefront_client-$(STOREFRONT_CLIENT_VERSION)-py3-none-any.whl)
	$(call clobber_python_wheel,arkhai-core-registry-client,$(REGISTRY_CLIENT_VERSION),$(DIST_DIR)/arkhai_core_registry_client-$(REGISTRY_CLIENT_VERSION)-py3-none-any.whl)
	$(call clobber_python_wheel,arkhai-vms-provisioning-operator-client,$(PROVISIONING_OPERATOR_CLIENT_VERSION),$(DIST_DIR)/arkhai_vms_provisioning_operator_client-$(PROVISIONING_OPERATOR_CLIENT_VERSION)-py3-none-any.whl)

# Reviw and agent targets

# ---------------------------------------------------------------------------
# check-comment-hygiene — mechanical sweep for AGENTS.md's "Python comments
# and docstrings" rule: change IDs, section/task numbers, and change-document
# filenames must never appear in comments or docstrings outside openspec/.
# This catches the reliably-mechanical subset of that rule (not the fuzzier
# "references the review that introduced the code" cases, which still need
# a human/LLM read) and is meant to run as part of every plan's closeout
# task, not only when someone remembers to ask. Deliberately does not match
# a bare "tombstone" -- that word has a legitimate, unrelated meaning
# (a soft-delete marker row) already in use in this codebase, and a regex
# can't safely tell the two usages apart; the tombstone convention itself
# stays a judgment-call check, not a mechanical one.
# ---------------------------------------------------------------------------
check-comment-hygiene: ## Fail if change-ID/task-number references leak outside openspec/
	@echo "Scanning for change-ID and task-number references outside openspec/..."
	@matches=$$(grep -rnE \
		'POOLS-[0-9]+|[Ss]ection [0-9]+\.[0-9]+|[Ss]ection [0-9]+(\s|:|$$)|[Tt]ask [0-9]+\.[0-9]+|\btasks\.md\b|\bdesign\.md\b|\bproposal\.md\b' \
		--include="*.py" --include="*.yml" --include="*.yaml" \
		--exclude-dir="openspec" --exclude-dir=".git" --exclude-dir="__pycache__" \
		--exclude-dir=".venv" --exclude-dir="node_modules" --exclude-dir="build" \
		. 2>/dev/null || true); \
	if [ -n "$$matches" ]; then \
		echo "$$matches"; \
		echo ""; \
		echo "FAIL: found change-history references outside openspec/. See AGENTS.md's"; \
		echo "'Python comments and docstrings' section -- comments must describe the"; \
		echo "current system, not the history of the change that produced it."; \
		exit 1; \
	fi
	@echo "OK: no change-ID/task-number references found outside openspec/."

code-snapshot: ## Zip all git-tracked files for sharing (excludes gitignored artifacts).
	@mkdir -p .snapshot
	@OUTFILE="$(CURDIR)/.snapshot/$(GIT_NAME)-$(GIT_SUFFIX).zip"; \
	echo "Creating $$OUTFILE ..."; \
	git ls-files --recurse-submodules | zip -@ "$$OUTFILE"; \
	SIZE=$$(du -sh "$$OUTFILE" | cut -f1); \
	echo "Done: $$OUTFILE ($$SIZE)"

# review-diff must capture untracked new files, not only modifications to
# tracked ones -- a reviewer needs to see everything under review, and
# `git diff HEAD` alone is silent about paths git has never seen. `git add
# -A -N .` (intent-to-add) makes new paths visible to the diff without
# staging their content; the trailing `git reset` unwinds the index back
# to exactly its pre-run state, so the target's own "without changing git
# state" guarantee still holds once it completes.
review-diff: ## Write a binary-safe HEAD-relative diff for review without changing git state.
	@mkdir -p .snapshot
	@OUTFILE="${CURDIR}/.snapshot/$(GIT_NAME)-${GIT_SUFFIX}.diff"; \
	echo "Creating $$OUTFILE ..."; \
	git add -A -N .; \
	git diff --binary HEAD > "$$OUTFILE"; \
	git reset -q; \
	echo "Done: $$OUTFILE"

last-diff: ## Write a binary-safe diff for the most recent commit.
	@mkdir -p .snapshot
	@OUTFILE="${CURDIR}/.snapshot/$(GIT_NAME)-${GIT_SUFFIX}-last.diff"; \
	echo "Creating $$OUTFILE ..."; \
	git diff --binary HEAD^ HEAD > "$$OUTFILE"; \
	echo "Done: $$OUTFILE"

review-wheelhouse-prepare: dist-clean ## Rebuild wheels and refresh selected lockfiles before packaging.
	@$(MAKE) dist
	@$(MAKE) review-locks

review-locks: ## Refresh selected project lockfiles against current repository wheels.
	@uv run python $(CURDIR)/scripts/refresh-review-locks.py \
		--root "$(CURDIR)" \
		--dist-dir "$(DIST_DIR)" \
		--python "$${REVIEW_PYTHON:-3.13}" \
		--projects $${REVIEW_PROJECTS}

review-wheelhouse: review-wheelhouse-prepare ## Bundle scoped locked development dependencies without running tests.
	@bash ./scripts/package-review-wheelhouse.sh "$(CURDIR)/.snapshot/$(GIT_NAME)-$(GIT_SUFFIX)-wheelhouse.tar.gz"

review-wheelhouse-scope: ## Print the review projects resolved from REVIEW_PROJECTS, REVIEW_SCOPE_FILE, or BASE_REF.
	@args="--root $(CURDIR) --base-ref $${BASE_REF:-HEAD^}"; \
	if [ -n "$${REVIEW_PROJECTS:-}" ]; then args="$$args --projects $$REVIEW_PROJECTS"; \
	elif [ -n "$${REVIEW_SCOPE_FILE:-}" ]; then args="$$args --scope-file $$REVIEW_SCOPE_FILE"; fi; \
	$(CURDIR)/scripts/resolve-review-scope.py $$args
