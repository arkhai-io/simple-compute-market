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

.PHONY: helm-values-schema review-wheelhouse review-wheelhouse-scope build build-dev build-seller build-apicredits-service build-apicredits-storefront build-apicredits-sample-app test test-core test-compute-provisioning-contracts test-compute-provisioning-client test-compute-provisioning test-compute-provisioning-ansible test-provisioning test-provisioning-iac test-registry test-kits dist dist-release dist-ci dist-ci-kits dist-storefront-client dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-service dist-compute-provisioning-ansible dist-compute-provisioning-service dist-kits dist-registry-client dist-registry dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-alkahest dist-config dist-clean init init-prerequisites init-submodules init-zero-tier init-buyer init-storefront init-bare-metal-storefront init-arkhai-core-registry push-runtime-artifacts push-images push-dev-image check-packaging check-release-components check-workflow-credentials check-market-binary check-release-versions check-release-record check-uv-setup check-locks check-uv-version check-python-version check-project-layout lock
.PHONY: check-architecture check-architecture-layers check-architecture-scope check-architecture-dependencies check-architecture-kinds check-architecture-change architecture-report
.PHONY: test-release-tooling test-deployment-packaging test-registry-client test-e2e-unit
.PHONY: test-frp-grant-admission test-frp-grant-admission-frp test-frp-grant-admission-floor build-frp-grant-admission
.PHONY: test-lane-double-controls dist-lane-double-controls test-payments-lane-double test-mediation-lane-double build-tools
.PHONY: dist-arkhai-core-registry dist-release-set dist-apicredits-sample-app
.PHONY: build-market-binary build-bare-metal-storefront build-e2e-base build-e2e-vm build-e2e-bare-metal build-e2e-apicredits build-e2e-native-gate test-provisioning-iac-native test-bare-metal-iac-native
.PHONY: run-e2e run-ci fetch-e2e-logs
.PHONY: helm-topology-up helm-topology-down helm-topology-check helm-topology-secrets
.PHONY: design-review validate-local validate-ci validate-helm validate-parallel check-change check-repository install-gitleaks check-public-content check-secrets audit-secrets check-decision-destinations check-history-wording check-version-bumps check-local-imports check-capability-index record-capacity review-diff last-diff code-snapshot review-wheelhouse-prepare review-locks pre-push

# ---------------------------------------------------------------------------
# Dist — build pure-Python wheels for internal packages before image builds.
#
# These wheels are placed in .dist/ (gitignored) and consumed by downstream
# Docker images via --find-links.  Only pure-Python packages (py3-none-any
# wheels) should be built here; packages with native extensions must be built
# inside the Docker build context.
# ---------------------------------------------------------------------------
# The release set alone: every internal wheel but those only tests depend on —
# the lane doubles' control contract and the API-credit sample app — since no
# operator installs one.
dist-release: ## Build the wheel set a release carries.
	$(MAKE) dist-release-set

# Every internal wheel but the lane doubles' control contract and the API-credit
# sample app.
dist-release-set:dist-storefront-client dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-arkhai-core-registry dist-kits dist-alkahest dist-config dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-ansible dist-domains dist-compute-provisioning-service dist-registry-client

# The release set and the two wheels only tests depend on, which the lanes'
# images install from .dist: the lane doubles' control contract, for the e2e
# runner image and both lane doubles' images, and the API-credit sample app, for
# its image in the API-credit lane.
dist: dist-release-set dist-lane-double-controls dist-apicredits-sample-app

dist-ci: dist-storefront-client dist-identity dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-arkhai-core-registry dist-ci-kits dist-alkahest dist-config dist-policy dist-compute-provisioning-contracts dist-compute-provisioning-client dist-compute-provisioning dist-compute-provisioning-ansible dist-domains dist-compute-provisioning-service dist-registry-client dist-lane-double-controls dist-apicredits-sample-app ## Build repository-owned Python wheels without fetching separately released artifacts.

dist-domains: dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-storefront-client dist-registry-client dist-ci-kits dist-compute-provisioning dist-compute-provisioning-ansible ## Build every domains-scoped wheel the release set carries through the domain aggregate
	cd domains && $(MAKE) dist-release DIST_DIR=$(DIST_DIR)

dist-apicredits-sample-app: ## Build the API-credit sample app's wheel into .dist/
	cd domains && $(MAKE) dist-apicredits-sample-app DIST_DIR=$(DIST_DIR)

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

dist-lane-double-controls: ## Build the lane doubles' control-contract wheel into .dist/
	-mkdir -p $(DIST_DIR)
	cd tools/lane-double-controls && $(MAKE) build DIST_DIR=$(DIST_DIR)
	@ls $(DIST_DIR)/lane_double_controls-*-none-any.whl > /dev/null 2>&1 || \
		(echo "ERROR: lane-double-controls produced a platform-specific wheel" && exit 1)

dist-helm: ## Package helm chart so it's ready for pushing into .dist/
	helm package helm/ --destination $(DIST_DIR)

test-release-tooling: dist-identity ## Run the scripts' tests, among them the release declaration's, its checks', and the wheelhouse's.
	uv run --no-project --with pytest --with 'eth-account>=0.13,<0.14' \
		--with 'arkhai-kit-identity' --with pyyaml --find-links "$(DIST_DIR)" \
		pytest -q scripts/tests

test-deployment-packaging: test-release-tooling ## Run release tooling plus Helm schema/render contracts.
	$(MAKE) -C helm test-render

dist-clean: ## Remove .dist/ directory
	rm -rf $(DIST_DIR)

test: test-domains test-core test-kits test-compute-provisioning-contracts test-compute-provisioning-client test-compute-provisioning test-compute-provisioning-ansible test-provisioning test-provisioning-iac test-registry test-registry-client test-e2e-unit test-deployment-packaging test-frp-grant-admission test-lane-double-controls test-payments-lane-double test-mediation-lane-double ## Run every unit and integration suite; the docker-compose e2e scenarios and cluster `helm test` are separate

test-domains:
	$(MAKE) -C domains test

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
	$(MAKE) -C provisioning/compute/iac test

test-registry:
	cd core/registry && make reinit && make test

test-registry-client:
	cd core/registry-client && $(MAKE) test

# The standalone frps admission plugin under tools/: its default suite needs no
# network and skips the real-frp tests, which its gate runs with the floor run.
test-frp-grant-admission:
	$(MAKE) -C tools/frp-grant-admission test

test-frp-grant-admission-frp: ## Run the frps admission plugin against the real frp its pins file names; fetches frp
	$(MAKE) -C tools/frp-grant-admission test-frp

test-frp-grant-admission-floor: ## Run the frps admission plugin's unit tests with its runtime dependencies at their declared floors
	$(MAKE) -C tools/frp-grant-admission test-floor

# The lane doubles' control contract under tools/: the committed lane CA and leaves,
# its type check, then its unit and integration suite.
test-lane-double-controls:
	$(MAKE) -C tools/lane-double-controls test

# The lanes' payments double under tools/: its unit and in-process application
# integration suite.
test-payments-lane-double:
	$(MAKE) -C tools/payments-lane-double test

# The lanes' mediation double under tools/: its unit and in-process application
# integration suite.
test-mediation-lane-double:
	$(MAKE) -C tools/mediation-lane-double test

# The e2e project's unit tests; its scenarios need the docker-compose stack.
test-e2e-unit:
	cd e2e-tests && $(MAKE) test-unit

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
#
# IMAGE_SUFFIX, empty by default, is appended to every image tag a build target
# writes, here and in each subproject the image targets delegate to, which is
# passed it explicitly. A change's Helm validation builds with
# `IMAGE_SUFFIX=-<change>` and deploys those tags, so two changes' builds never
# write one tag (scripts/change_namespace.py). Compose, the pipeline lanes, and
# an owner's own deployments use the bare tags.
IMAGE_SUFFIX ?=

build: ## Build the wheels, the release's market binary, and every runtime image
	$(MAKE) init-prerequisites
	$(MAKE) dist
	$(MAKE) build-market-binary
	$(MAKE) -j4 build-registry build-storefront build-bare-metal-storefront build-provisioning
	$(MAKE) -j4 build-apicredits-service build-apicredits-storefront build-apicredits-sample-app build-frp-grant-admission

build-dev: ## Build everything `build` does, the dev chain image, the test image, and the lane doubles
	$(MAKE) build
	$(MAKE) build-dev-env
	$(MAKE) build-test-image
	$(MAKE) build-tools

# One end-to-end lane's images: the wheels, the dev chain with its baked state,
# the test image (which installs `market` from the wheels, so no lane needs
# the release's binary), and the runtime images that lane's stack runs. Each lane job
# builds only its own; build-dev keeps building everything for local use. The
# pipeline runs a lane target on a fresh checkout, so this target, not its
# caller, makes the wheels first, ordered as `build` orders its steps.
build-e2e-base:
	$(MAKE) init-prerequisites
	$(MAKE) dist
	$(MAKE) build-dev-env
	$(MAKE) build-test-image

build-e2e-vm: build-e2e-base ## Build the VM end-to-end lane's images
	$(MAKE) -j4 build-registry build-storefront build-provisioning build-tools

build-e2e-bare-metal: build-e2e-base ## Build the bare-metal end-to-end lane's images
	$(MAKE) -j4 build-registry build-provisioning build-bare-metal-storefront build-tools

build-e2e-apicredits: build-e2e-base ## Build the API-credit end-to-end lane's images
	$(MAKE) -j5 build-registry build-apicredits-service build-apicredits-storefront build-apicredits-sample-app build-tools

# The native Ansible gate's image: only the provisioning image and the wheels it
# installs, since the gate composes no stack, so no dev chain and no test image.
# The pipeline runs it on a fresh checkout, so the wheels come first, as the lane
# targets make them.
build-e2e-native-gate: ## Build the provisioning image the native Ansible gate runs in
	$(MAKE) init-prerequisites
	$(MAKE) dist
	$(MAKE) build-provisioning

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

# The release's `market` binary: the buyer CLI frozen with every declared buyer
# domain, installed from its locked project, core/buyer/market-binary, in the
# build image that project's Dockerfile pins by digest. scripts/market_binary.py
# reads the binary's name and output from the declaration entry this target
# builds, and derives what the freeze needs; check-market-binary holds the
# project's dependencies to the declaration. The image's smoke test runs
# `market plugins`. Like the image targets, it builds no wheels: run `make dist`
# first.
MARKET_BINARY = python3 scripts/market_binary.py --target $@
build-market-binary: ## Build the release's linux/amd64 market binary from the wheelhouse into its declared path
	name=$$($(MARKET_BINARY) name) && \
	output=$$($(MARKET_BINARY) output-dir) && \
	entry_point=$$($(MARKET_BINARY) entry-point) && \
	options=$$($(MARKET_BINARY) pyinstaller-options) && \
	echo "Freezing $$entry_point as $$output/$$name" && \
	docker build -f core/buyer/market-binary/Dockerfile \
		--build-arg "BINARY_NAME=$$name" \
		--build-arg "ENTRY_POINT=$$entry_point" \
		--build-arg "PYINSTALLER_OPTIONS=$$options" \
		--output "type=local,dest=$$output" .

# Regenerate the baked Anvil state + Alkahest address book by running
# EnvTestManager once and snapshotting its chain (see dev-env/generate_state.py).
# Runs through the storefront venv, which pins alkahest_py; the relative
# --find-links keeps domains/vms/storefront/uv.lock paths portable.
build-anvil-state:
	cd kit/alkahest && uv run --find-links ../../.dist python ../../dev-env/generate_state.py

build-dev-env: build-anvil-state
	cd dev-env && make build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

build-registry:
	cd core/registry && make build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

build-storefront:
	cd domains/vms/storefront && make build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

build-bare-metal-storefront:
	docker build --ulimit nofile=65536:65536 \
		-f domains/bare_metal/storefront/Dockerfile \
		-t arkhai:bare-metal-storefront$(IMAGE_SUFFIX) .

build-provisioning:
	cd provisioning/compute/service && make build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

# Native gates run the Ansible, collections, playbooks and tests packaged in the
# candidate image, with loopback networking only. A separate parse pass uses the
# shared service configuration and image role path, as service jobs do.
PROVISIONING_IMAGE ?= arkhai:compute-provisioning$(IMAGE_SUFFIX)
test-bare-metal-iac-native: ## Native helper account/IPC/mount checks in a disposable private container
	@docker image inspect $(PROVISIONING_IMAGE) >/dev/null 2>&1 || { \
		echo "no $(PROVISIONING_IMAGE) image: build it first, with make build-provisioning" >&2; exit 1; }
	docker run --rm --user 0 --network none --pid="" --ipc private \
		--cap-add SYS_ADMIN --security-opt apparmor=unconfined \
		--tmpfs /work:rw,nosuid,nodev,mode=0755 \
		-v "$(CURDIR)/domains/bare_metal/provisioning/iac:/iac:ro" -w /iac \
		-e BARE_METAL_DISPOSABLE_NATIVE=private-container-v1 \
		-e PYTHON=/home/appuser/ansible-venv/bin/python \
		$(PROVISIONING_IMAGE) bash scripts/native_cleanup_gate.sh

test-provisioning-iac-native: ## Run family and VM IaC native Ansible tests in the built provisioning image
	@docker image inspect $(PROVISIONING_IMAGE) >/dev/null 2>&1 || { \
		echo "no $(PROVISIONING_IMAGE) image: build it first, with make build-provisioning" >&2; exit 1; }
	docker run --rm --network none \
		-w /opt/domains/vms/provisioning/iac \
		-e PYTHON=/home/appuser/ansible-venv/bin/python \
		$(PROVISIONING_IMAGE) bash scripts/native_ansible_gate.sh
	docker run --rm --network none \
		-w /opt/provisioning/compute/iac \
		-e PYTHON=/home/appuser/ansible-venv/bin/python \
		$(PROVISIONING_IMAGE) bash scripts/native_ansible_gate.sh
	docker run --rm --network none -e ANSIBLE_LOG_PATH=/dev/null \
		$(PROVISIONING_IMAGE) bash /opt/provisioning/compute/iac/scripts/image_syntax_gate.sh

# API-credits domain images (item 6). Built from the repo root so each
# Dockerfile's `COPY .dist/` + `COPY domains/` resolve. The api-credits
# registry reuses arkhai:registry (built by build-registry) with a
# different filter-spec mounted at runtime.
build-apicredits-service:
	docker build --ulimit nofile=65536:65536 -f domains/apicredits/service/Dockerfile -t arkhai:apicredits-service$(IMAGE_SUFFIX) .

build-apicredits-storefront:
	docker build --ulimit nofile=65536 -f domains/apicredits/storefront/Dockerfile -t arkhai:apicredits-storefront$(IMAGE_SUFFIX) .

build-apicredits-sample-app:
	docker build --ulimit nofile=65536:65536 -f domains/apicredits/sample-app/Dockerfile -t arkhai:apicredits-sample-app$(IMAGE_SUFFIX) .

# The frps admission plugin builds from its own directory, which is the whole of its
# build context; the image carries the plugin's own version, read from its project.
FRP_GRANT_ADMISSION_DIR := tools/frp-grant-admission
# Hoisted into a variable: macOS-shipped GNU Make 3.81 refuses `$$` inside single
# quotes inside `$(shell ...)`.
FRP_GRANT_ADMISSION_VERSION_SED := s/^version = "\(.*\)"$$/\1/p
build-frp-grant-admission: ## Build the frps admission plugin's image
	docker build --ulimit nofile=65536:65536 \
		--build-arg VERSION=$(shell sed -n '$(FRP_GRANT_ADMISSION_VERSION_SED)' $(FRP_GRANT_ADMISSION_DIR)/pyproject.toml) \
		-f $(FRP_GRANT_ADMISSION_DIR)/Dockerfile \
		-t arkhai:frp-grant-admission$(IMAGE_SUFFIX) $(FRP_GRANT_ADMISSION_DIR)
	$(if $(IMAGE_SUFFIX),,docker tag arkhai:frp-grant-admission arkhai:frp-grant-admission-$(GIT_SUFFIX))

build-test-image:
	cd e2e-tests && make build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

# The lane doubles' images, which lanes and the local release run and nothing
# pushes; each is built by its own target in tools/Makefile.
build-tools: ## Build the lane doubles' images
	cd tools && $(MAKE) build IMAGE_SUFFIX=$(IMAGE_SUFFIX)

#Init should complete all deployment times set up steps required prior to your standalone run statements
#The less of these the better but sometimes you get things like helm repo add or terraform init that can't be avoided.
# `make init` builds the internal wheels and resolves dependencies for the buyer,
# both storefronts, and the registry. Each project's Makefile owns its own venv;
# we just delegate so a fresh clone has one entry point. Run `make build`
# separately for Docker images.
init: init-prerequisites init-submodules init-buyer init-storefront init-bare-metal-storefront init-arkhai-core-registry

# The uv installed here is the repository's minimum (scripts/check_uv_version.py):
# init's reinit refuses an older one.
init-prerequisites:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.12.22/install.sh | sh; source $HOME/.local/bin/env; }

init-submodules:
	GIT_TRACE=1 GIT_CURL_TRACE=1 git submodule update --init

# ZeroTier overlay install (sudo). Standalone — run by whoever sets up the
# overlay network; not pulled into `build` so a default build needs no sudo.
init-zero-tier:
	cd scripts/zerotier && make install

# Each role's environment installs every internal package its lock names from
# .dist, so each builds the whole repository wheelhouse first. A hand-kept subset
# drifts from the locks, and the gap shows only in a checkout whose .dist no
# earlier build has filled, such as a fresh clone.
init-buyer: dist-ci
	cd domains/vms/buyer && make init

init-storefront: dist-ci
	cd domains/vms/storefront && make init

# The bare-metal chart's and the release topology's render checks load their
# rendered configuration with this environment's storefront; without it they
# skip, which validation fails.
init-bare-metal-storefront: dist-ci
	cd domains/bare_metal/storefront && make init

init-arkhai-core-registry: dist-ci
	cd core/registry && make init

deploy-compose:
	docker compose up
	docker compose ps

# Top-level Helm deploy consumes pre-existing Secret names from helm/values.yaml;
# credential files never pass through Helm values, while a host definitions
# document, which names keys by path and carries none, is the provisioning
# chart's `definitions.hosts` value. It keeps the release's volumes on
# uninstall; a local development cluster is deployed with
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
# Supply AR_PROJECT and AR_LOCATION explicitly for the destination deployment.
# Registry URLs are derived from these values and AR_PREFIX.
# ---------------------------------------------------------------------------

AR_PROJECT ?=
AR_LOCATION ?=
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
#   make build-market-binary — .dist/bin/market must exist
#
# Targets can be run individually or all at once via push-runtime-artifacts.
# ---------------------------------------------------------------------------

ARTIFACT_COMMAND = python3 scripts/publish_artifacts.py --project "$(AR_PROJECT)" --location "$(AR_LOCATION)" --prefix "$(AR_PREFIX)"

.PHONY: _require-ar-project test-domains dist-domains push-dev-images push-charts push-wheels push-cli clobber-wheels
_require-ar-project:
	@$(ARTIFACT_COMMAND) check

push-runtime-artifacts: push-images push-charts push-wheels push-cli

push-images: _require-ar-project
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target registry --source registry
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target storefront --source storefront
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target provisioning --source compute-provisioning
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target frp-grant-admission --source frp-grant-admission

push-dev-images: _require-ar-project
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target dev-env --source dev-env
	$(ARTIFACT_COMMAND) image --registry "$(DOCKER_REGISTRY)" --suffix "$(GIT_SUFFIX)" --target e2e-tests --source e2e-tests

push-charts: _require-ar-project dist-helm
	helm push $(DIST_DIR)/arkhai-node-operator-*.tgz $(HELM_REGISTRY)
	rm $(DIST_DIR)/arkhai-node-operator-*.tgz

push-wheels: _require-ar-project ## Publish every declared distribution to the registry.
	uv run --no-project python scripts/push-distributions.py \
	  --dist-dir $(DIST_DIR) --registry $(PYTHON_REGISTRY)

push-cli: _require-ar-project
	gcloud artifacts generic upload \
	  --project=$(AR_PROJECT) \
	  --location=$(AR_LOCATION) \
	  --repository=$(AR_PREFIX)-cli \
	  --package=market \
	  --version=$(GIT_SUFFIX) \
	  --source=.dist/bin/market

clobber-wheels: _require-ar-project
	$(ARTIFACT_COMMAND) wheel --registry "$(PYTHON_REGISTRY)" --package arkhai-core-storefront-client --version "$(STOREFRONT_CLIENT_VERSION)" --wheel "$(DIST_DIR)/arkhai_core_storefront_client-$(STOREFRONT_CLIENT_VERSION)-py3-none-any.whl" --clobber
	$(ARTIFACT_COMMAND) wheel --registry "$(PYTHON_REGISTRY)" --package arkhai-core-registry-client --version "$(REGISTRY_CLIENT_VERSION)" --wheel "$(DIST_DIR)/arkhai_core_registry_client-$(REGISTRY_CLIENT_VERSION)-py3-none-any.whl" --clobber
	$(ARTIFACT_COMMAND) wheel --registry "$(PYTHON_REGISTRY)" --package arkhai-vms-provisioning-operator-client --version "$(PROVISIONING_OPERATOR_CLIENT_VERSION)" --wheel "$(DIST_DIR)/arkhai_vms_provisioning_operator_client-$(PROVISIONING_OPERATOR_CLIENT_VERSION)-py3-none-any.whl" --clobber

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

# An indexed capability's spec.md held to its index.md
# (openspec/README.md#capability-documentation-pattern). With CHANGE=<name> that
# change's deltas count as its archive will leave them, since closeout writes the
# index before the archive merges them.
check-spec-index: ## Fail if an indexed capability's spec.md and index.md disagree on its requirement ids (CHANGE=<name> counts its deltas)
	@python3 scripts/check_spec_index.py "$(CHANGE)"

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

# An older uv writes locks at an older revision; uv_project.py refuses it too, but
# this prerequisite refuses before the wheelhouse is built, even under -j.
lock: check-uv-version ## Relock projects against current wheels without installing anything (PROJECTS="dir ..." narrows it)
	@$(MAKE) --no-print-directory dist
	python3 scripts/uv_project.py lock $(PROJECTS)

check-uv-version: ## Fail if the installed uv is older than the minimum that writes this repository's locks
	@python3 scripts/check_uv_version.py

check-packaging: dist ## Run every packaging check against the tree and a freshly built wheelhouse
	@$(MAKE) --no-print-directory check-uv-setup check-locks check-python-version check-project-layout check-architecture check-workflow-credentials check-market-binary

check-release-components: ## Fail if a workflow, publish target, or lane target lists release components itself, a workflow holds a publishing credential, or the market binary's project bundles other than the declared buyer CLI and domains
	@python3 scripts/check_release_components.py

check-workflow-credentials: ## Fail if a workflow holds a credential that could publish, or names a publishing step
	@python3 scripts/check_release_components.py --rule credentials

check-market-binary: ## Fail unless the market binary's project depends on exactly the declared buyer CLI and buyer domains
	@python3 scripts/check_release_components.py --rule market-binary

check-release-versions: ## Fail if a wheel or the chart keeps a version an earlier marketplace release recorded with other contents: the wheelhouse and the chart packaged with .helm-version's Helm, or with TAG=marketplace-v<semver> that tag's own record, with no build
	@python3 scripts/check_release_versions.py $(if $(TAG),--tag $(TAG))

check-release-record: ## Fail unless TAG=marketplace-v<semver> records a marketplace release in the shape the cut makes
	@test -n "$(TAG)" || { echo "check-release-record: name the tag, TAG=marketplace-v<semver>" >&2; exit 1; }
	@python3 scripts/check_release_record.py $(TAG)

check-uv-setup: ## Fail if a reinit target or image install names internal packages instead of deriving them
	@python3 scripts/check_uv_setup.py

check-locks: ## Fail if a lock is not current with its project, the wheels in .dist, or the repository (run make dist first)
	@python3 scripts/check_locks.py

check-python-version: ## Fail if anything selects a Python version other than .python-version
	@python3 scripts/check_python_version.py

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

review-locks: ## Refresh selected project lockfiles against current repository wheels.
	@if [ -z "$${REVIEW_PROJECTS}" ]; then echo "REVIEW_PROJECTS names no projects" >&2; exit 1; fi
	python3 scripts/uv_project.py lock $${REVIEW_PROJECTS}

# The change workflow's targets — each step, the review, the round view, the
# workflow's checks, and the guarded push — are the engine's make fragment, which
# reads the branch a change lands on from the change's clone. A value of the
# owner's machine, such as HELM_ALL_SCENARIOS or HELM_CONTEXT given to `make
# validate`, reaches the Helm part's command through the environment: make exports
# a variable set on its command line to every command it runs, the validation
# session included, and the part's own make reads it there.
include scripts/change_workflow/workflow.mk

# The owner's complete closing check is the workflow's whole `pre-commit`: its
# default checks, then this repository's `check-repository`, each once. Run as the
# engine runs it before a commit, a worktree changing a path outside the inert
# paths runs the functional hooks first.
check-change: ## Run the change workflow's pre-commit for a change: its default checks — the change index, the task list, the agent skills, the strict OpenSpec validation — then check-repository; when the worktree changes a path outside the inert paths, relocking, the packaging check, and every suite first (CHANGE=<change> [CHANGE_BASE=<the branch it lands on; the one its clone recorded>])
	@scripts/change-workflow run pre-commit "$(CHANGE)"$(if $(strip $(CHANGE_BASE)), --base "$(CHANGE_BASE)")

check-repository: ## Run this repository's own closing checks of a change — comment hygiene, its citations, the indexed capabilities' specifications, decision destinations, history wording, version bumps, local imports, and the capability index — printing only failures and one pass line; the workflow's pre-commit hook (CHANGE=<change> [CHANGE_BASE=<the branch it lands on; the one its clone recorded>])
	@python3 scripts/check_change.py "$(CHANGE)"$(if $(strip $(CHANGE_BASE)), --base "$(CHANGE_BASE)")

check-decision-destinations: ## Fail if a `### D<n>` decision of a change's design has no bullet starting `D<n>` in its proposal's "Knowledge to promote" (CHANGE=<change>)
	@python3 scripts/check_decision_destinations.py "$(CHANGE)"

check-history-wording: ## Fail if a comment or docstring line added since the merge-base with the branch the change lands on describes history ([CHANGE_BASE=dev])
	@python3 scripts/check_history_wording.py$(if $(strip $(CHANGE_BASE)), --base "$(CHANGE_BASE)")

check-version-bumps: ## Fail if a package version differs from its version at the merge-base with the branch the change lands on by more than one SemVer step ([CHANGE_BASE=dev])
	@python3 scripts/check_version_bumps.py$(if $(strip $(CHANGE_BASE)), --base "$(CHANGE_BASE)")

check-local-imports: ## Fail if an import added inside a function since the merge-base with the branch the change lands on has no comment giving its reason ([CHANGE_BASE=dev])
	@python3 scripts/check_local_imports.py$(if $(strip $(CHANGE_BASE)), --base "$(CHANGE_BASE)")

check-capability-index: ## Fail if a capability with a spec.md has no row in openspec/specs/README.md, or a row links nothing
	@python3 scripts/check_capability_index.py

record-capacity: ## Record in helm/validation-capacity.toml the memory a change's latest validation measured, with when and from which change; when it measured none, leave the file as it is and say so; run by archive cleanup (CHANGE=<change>)
	@python3 scripts/validate_slice.py capacity --change "$(CHANGE)"

design-review: ## Design review of an OpenSpec change in Codex, continuing the last design reviewer (CHANGE=<change> [FRESH=1])
	@$(MAKE) --no-print-directory review CHANGE="$(CHANGE)" KIND=design

HELM_CONTEXT ?= docker-desktop

validate-local: round-view-closed ## Validate HEAD without changing the checkout: check-packaging, then make test
	@python3 scripts/validate_slice.py local

WORKFLOW ?=
CI_AFTER_RUN ?=

validate-ci: round-view-closed ## Validate HEAD on a CI run dispatched by run-ci: wait for the run newer than CI_AFTER_RUN, keep its job logs, and class each failure against the same job in the latest completed dev run of code the branch contains (WORKFLOW=<file> CI_AFTER_RUN=<id>)
	@python3 scripts/validate_slice.py ci --workflow "$(WORKFLOW)" $(if $(strip $(CI_AFTER_RUN)),--after-run "$(CI_AFTER_RUN)")

validate-helm: round-view-closed ## Validate HEAD on the Helm charts in the change's namespace: preflights, the change's images, render checks, the release upgraded from zero over deleted volumes, the pipeline's scenarios as a pod there (CHANGE=<change> HELM_CONTEXT=docker-desktop [HELM_ALL_SCENARIOS=1])
	@python3 scripts/validate_slice.py helm --context "$(HELM_CONTEXT)" $(if $(CHANGE),--change "$(CHANGE)") $(if $(filter 1,$(HELM_ALL_SCENARIOS)),--all-scenarios)

# It deploys, so it is named as a validation and its script outside `check_*`:
# six steps' rules allow any `make check-*`, and closeout's `python3 scripts/check_*`.
validate-parallel: ## Run two changes' clones' Helm parts at the same moment and report whether each kept to its own namespace, tags, and scenario pod, and what it left in its namespace (CLONES="<clone> <clone>" HELM_CONTEXT=docker-desktop)
	@python3 scripts/validate_parallel.py --context "$(HELM_CONTEXT)" $(CLONES)

# Each dispatch ends its output with the newest run of its workflow on the branch
# before the dispatch, alone on the last line: the marker validation's collect
# waits past (fetch-e2e-logs' E2E_AFTER_RUN, validate-ci's CI_AFTER_RUN).
run-e2e: round-view-closed ## Run the E2E GitHub Actions workflow on the current branch, ending with the newest run of it there before the dispatch
	@python3 scripts/ci_evidence.py pipeline

run-ci: round-view-closed ## Dispatch a CI workflow validation may dispatch on the current branch, refusing any other, ending with the newest run of it there before the dispatch (WORKFLOW=<file>)
	@python3 scripts/ci_evidence.py dispatch "$(WORKFLOW)"

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


install-gitleaks: ## Install the gitleaks release scripts/gitleaks-pins.toml pins, verified against its sha256; needs no root and does nothing when it is already on PATH ([GITLEAKS_INSTALL_DIR=~/.local/bin])
	@python3 scripts/install_gitleaks.py$(if $(strip $(GITLEAKS_INSTALL_DIR)), --dir "$(GITLEAKS_INSTALL_DIR)")

check-public-content: ## Scan staged changes for recognizable private content, and for private keys and provider credentials through the pinned gitleaks
	@status=0; \
	python3 scripts/check_public_content.py --staged || status=1; \
	python3 scripts/check_secrets.py --staged || status=1; \
	exit $$status

REMOTE ?=

# Git gives a pre-push hook its ref updates on standard input, which both checks
# read, so they are read once and given to each; either refuses the push. The
# updates go on with no newline added: Git runs the hook with no input when every
# ref is up to date, and a blank line would be read as a malformed update. The
# repository's Git hook and the workflow's guarded push both run this.
pre-push: ## Run both public-content checks on what a push would send, as Git runs a pre-push hook: the ref updates on standard input (REMOTE=<remote>)
	@if [ -z "$(REMOTE)" ]; then echo "ERROR: pre-push needs REMOTE=<remote>" >&2; exit 2; fi; \
	updates=$$(cat); status=0; \
	printf '%s' "$$updates" | python3 scripts/check_public_content.py --pre-push "$(REMOTE)" || status=1; \
	printf '%s' "$$updates" | python3 scripts/check_secrets.py --pre-push "$(REMOTE)" || status=1; \
	exit $$status

check-secrets: ## Scan staged changes for private keys and provider credentials through the pinned gitleaks (.gitleaks.toml)
	@python3 scripts/check_secrets.py --staged

audit-secrets: ## Report what every gitleaks rule finds in HEAD's tracked tree, refusing nothing; read it before an official build ships (scripts/gitleaks-audit.toml)
	@python3 scripts/check_secrets.py --audit
