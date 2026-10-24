# PyPI intermittently serves 5xx where internal package names should
# 404 (they resolve from .dist); back off through the flap instead of
# failing after uv's default 3 tries.
# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat .python-version 2>/dev/null),$(error .python-version not found))

export UV_HTTP_RETRIES ?= 10

GIT_SUFFIX := $(shell git rev-parse --short HEAD)
GIT_NAME   ?= simple-compute-market
FOUNDRY_VERSION := v1.5.1
DIST_DIR := ${CURDIR}/.dist
IDENTITY_WHEEL := $(DIST_DIR)/arkhai_kit_identity-0.4.0-py3-none-any.whl

.PHONY: helm-values-schema e2e-dev-identities e2e-dev-identities-env e2e-vms-dev-env e2e-apicredits-dev-env e2e-apicredits-stack-env e2e-bare-metal-dev-env review-wheelhouse review-wheelhouse-scope build build-dev build-seller build-apicredits-service build-apicredits-storefront build-apicredits-sample-app test test-core test-compute-provisioning-contracts test-compute-provisioning-client test-compute-provisioning test-compute-provisioning-ansible test-provisioning test-provisioning-iac test-registry test-storefront test-bare-metal test-compute test-api test-api-client test-api-authority test-api-selling test-vms-domain test-vms-buyer test-apicredits test-apicredits-middleware test-kits dist dist-release dist-ci dist-ci-kits dist-api dist-api-contracts dist-api-client dist-api-authority dist-api-selling dist-storefront-client dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-service dist-compute-provisioning-ansible dist-compute-provisioning-service dist-kits dist-registry-client dist-registry dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-bare-metal-storefront dist-apicredits-domain dist-apicredits-service dist-apicredits-storefront dist-apicredits-middleware dist-apicredits-sample-app dist-apicredits-buyer dist-alkahest dist-config dist-clean init init-prerequisites init-submodules init-zero-tier init-buyer init-storefront init-arkhai-core-registry push-runtime-artifacts push-images push-dev-image check-packaging check-uv-setup check-locks check-python-version check-project-layout lock
.PHONY: check-architecture check-architecture-layers check-architecture-scope check-architecture-dependencies check-architecture-kinds check-architecture-change architecture-report
.PHONY: test-release-tooling test-deployment-packaging test-registry-client test-provisioning-adapter test-e2e-unit
.PHONY: dist-arkhai-core-registry
.PHONY: build-bare-metal-storefront build-e2e-base build-e2e-vm build-e2e-bare-metal build-e2e-apicredits build-apicredits-service-prekit
.PHONY: dist-bare-metal-buyer
.PHONY: run-e2e fetch-e2e-logs
.PHONY: helm-topology-up helm-topology-down helm-topology-check helm-topology-secrets
.PHONY: check-agent-skills review design-review design orchestrate plan implement validate-local validate-helm check-push-ready push-branch validate triage closeout archive-cleanup check-change-index check-tasks check-change change-next change-watch change-cost round-view round-done round-e2e-baseline round-view-closed review-diff last-diff code-snapshot review-wheelhouse-prepare review-locks

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
# The wheel set a publishing path builds; publishing workflows call this name.
dist-release: ## Build the wheel set for a publishing path.
	$(MAKE) dist

dist: dist-storefront-client dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-arkhai-core-registry dist-kits dist-alkahest dist-config dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-ansible dist-domains dist-compute-provisioning-service dist-registry-client

dist-ci: dist-storefront-client dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-arkhai-core-registry dist-ci-kits dist-alkahest dist-config dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-ansible dist-domains dist-compute-provisioning-service dist-registry-client ## Build repository-owned Python wheels without fetching separately released artifacts.

dist-domains: dist-ci-kits dist-compute-provisioning dist-compute-provisioning-ansible ## Build every domains-scoped wheel through the domain aggregate
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

dist-compute-provisioning-contracts: ## Build the compute provisioning family's wire-contract wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute/contracts && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning_contracts-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-provisioning-contracts produced a platform-specific wheel" && exit 1)

dist-compute-provisioning-client: dist-compute-provisioning-contracts ## Build the compute provisioning family's client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute/client && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-provisioning-client produced a platform-specific wheel" && exit 1)

dist-compute-provisioning: dist-ci-kits dist-compute-provisioning-contracts ## Build arkhai-compute-provisioning wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-provisioning produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-compute-provisioning-ansible: dist-compute-provisioning ## Build the compute family kit's Ansible implementation wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute/ansible && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning_ansible-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-compute-provisioning-ansible produced a platform-specific wheel" && exit 1)

dist-compute-provisioning-service: dist-ci-kits dist-compute-provisioning dist-domains ## Build the extracted compute service wheel.
	-mkdir -p $(DIST_DIR)
	cd provisioning/compute/service && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_compute_provisioning_service-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: compute provisioning service produced a platform-specific wheel" && exit 1)

dist-registry-client: ## Build arkhai-core-registry-client wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/registry-client && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_registry_client-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-registry-client produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-arkhai-core-registry: dist-registry-client ## Build arkhai-core-registry wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd core/registry && uv build --wheel --out-dir $(DIST_DIR)
	@ls $(DIST_DIR)/arkhai_core_registry-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: arkhai-core-registry produced a platform-specific wheel — must build inside Docker" && exit 1)

dist-registry: dist-registry-client ## Compatibility alias for dist-registry-client.

dist-identity: ## Build the exact identity-kit release wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd kit/identity && uv build --wheel --out-dir $(DIST_DIR)
	@test -f $(IDENTITY_WHEEL) || \
		(echo "ERROR: expected exact identity wheel $(IDENTITY_WHEEL)" && exit 1)

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

dist-bare-metal-buyer: dist-core dist-arkhai-core-buyer dist-registry-client dist-kits ## Build the bare-metal buyer contribution wheel.
	cd domains && $(MAKE) dist-bare-metal-buyer DIST_DIR=$(DIST_DIR)

dist-bare-metal-storefront: dist-core dist-arkhai-core-storefront dist-kits ## Build the bare-metal storefront contribution wheel.
	cd domains && $(MAKE) dist-bare-metal-storefront DIST_DIR=$(DIST_DIR)

# API-credits wheels, forwarded to `domains/Makefile` the same way the
# bare-metal ones above are. `dist-domains` already builds all of these
# through the domain aggregate; these exist so one wheel can be rebuilt on
# its own while iterating, which is what
# `domains/apicredits/sample-app/Makefile` and
# `domains/apicredits/middleware/python`'s workflow both tell you to do
# from the repository root.
#
# Prerequisites are each wheel's own internal dependencies, so a target
# invoked directly on a clean tree resolves instead of failing in
# `uv build` on a missing `.dist` entry.
dist-api: dist-identity ## Build arkhai-api, the api-family vocabulary, into .dist/
	cd domains && $(MAKE) dist-api DIST_DIR=$(DIST_DIR)

dist-api-contracts: dist-identity ## Build arkhai-api-contracts wheel into .dist/ (domains/Makefile builds arkhai-api first)
	cd domains && $(MAKE) dist-api-contracts DIST_DIR=$(DIST_DIR)

dist-api-client: dist-identity ## Build arkhai-api-client wheel into .dist/ (domains/Makefile builds the vocabulary and contracts first)
	cd domains && $(MAKE) dist-api-client DIST_DIR=$(DIST_DIR)

dist-api-authority: dist-identity dist-ci-kits ## Build arkhai-api-authority wheel into .dist/ (domains/Makefile builds the vocabulary and contracts first)
	cd domains && $(MAKE) dist-api-authority DIST_DIR=$(DIST_DIR)

dist-api-selling: dist-identity dist-core dist-registry-client dist-arkhai-core-storefront dist-ci-kits dist-policy ## Build arkhai-api-selling wheel into .dist/ (domains/Makefile builds the vocabulary, contracts, and client first)
	cd domains && $(MAKE) dist-api-selling DIST_DIR=$(DIST_DIR)

dist-apicredits-domain: dist-core dist-identity dist-alkahest dist-policy ## Build arkhai-apicredits-domain wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-domain DIST_DIR=$(DIST_DIR)

dist-apicredits-service: dist-identity dist-ci-kits dist-apicredits-domain dist-apicredits-middleware ## Build arkhai-apicredits-service wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-service DIST_DIR=$(DIST_DIR)

dist-apicredits-storefront: dist-apicredits-domain dist-arkhai-core-storefront dist-registry-client dist-ci-kits dist-config ## Build arkhai-apicredits-storefront wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-storefront DIST_DIR=$(DIST_DIR)

dist-apicredits-middleware: dist-identity ## Build arkhai-apicredits-middleware wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-middleware DIST_DIR=$(DIST_DIR)

# Depends on the middleware wheel because the sample app requires it with
# the `signed` extra, which resolves arkhai-kit-identity out of .dist/.
dist-apicredits-sample-app: dist-apicredits-middleware ## Build arkhai-apicredits-sample-app wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-sample-app DIST_DIR=$(DIST_DIR)

dist-apicredits-buyer: dist-apicredits-domain dist-arkhai-core-buyer dist-ci-kits dist-config ## Build arkhai-apicredits-buyer wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-buyer DIST_DIR=$(DIST_DIR)

dist-kits: ## Build kit-owned wheels into .dist/
	$(MAKE) -C kit dist DIST_DIR=$(DIST_DIR)

dist-ci-kits: ## Build kit-owned wheels that do not require separately released artifacts.
	$(MAKE) -C kit dist-ci DIST_DIR=$(DIST_DIR)

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

test-release-tooling: dist-identity ## Run release verifier and portable wheelhouse contract tests.
	uv run --no-project --with pytest --with 'eth-account>=0.13,<0.14' \
		--with 'arkhai-kit-identity' --find-links "$(DIST_DIR)" \
		pytest -q scripts/tests

test-deployment-packaging: test-release-tooling ## Run release tooling plus Helm schema/render contracts.
	$(MAKE) -C helm test-render

dist-clean: ## Remove .dist/ directory
	rm -rf $(DIST_DIR)

test: test-core test-kits test-compute-provisioning-contracts test-compute-provisioning-client test-compute-provisioning test-compute-provisioning-ansible test-provisioning test-provisioning-iac test-registry test-registry-client test-storefront test-provisioning-adapter test-bare-metal test-compute test-api test-vms-domain test-vms-buyer test-apicredits test-e2e-unit test-deployment-packaging ## Run every unit and integration suite; the docker-compose e2e scenarios and cluster `helm test` are separate

test-core:
	cd core && make test

test-compute-provisioning-contracts:
	cd provisioning/compute/contracts && $(MAKE) test

test-compute-provisioning-client:
	cd provisioning/compute/client && $(MAKE) test

test-compute-provisioning:
	cd provisioning/compute && make test

test-compute-provisioning-ansible:
	cd provisioning/compute/ansible && make test

test-provisioning:
	cd provisioning/compute/service && make test

test-provisioning-iac:
	$(MAKE) -C domains test-provisioning-iac

test-registry:
	cd core/registry && make reinit && make test

test-registry-client:
	cd core/registry-client && $(MAKE) test

test-provisioning-adapter:
	$(MAKE) -C domains test-provisioning-adapter

# The e2e project's unit tests; its scenarios need the docker-compose stack.
test-e2e-unit:
	cd e2e-tests && $(MAKE) test-unit

test-storefront:
	$(MAKE) -C domains test-storefront

test-bare-metal:
	$(MAKE) -C domains test-bare-metal

test-compute:
	$(MAKE) -C domains test-compute

test-api:
	$(MAKE) -C domains test-api

test-api-client:
	$(MAKE) -C domains test-api-client

test-api-authority:
	$(MAKE) -C domains test-api-authority

test-api-selling:
	$(MAKE) -C domains test-api-selling

test-vms-domain:
	$(MAKE) -C domains test-vms-domain

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
# `build` produces the production artifacts: the runtime images and the buyer
# CLI binary. `build-dev` adds the test chain + integration-test image needed
# for the local e2e stack.
#
# Every image copies `.dist/` and the dev chain's state is generated from it,
# so the wheels must be complete before any of them starts. Under `make -j` a
# target's prerequisites run concurrently, and the GNU Make the pipeline's
# runners carry (4.3) has no `.WAIT` to order them, so these targets order
# their steps as recipe lines of recursive calls instead. Only the images,
# which share nothing but `.dist/`, are built in parallel.
build: ## Build the wheels, the buyer CLI binary, and every runtime image
	$(MAKE) init-prerequisites
	$(MAKE) dist
	$(MAKE) build-buyer
	$(MAKE) -j4 build-registry build-storefront build-bare-metal-storefront build-provisioning
	$(MAKE) -j3 build-apicredits-service build-apicredits-storefront build-apicredits-sample-app

# ---------------------------------------------------------------------------
# e2e-*-dev-env — each stack's signer, wallet, and buyer paths from the
# committed development values in dev-env/identities, as bare `VAR=value`
# lines for `docker compose --env-file`.
#
# The compose files guard every one of these with `${VAR:?...}`, so
# `docker compose up` refuses to start until all are set. Exporting them from
# committed fixtures is what lets a contributor, a fork, or a CI job holding no
# repository secrets run a stack. Every value is a well-known deterministic
# development value; see dev-env/identities/README.md, which lists the files
# each target satisfies.
#
#   e2e-vms-dev-env         the VM lane (compose.vms.yml, compose.vms-local.yml)
#   e2e-apicredits-dev-env  the API-credit lane (compose.apicredits.yml,
#                           compose.apicredits-local.yml, compose.apicredits-lane.yml)
#   e2e-bare-metal-dev-env  the bare-metal lane, below
#   e2e-dev-identities-env  the full local stack (docker-compose.yml and both
#                           market overlays): the VM and API-credit values except
#                           the API-credit lane's own compute registry
#
# The e2e targets write a file rather than eval'ing captured output: compose
# reads the file itself, so nothing has to survive a shell round-trip, and a
# recursive make implies `-w` and would print `Entering directory` into a
# capture. Recursion here passes `--no-print-directory` for the same reason.
# `e2e-dev-identities` prints the full stack's values as `export` lines for a
# human to eval:
#
#     eval "$(make -s --no-print-directory e2e-dev-identities)"
# ---------------------------------------------------------------------------
E2E_IDENTITY_DIR := $(CURDIR)/dev-env/identities
E2E_BUYER_RUNTIME_DIR ?= $(CURDIR)/.e2e-buyer
# Development bearer tokens for registry-b, which gates read and write.
# Not secret; the same values are committed in the storefront secret
# overlay and the buyer config, and all three must agree.
E2E_REGISTRY_ADMIN_KEY ?= development-registry-admin-key
E2E_REGISTRY_BOOTSTRAP_KEY ?= development-registry-bootstrap-key

# Mock provisioning is the provisioning service's `mock` profile, chosen per
# run: the services run their playbooks through the mock runner and mount the
# `/test` controls. It is a separate choice from running locally — a local
# stack can provision real hosts, and a cluster runs mock through the
# provisioning chart's `mockMode`. The lane scenarios hold jobs through the
# `/test` controls, so the lanes default to mock; `real` selects each stack's
# container profile. The compose files default to real when no environment
# file says otherwise, as the chart does. No storefront reads this: whether
# delivery is mocked is the provisioning service's concern alone.
PROVISIONING_MODE ?= mock
E2E_PROVISIONING_PROFILES_mock := mock
E2E_PROVISIONING_PROFILES_real := docker
E2E_PROVISIONING_PROFILES = $(E2E_PROVISIONING_PROFILES_$(PROVISIONING_MODE))
E2E_REQUIRE_PROVISIONING_MODE = $(if $(E2E_PROVISIONING_PROFILES),,$(error PROVISIONING_MODE must be mock or real, not '$(PROVISIONING_MODE)'))

e2e-dev-identities: ## Print shell exports pointing the full local stack at committed development identities
	@$(MAKE) -s --no-print-directory e2e-dev-identities-env \
		| sed 's/^/export /; s/=\(.*\)$$/="\1"/'

e2e-dev-identities-env: ## Print the full local stack's VAR=value lines for `docker compose --env-file`
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	@$(MAKE) -s --no-print-directory e2e-vms-dev-env
	@$(MAKE) -s --no-print-directory e2e-apicredits-stack-env

e2e-vms-dev-env: ## Print the VM lane's VAR=value lines for `docker compose --env-file`
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	@mkdir -p "$(E2E_BUYER_RUNTIME_DIR)/profile" "$(E2E_BUYER_RUNTIME_DIR)/state"
	@echo 'VMS_PROVISIONING_ACTIVE_PROFILES=$(E2E_PROVISIONING_PROFILES)'
	@echo 'VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/registry-a.eip191'
	@echo 'VMS_REGISTRY_B_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/registry-b.eip191'
	@echo 'VMS_PROVISIONING_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/provisioning.identity.env'
	@echo 'VMS_ALICE_PROVISIONING_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/provisioning-alice.identity.env'
	@echo 'VMS_BOB_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/bob.identity.env'
	@echo 'VMS_ALICE_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/alice.identity.env'
	@echo 'VMS_BOB_EVM_WALLET_ENV_FILE=$(CURDIR)/domains/vms/storefront/.env.bob.docker'
	@echo 'VMS_ALICE_EVM_WALLET_ENV_FILE=$(CURDIR)/domains/vms/storefront/.env.alice.docker'
	@echo 'VMS_BUYER_CONFIG_PATH=$(E2E_IDENTITY_DIR)/buyer.config.toml'
	@echo 'VMS_BUYER_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/buyer.eip191'
	@echo 'VMS_BUYER_PROFILE_DIR=$(E2E_BUYER_RUNTIME_DIR)/profile'
	@echo 'VMS_BUYER_STATE_DIR=$(E2E_BUYER_RUNTIME_DIR)/state'
	@echo 'VMS_BOB_STOREFRONT_SECRETS_FILE=$(E2E_IDENTITY_DIR)/bob.storefront.secrets.toml'
	@# registry-b gates read and write behind bearer tokens. The bootstrap
	@# value must stay byte-equal to the [registry.auth] entries in
	@# bob.storefront.secrets.toml and buyer.config.toml, so all three come
	@# from this one constant.
	@echo 'VMS_REGISTRY_ADMIN_API_KEY=$(E2E_REGISTRY_ADMIN_KEY)'
	@echo 'VMS_REGISTRY_BOOTSTRAP_API_KEY=$(E2E_REGISTRY_BOOTSTRAP_KEY)'

# The API-credit stack's values, shared by its lane and the full local stack.
e2e-apicredits-stack-env:
	@mkdir -p "$(E2E_BUYER_RUNTIME_DIR)/apicredits/profile" "$(E2E_BUYER_RUNTIME_DIR)/apicredits/state"
	@echo 'APICREDITS_REGISTRY_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/api-credits-registry.ed25519'
	@echo 'APICREDITS_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/api-credits.identity.env'
	@echo 'APICREDITS_EVM_WALLET_ENV_FILE=$(E2E_IDENTITY_DIR)/api-credits.wallet.env'
	@echo 'APICREDITS_ADMIN_KEY_FILE=$(E2E_IDENTITY_DIR)/api-credits-admin-key'
	@echo 'APICREDITS_SERVICE_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/api-credits-service.ed25519'
	@echo 'APICREDITS_GATED_APP_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/api-credits-gated-app.ed25519'
	@echo 'APICREDITS_BUYER_CONFIG_PATH=$(E2E_IDENTITY_DIR)/api-credits-buyer.config.toml'
	@echo 'APICREDITS_BUYER_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/buyer.eip191'
	@echo 'APICREDITS_BUYER_PROFILE_DIR=$(E2E_BUYER_RUNTIME_DIR)/apicredits/profile'
	@echo 'APICREDITS_BUYER_STATE_DIR=$(E2E_BUYER_RUNTIME_DIR)/apicredits/state'

e2e-apicredits-dev-env: ## Print the API-credit lane's VAR=value lines for `docker compose --env-file`
	@$(MAKE) -s --no-print-directory e2e-apicredits-stack-env
	@# The compute-schema registry the credits scenario routes discovery
	@# across; only the lane runs it, since the full stack has VM's.
	@echo 'APICREDITS_COMPUTE_REGISTRY_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/registry-a.eip191'

# ---------------------------------------------------------------------------
# e2e-bare-metal-dev-env — the bare-metal end-to-end lane's `--env-file`
# values: compose.bare-metal.yml, compose.dev.yml, and
# compose.bare-metal-local.yml guard every one with `${VAR:?...}`.
#
# The lane is a separate stack on its own dev chain, so it reuses the committed
# Anvil development credentials under the assignments recorded in
# dev-env/identities/README.md ("The bare-metal lane"). The storefront's own
# settings are not here: they are its development storefront.toml and secrets
# overlay, which this target names as files for the stack to mount. Only the
# bare-metal stack's own files and the variables its Compose files read are
# printed.
# ---------------------------------------------------------------------------
E2E_BARE_METAL_DIR := $(CURDIR)/dev-env/bare-metal
E2E_BARE_METAL_REGISTRY_ID := 0x90f79bf6eb2c4f870365e785982e1f101e93b906
E2E_BARE_METAL_SITE_AUTHORITY_ID := 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
E2E_BARE_METAL_STOREFRONT_ID := 0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc
E2E_BARE_METAL_SITE_ADMIN_ID := 0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc
E2E_BARE_METAL_SITE_ID := bare-metal-e2e

e2e-bare-metal-dev-env: ## Print VAR=value lines for the bare-metal lane's `docker compose --env-file`
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	@echo 'BARE_METAL_PROVISIONING_ACTIVE_PROFILES=$(E2E_PROVISIONING_PROFILES)'
	@echo 'BARE_METAL_REGISTRY_AUTHORITY_ID=bare-metal-registry'
	@echo 'BARE_METAL_REGISTRY_AUTHORITY_SCHEME=eip191'
	@echo 'BARE_METAL_REGISTRY_AUTHORITY_IDENTIFIER=$(E2E_BARE_METAL_REGISTRY_ID)'
	@echo 'BARE_METAL_REGISTRY_PUBLIC_URL=http://bare-metal-registry:8080'
	@echo 'BARE_METAL_REGISTRY_DISPLAY_NAME=Local Bare Metal Compute Registry'
	@echo 'BARE_METAL_OPERATOR_IDENTITY=Arkhai local development'
	@echo 'BARE_METAL_REGISTRY_IDENTITY_CREDENTIAL_FILE=$(E2E_IDENTITY_DIR)/registry-a.eip191'
	@echo 'BARE_METAL_PROVISIONING_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/provisioning.identity.env'
	@echo 'BARE_METAL_PROVISIONING_IDENTITY_SCHEME=eip191'
	@echo 'BARE_METAL_PROVISIONING_IDENTITY_IDENTIFIER=$(E2E_BARE_METAL_SITE_AUTHORITY_ID)'
	@echo 'BARE_METAL_PROVISIONING_ADMIN_IDENTITY_SCHEME=eip191'
	@echo 'BARE_METAL_PROVISIONING_ADMIN_IDENTITY_IDENTIFIER=$(E2E_BARE_METAL_SITE_ADMIN_ID)'
	@echo 'BARE_METAL_PROVISIONING_INVENTORY_FILE=$(E2E_BARE_METAL_DIR)/hosts.ini'
	@echo 'BARE_METAL_POOL_DEFINITIONS_FILE=$(E2E_BARE_METAL_DIR)/resource-pools.yaml'
	@echo 'BARE_METAL_PROVISIONING_SSH_PRIVATE_KEY_FILE=$(E2E_BARE_METAL_DIR)/ssh-key-placeholder'
	@echo 'BARE_METAL_SITE_ID=$(E2E_BARE_METAL_SITE_ID)'
	@# The site binds its seller role to the storefront's principal, which the
	@# storefront's development storefront.toml states as [Identity.principal].
	@echo 'BARE_METAL_STOREFRONT_IDENTITY_SCHEME=eip191'
	@echo 'BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER=$(E2E_BARE_METAL_STOREFRONT_ID)'
	@echo 'BARE_METAL_STOREFRONT_IDENTITY_ENV_FILE=$(E2E_IDENTITY_DIR)/bob.identity.env'
	@echo 'BARE_METAL_STOREFRONT_CONFIG_FILE=$(CURDIR)/domains/bare_metal/storefront/storefront.dev.toml'
	@echo 'BARE_METAL_STOREFRONT_SECRETS_FILE=$(E2E_IDENTITY_DIR)/bare-metal.storefront.secrets.toml'
	@# The buyer service is in the `buyer` profile and the lane never starts it,
	@# but compose still requires its variables.
	@echo 'BARE_METAL_BUYER_IMAGE=arkhai:e2e-tests'
	@echo 'BARE_METAL_BUYER_IDENTITY_ENV_FILE=$(E2E_BARE_METAL_DIR)/buyer.identity.env'
	@echo 'BARE_METAL_BUYER_CONFIG_FILE=$(E2E_BARE_METAL_DIR)/buyer.toml'

build-dev: ## Build everything `build` does, the dev chain image, and the test image
	$(MAKE) build
	$(MAKE) build-dev-env
	$(MAKE) build-test-image

# One end-to-end lane's images: the wheels, the dev chain with its baked state,
# the test image (which installs `market` from the wheels, so no lane needs
# build-buyer), and the runtime images that lane's stack runs. Each lane job
# builds only its own; build-dev keeps building everything for local use. The
# pipeline runs a lane target on a fresh checkout, so this target, not its
# caller, makes the wheels first, ordered as `build` orders its steps.
build-e2e-base:
	$(MAKE) init-prerequisites
	$(MAKE) dist
	$(MAKE) build-dev-env
	$(MAKE) build-test-image

build-e2e-vm: build-e2e-base ## Build the VM end-to-end lane's images
	$(MAKE) -j3 build-registry build-storefront build-provisioning

build-e2e-bare-metal: build-e2e-base ## Build the bare-metal end-to-end lane's images
	$(MAKE) -j3 build-registry build-provisioning build-bare-metal-storefront

build-e2e-apicredits: build-e2e-base build-apicredits-service-prekit ## Build the API-credit end-to-end lane's images
	$(MAKE) -j4 build-registry build-apicredits-service build-apicredits-storefront build-apicredits-sample-app

# The previous service release, built from the pinned base commit's own
# wheelhouse in a temporary worktree.
APICREDITS_SERVICE_PREKIT_COMMIT := 9720ac59697a132f48913b91448c8224ece35cde
APICREDITS_SERVICE_PREKIT_WORKTREE := $(CURDIR)/.worktrees/apicredits-service-prekit

build-apicredits-service-prekit: ## Build arkhai:apicredits-service-prekit, the previous service release, from the pinned base commit
	git cat-file -e $(APICREDITS_SERVICE_PREKIT_COMMIT)^{commit} 2>/dev/null || \
		git fetch --depth 1 origin $(APICREDITS_SERVICE_PREKIT_COMMIT)
	git worktree remove --force $(APICREDITS_SERVICE_PREKIT_WORKTREE) 2>/dev/null || true
	git worktree prune
	git worktree add --detach $(APICREDITS_SERVICE_PREKIT_WORKTREE) $(APICREDITS_SERVICE_PREKIT_COMMIT)
	( $(MAKE) -C $(APICREDITS_SERVICE_PREKIT_WORKTREE) dist && \
	  cd $(APICREDITS_SERVICE_PREKIT_WORKTREE) && docker build --ulimit nofile=65536:65536 \
		-f domains/apicredits/service/Dockerfile -t arkhai:apicredits-service-prekit . ); \
	status=$$?; git worktree remove --force $(APICREDITS_SERVICE_PREKIT_WORKTREE); exit $$status

# Seller-only build: the two runtime images a seller actually needs
# (`arkhai:storefront`, `arkhai:compute-provisioning`) and just the wheels they
# consume via --find-links. Skips `build-registry` (sellers point at
# someone else's registry).
build-seller: init-prerequisites dist-kits dist-storefront-client dist-identity dist-core dist-arkhai-core-storefront dist-alkahest dist-config dist-policy dist-compute-provisioning dist-domains dist-compute-provisioning-service dist-registry-client ## Build only what a seller needs: storefront + provisioning images.
	$(MAKE) -j3 build-storefront build-bare-metal-storefront build-provisioning

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
	cd kit/alkahest && uv run --find-links ../../.dist python ../../dev-env/generate_state.py

build-dev-env: build-anvil-state
	cd dev-env && make build

build-registry:
	cd core/registry && make build

build-storefront:
	cd domains/vms/storefront && make build

build-bare-metal-storefront:
	docker build --ulimit nofile=65536:65536 \
		-f domains/bare_metal/storefront/Dockerfile \
		-t arkhai:bare-metal-storefront .

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

# Top-level Helm deploy consumes pre-existing Secret names from helm/values.yaml;
# credential files and inventory content never pass through Helm values. It keeps
# the release's volumes on uninstall; a local development cluster is deployed with
# `make -C helm deploy-local` instead (docs/development/DEPLOYMENT_AND_CONFIG.md).
deploy: deploy-helm

deploy-helm:
	$(MAKE) -C helm deploy

# The local two-release topology on a development cluster: several storefronts
# per registry. Release 1 is `make -C helm deploy-local`'s release; release 2 is
# the bare-metal storefront and its own provisioning service, publishing to
# release 1's registry (helm/bare-metal-release-values.yaml). helm/Makefile's
# topology targets say what each installs, needs, and checks; helm-topology-secrets
# creates the Secrets both releases read and the deal test's buyer-profile volume,
# from development values only.
helm-topology-secrets: ## Create the local two-release Helm topology's Secrets and the buyer-profile volume, from development values (cast and kubectl)
	$(MAKE) -C helm topology-secrets

helm-topology-up: ## Install the local two-release Helm topology (the umbrella, then the bare-metal seller release on its registry) and restart its Deployments, all but dev-env's, onto rebuilt images
	$(MAKE) -C helm topology-up

helm-topology-down: ## Uninstall the local two-release Helm topology, the bare-metal seller release first
	$(MAKE) -C helm topology-down

helm-topology-check: ## Run both releases' helm tests against the installed two-release topology
	$(MAKE) -C helm topology-check

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
	$(call push_image,provisioning,compute-provisioning)

push-dev-images: _require-ar-project
	$(call push_image,dev-env,dev-env)
	$(call push_image,e2e-tests,e2e-tests)

push-charts: _require-ar-project dist-helm
	helm push $(DIST_DIR)/arkhai-node-operator-*.tgz $(HELM_REGISTRY)
	rm $(DIST_DIR)/arkhai-node-operator-*.tgz

push-wheels: _require-ar-project ## Publish every manifest distribution to the registry.
	uv run --no-project python scripts/push-distributions.py \
	  --dist-dir $(DIST_DIR) --registry $(PYTHON_REGISTRY)

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
# check-comment-hygiene — mechanical sweep for AGENTS.md's "Python comments and
# docstrings" rule: change IDs, section/task numbers, change-document filenames,
# and OpenSpec change names must never appear in code outside openspec/. The
# scans, their file types, exclusions, and the one exemption are
# scripts/check_comment_hygiene.py's, with their reasons.
# ---------------------------------------------------------------------------
check-comment-hygiene: ## Fail if change-ID/task-number references leak outside openspec/
	@python3 scripts/check_comment_hygiene.py

# ---------------------------------------------------------------------------
# check-doc-citations — AGENTS.md's cross-reference rule: every openspec/,
# docs/, tools/, scripts/, e2e-tests/, and .agents/ path cited by a document
# must resolve on this branch, and an unresolvable one is a blocking defect
# rather than a stale link.
#
# Rejects a tombstoned target as well as an absent one. The existence test
# this replaces could not fail on a rename-to-tombstone -- the likeliest
# broken citation in a renaming change -- because a tombstoned file still
# exists on disk while its content is gone. The predicate is imported from
# scripts/tombstones.py rather than reimplemented, so this check and the
# prune utility cannot disagree about what a tombstone is.
#
# Archived changes are excluded: they record what was true when archived. A
# change runs this during its own closeout, while its citations are still
# expected to hold.
# ---------------------------------------------------------------------------
# Pass CHANGE=<name> to scope to one change's own documents, active or archived,
# which is what a closeout gates on: a change owes the citations it wrote, and
# gating it on the whole repository's documentation debt would let one stale
# runbook block everyone else's archival.
check-doc-citations: ## Fail if a document cites a path that is absent or tombstoned (CHANGE=<name> to scope)
	@python3 scripts/check_doc_citations.py "$(CHANGE)"

# Each storefront chart's values schema carries one definition generated from
# that storefront's typed configuration models; it keeps secret-marked fields
# out of the chart's pass-through config. Each storefront names the schema files
# it writes -- VM's storefront chart and the umbrella's storefront definition, and
# the bare-metal chart's -- and its generator runs in that storefront's own
# environment (make init-storefront; make -C domains/bare_metal/storefront init),
# whose test suite fails when a committed definition is stale.
helm-values-schema: ## Regenerate each storefront's config definition in its Helm values schemas
	cd domains/vms/storefront && uv run --frozen --no-sync python -m market_storefront.values_schema write --root ../../..
	cd domains/bare_metal/storefront && uv run --frozen --no-sync python -m arkhai_bare_metal_storefront.values_schema write --root ../../..

lock: dist ## Relock projects against current wheels without installing anything (PROJECTS="dir ..." narrows it)
	python3 scripts/uv_project.py lock $(PROJECTS)

check-packaging: dist ## Run every packaging check against the tree and a freshly built wheelhouse
	@$(MAKE) --no-print-directory check-uv-setup check-locks check-python-version check-project-layout check-architecture

check-uv-setup: ## Fail if a reinit target or image install names internal packages instead of deriving them
	@python3 scripts/check_uv_setup.py

check-locks: ## Fail if a lock is not current with its project, the wheels in .dist, or the repository (run make dist first)
	@python3 scripts/check_locks.py

check-python-version: ## Fail if anything selects a Python version other than .python-version
	@python3 scripts/check_python_version.py

check-agent-skills: ## Fail if an agent skill is not loaded from its one source under .agents/skills
	@python3 scripts/check_agent_skills.py

check-project-layout: ## Fail if a distribution is not one package under src/ or cannot install editable
	@python3 scripts/check_project_layout.py

# check-architecture -- the package layer, scope, and kind rules of
# docs/development/ARCHITECTURE.md, over every import and every declared
# internal dependency, against docs/development/ARCHITECTURE.toml. Each part
# runs alone; any part failing fails the whole. It reads only the tree, so it
# needs no wheelhouse and no project environment.
check-architecture: ## Fail if a package breaks a layer, scope, dependency, or kind rule no exception row excuses
	@status=0; \
	for part in layers scope dependencies kinds; do \
		python3 scripts/check_architecture_$$part.py || status=1; \
	done; \
	exit $$status

check-architecture-layers: ## Fail on an upward dependency, a same-layer cycle, a scope outside its layer's bounds, an unclassified project, a stale override, or an invalid rules file
	@python3 scripts/check_architecture_layers.py

check-architecture-scope: ## Fail on a dependency or identity literal outside a package's scope
	@python3 scripts/check_architecture_scope.py

check-architecture-dependencies: ## Fail on an undeclared internal import; warn on an unexplained declaration
	@python3 scripts/check_architecture_dependencies.py

check-architecture-kinds: ## Fail on a dependency outside a kind or package allowlist, an undeclared third-party import in an allowlisted package, or an imported plugin
	@python3 scripts/check_architecture_kinds.py

# A change owes the rows it owns, as it owes the citations it wrote: it may not
# be archived while it owns an exception or override row.
check-architecture-change: ## Fail while CHANGE=<name> owns an architecture exception or override row
	@if [ -z "$(CHANGE)" ]; then echo "CHANGE=<name> is required" >&2; exit 2; fi
	@status=0; \
	for part in layers scope dependencies kinds; do \
		python3 scripts/check_architecture_$$part.py --change "$(CHANGE)" || status=1; \
	done; \
	if [ $$status -eq 0 ]; then echo "OK: $(CHANGE) owns no architecture row."; fi; \
	exit $$status

architecture-report: ## Write the full architecture report, no exception applied (OUT=<path>, else stdout)
	@python3 scripts/architecture_report.py $(if $(OUT),--out "$(OUT)")

# `zip -y` stores a symlink as a link. Without it the agent-skill links under
# .claude/skills and .codex/skills unzip as empty directories, and the snapshot no
# longer shows which skills each harness loads.
code-snapshot: round-view-closed ## Zip all git-tracked files for sharing (excludes gitignored artifacts).
	@mkdir -p .snapshot
	@OUTFILE="$(CURDIR)/.snapshot/$(GIT_NAME)-$(GIT_SUFFIX).zip"; \
	echo "Creating $$OUTFILE ..."; \
	git ls-files --recurse-submodules | zip -y -@ "$$OUTFILE"; \
	SIZE=$$(du -sh "$$OUTFILE" | cut -f1); \
	echo "Done: $$OUTFILE ($$SIZE)"

# review-diff must capture untracked new files, not only modifications to
# tracked ones -- a reviewer needs to see everything under review, and
# `git diff HEAD` alone is silent about paths git has never seen. `git add
# -A -N .` (intent-to-add) makes new paths visible to the diff without
# staging their content; the trailing `git reset` unwinds the index back
# to exactly its pre-run state, so the target's own "without changing git
# state" guarantee still holds once it completes.
review-diff: round-view-closed ## Write a binary-safe HEAD-relative diff for review without changing git state.
	@mkdir -p .snapshot
	@OUTFILE="${CURDIR}/.snapshot/$(GIT_NAME)-${GIT_SUFFIX}.diff"; \
	echo "Creating $$OUTFILE ..."; \
	git add -A -N .; \
	git diff --binary HEAD > "$$OUTFILE"; \
	git reset -q; \
	echo "Done: $$OUTFILE"

last-diff: round-view-closed ## Write a binary-safe diff for the most recent commit.
	@mkdir -p .snapshot
	@OUTFILE="${CURDIR}/.snapshot/$(GIT_NAME)-${GIT_SUFFIX}-last.diff"; \
	echo "Creating $$OUTFILE ..."; \
	git diff --binary HEAD^ HEAD > "$$OUTFILE"; \
	echo "Done: $$OUTFILE"

review-wheelhouse-prepare: ## Rebuild the wheelhouse from scratch, then refresh review locks.
	@# Nothing needs preserving across the rebuild any more. This copied the
	@# staged release inputs to a temporary directory and handed them back to
	@# `dist`, because `dist-clean` would otherwise delete artifacts that were
	@# received rather than built. `dist` builds every wheel it produces, so a
	@# clean rebuild loses nothing.
	$(MAKE) dist-clean
	$(MAKE) dist
	@$(MAKE) review-locks

review-locks: ## Refresh selected project lockfiles against current repository wheels.
	@if [ -z "$${REVIEW_PROJECTS}" ]; then echo "REVIEW_PROJECTS names no projects" >&2; exit 1; fi
	python3 scripts/uv_project.py lock $${REVIEW_PROJECTS}

review-wheelhouse: ## Resolve scope, rebuild wheels, refresh locks, and bundle dependencies.
	@projects="$${REVIEW_PROJECTS:-}"; \
	if [ -z "$${projects// }" ]; then \
		args="--root $(CURDIR) --base-ref $${BASE_REF:-HEAD^} --format lines"; \
		if [ -n "$${REVIEW_SCOPE_FILE:-}" ]; then args="$$args --scope-file $$REVIEW_SCOPE_FILE"; fi; \
		projects="$$($(CURDIR)/scripts/resolve-review-scope.py $$args | tr '\n' ' ')"; \
	fi; \
	$(MAKE) review-wheelhouse-prepare REVIEW_PROJECTS="$$projects"; \
	REVIEW_PROJECTS="$$projects" bash ./scripts/package-review-wheelhouse.sh \
		"$(CURDIR)/.snapshot/$(GIT_NAME)-$(GIT_SUFFIX)-wheelhouse.tar.gz"

review-wheelhouse-scope: ## Print the review projects resolved from REVIEW_PROJECTS, REVIEW_SCOPE_FILE, or BASE_REF.
	@args="--root $(CURDIR) --base-ref $${BASE_REF:-HEAD^}"; \
	if [ -n "$${REVIEW_PROJECTS:-}" ]; then args="$$args --projects $$REVIEW_PROJECTS"; \
	elif [ -n "$${REVIEW_SCOPE_FILE:-}" ]; then args="$$args --scope-file $$REVIEW_SCOPE_FILE"; fi; \
	$(CURDIR)/scripts/resolve-review-scope.py $$args

REVIEW_BASE ?= dev
# The review's models are the review row's in .claude/change-steps.toml. Unset by
# default; given, they are the owner's choice for one run, outside the row's policy:
# REVIEW_MODEL replaces the whole list, a claude- model running on Claude and any
# other on Codex, and the record says so. The orchestrating session never sets them.
REVIEW_MODEL ?=
REVIEW_EFFORT ?=
review: round-view-closed ## Review an OpenSpec change read-only, in Codex or, when Codex is unavailable, on Claude (CHANGE=<change> KIND=design|implementation|pre-closeout|closeout [REVIEW_BASE=dev] [REVIEW_MODEL=<any model id, claude-… on Claude; the owner's choice>] [REVIEW_EFFORT=<effort>] [FRESH=1] [UNVALIDATED=1])
	@python3 scripts/run_change_step.py review "$(CHANGE)" --kind "$(KIND)" --base "$(REVIEW_BASE)" $(if $(strip $(REVIEW_MODEL)),--model "$(REVIEW_MODEL)") $(if $(strip $(REVIEW_EFFORT)),--effort "$(REVIEW_EFFORT)") $(if $(strip $(FRESH)),--fresh) $(if $(filter 1,$(UNVALIDATED)),--unvalidated)

# With UNATTENDED=1, a step's target runs it through scripts/run_change_step.py
# instead: a headless Claude Code session held to the step's permissions in
# .claude/change-steps.toml, ending with an outcome logged to the change's
# reviews/workflow.jsonl. Without it, each target opens an interactive session as
# the owner's own permission settings allow.
STEP_RUN = python3 scripts/run_change_step.py run

design: ## Open a Claude Code design session for an OpenSpec change (CHANGE=<change> [UNATTENDED=1])
	@python3 scripts/find_change.py --active "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) design "$(CHANGE)",claude "/change-design $(CHANGE)")

# The orchestrating session relays and routes rather than judging, so it needs a
# large context for a change's relayed turns, not a high effort.
orchestrate: ## Open the orchestrating Claude Code session for one OpenSpec change, on Opus 5.5 at medium effort (CHANGE=<change>)
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@claude --model claude-opus-5-5 --effort medium "/change-orchestrate $(CHANGE)"

plan: ## Open a Claude Code planning session for an OpenSpec change; unattended, it resumes the design session (CHANGE=<change> [UNATTENDED=1] [FRESH=1])
	@python3 scripts/find_change.py --active "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) plan "$(CHANGE)"$(if $(filter 1,$(FRESH)), --fresh),claude "/change-plan $(CHANGE)")

implement: round-view-closed ## Open a fresh Claude Code session implementing an OpenSpec change (CHANGE=<change> [SECTION=<n>] [SECTIONS=<n-m>] [UNATTENDED=1])
	@python3 scripts/find_change.py --active "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) implement "$(CHANGE)"$(if $(strip $(SECTIONS)$(SECTION)), --sections "$(or $(strip $(SECTIONS)),$(strip $(SECTION)))"),claude "/change-implement $(CHANGE)$(if $(strip $(SECTIONS)), sections $(SECTIONS),$(if $(strip $(SECTION)), section $(SECTION)))")

triage: round-view-closed ## Open a fresh Claude Code session triaging an OpenSpec change's untriaged reviews, validation, and the owner's notes (CHANGE=<change> [UNATTENDED=1])
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) triage "$(CHANGE)",claude "/change-triage $(CHANGE)")

closeout: round-view-closed ## Open a fresh Claude Code session closing out an OpenSpec change, archiving it last; resumes one archived but not committed (CHANGE=<change> [UNATTENDED=1])
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) closeout "$(CHANGE)",claude "/change-closeout $(CHANGE)")

check-change-index: ## Fail if the change index has a malformed row, an unresolved change link, an unknown status, a dependency it does not list or that is archived, or an active change directory without exactly one row
	@python3 scripts/check_change_index.py

check-tasks: ## Fail if a task of a change's task list sits under another section's heading: a heading is missing or the task misplaced (CHANGE=<change>)
	@python3 scripts/check_tasks.py "$(CHANGE)"

check-change: ## Run a change's closing checks — comment hygiene, agent skills, its citations and task list, the change index, and the pinned strict OpenSpec validation — printing only failures and one pass line (CHANGE=<change>)
	@python3 scripts/check_change.py "$(CHANGE)"

change-watch: ## Follow the progress of an OpenSpec change's steps as they run, moving to each new step's progress file as it starts; Ctrl+C stops (CHANGE=<change>)
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@python3 scripts/run_change_step.py watch "$(CHANGE)"

change-next: ## Print the next step of an OpenSpec change as the orchestrator computes it, in plain form: the step, its reason, and for a waiting run its seq and what it asks (CHANGE=<change>)
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@python3 scripts/change_next_step.py "$(CHANGE)" --plain

change-cost: ## Report what an OpenSpec change's unattended runs cost, by step and by round, with partial dollars as a range and the cache misses with their gaps (CHANGE=<change>)
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@python3 scripts/change_cost.py "$(CHANGE)"

archive-cleanup: round-view-closed ## Open a fresh Claude Code session cleaning up an archived OpenSpec change once its closeout review's triage has advanced it: dependents released, row set to archived (CHANGE=<change> [UNATTENDED=1])
	@python3 scripts/find_change.py --archived "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) archive-cleanup "$(CHANGE)",claude "/change-archive-cleanup $(CHANGE)")

round-view-closed: ## Fail while a round view is open: the branch then points at the round's base, not its commit
	@python3 scripts/round_view.py check

round-view: ## Show an implementation round as uncommitted changes in this checkout for the owner's reading, after pushing HEAD and dispatching the E2E pipeline (CHANGE=<change> [BASE=<commit>] [NO_E2E=1])
	@python3 scripts/round_view.py start "$(CHANGE)" $(if $(BASE),--base "$(BASE)") $(if $(filter 1,$(NO_E2E)),--no-e2e)

round-done: ## Return the branch to the round's commit after round-view, keeping any edits as uncommitted changes
	@python3 scripts/round_view.py done

round-e2e-baseline: ## Print, and forget, the run before the E2E run round-view dispatched for HEAD, if it dispatched one
	@python3 scripts/round_view.py e2e-baseline

design-review: ## Design review of an OpenSpec change in Codex, continuing the last design reviewer (CHANGE=<change> [FRESH=1])
	@$(MAKE) --no-print-directory review CHANGE="$(CHANGE)" KIND=design

HELM_CONTEXT ?= docker-desktop

validate-local: round-view-closed ## Validate HEAD without changing the checkout: check-packaging, then make test
	@python3 scripts/validate_slice.py local

validate-helm: round-view-closed ## Validate HEAD on the Helm charts: preflights, images, render checks, the release replaced by a fresh local deploy, the pipeline's scenarios (HELM_CONTEXT=docker-desktop [HELM_ALL_SCENARIOS=1])
	@python3 scripts/validate_slice.py helm --context "$(HELM_CONTEXT)" $(if $(filter 1,$(HELM_ALL_SCENARIOS)),--all-scenarios)

check-push-ready: round-view-closed ## Fail unless HEAD is a clean, attached change branch that may be pushed to its own name
	@python3 scripts/check_push_ready.py check

push-branch: round-view-closed ## Push exactly HEAD, unforced, to the current branch's own name once check-push-ready passes
	@python3 scripts/check_push_ready.py push

validate: round-view-closed ## Open a Claude Code session validating the commit at HEAD for an OpenSpec change (CHANGE=<change> [HELM_ALL_SCENARIOS=1] [UNATTENDED=1])
	@python3 scripts/find_change.py "$(CHANGE)" >/dev/null
	@$(if $(filter 1,$(UNATTENDED)),$(STEP_RUN) validate "$(CHANGE)"$(if $(filter 1,$(HELM_ALL_SCENARIOS)), --arguments "with HELM_ALL_SCENARIOS=1"),claude "/change-validate $(CHANGE)$(if $(filter 1,$(HELM_ALL_SCENARIOS)), with HELM_ALL_SCENARIOS=1)")

run-e2e: round-view-closed ## Run the E2E GitHub Actions workflow on the current branch.
	@branch="$$(git branch --show-current)"; \
	if [ -z "$$branch" ]; then \
		echo "ERROR: run-e2e requires a checked-out branch." >&2; \
		exit 1; \
	fi; \
	echo "Triggering E2E workflow on branch $$branch..."; \
	gh workflow run e2e.yml --ref "$$branch"

E2E_LOG_DIR ?= $(CURDIR)/.snapshot/e2e-logs
E2E_RUN_ID ?=
E2E_COMMIT ?=
E2E_AFTER_RUN ?=

fetch-e2e-logs: ## Wait for an E2E run, fetch its logs, and zip the resulting directory.
	@$(CURDIR)/scripts/fetch-e2e-logs.py \
		--output-dir "$(E2E_LOG_DIR)" \
		$(if $(strip $(E2E_RUN_ID)),--run-id "$(E2E_RUN_ID)") \
		$(if $(strip $(E2E_COMMIT)),--commit "$(E2E_COMMIT)") \
		$(if $(strip $(E2E_AFTER_RUN)),--after-run "$(E2E_AFTER_RUN)")

prune-tombstones: ## Delete every file whose contents are a tombstone comment
	@python3 scripts/prune_tombstones.py
