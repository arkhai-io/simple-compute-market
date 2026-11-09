# PyPI intermittently serves 5xx where internal package names should
# 404 (they resolve from .dist); back off through the flap instead of
# failing after uv's default 3 tries.
# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../.python-version 2>/dev/null),$(error ../.python-version not found))

export UV_HTTP_RETRIES ?= 10

PYTHON      ?= python3

# Default profile if none supplied
ACTIVE_PROFILES ?= local
CONFIG_DIRECTORY ?= $(CURDIR)/config
MODULE ?= contracts

# Path to the monorepo .dist/ wheel directory, relative to e2e-tests/.
# Used by uv when resolving pure-Python internal packages (arkhai-vms-buyer,
# arkhai-kit-policy, arkhai-vms-storefront, and the VM operator client) that are distributed as wheels rather than editable
# source installs.  The Dockerfile passes --find-links /dist on the uv sync
# CLI instead; this variable is for local development only.
DIST_DIR ?= ../.dist

.PHONY: build venv test test-e2e test-e2e-vm test-e2e-bare-metal test-e2e-apicredits \
	e2e-vm-down e2e-vm-logs e2e-bare-metal-down e2e-bare-metal-logs e2e-apicredits-down e2e-apicredits-logs

# -----------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------

init-venv:
	uv venv --allow-existing

init: init-venv reinit

reinit: init-venv
	python3 ../scripts/uv_project.py reinit

# -----------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= e2e-tests
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
# Appended to the image's tag; the root Makefile's IMAGE_SUFFIX. A suffixed build
# is tagged per change alone: a commit tag would keep one image per validated commit.
# The targets that run the image use the bare tag, as the pipeline lanes do.
IMAGE_SUFFIX ?=

build: build-images

build-images: reinit
	cd .. && docker build -t $(IMAGE_NAME):$(IMAGE_TAG)$(IMAGE_SUFFIX) -f e2e-tests/Dockerfile .
	$(if $(IMAGE_SUFFIX),,docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX))

test:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest $(PYTEST_ARGS)

test-unit: reinit ## Unit tests only; no stack or external services
	.venv/bin/pytest tests/unit $(PYTEST_ARGS)

# MODULE is a pytest marker expression, so it may be `a or b`.
test-module:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest -m "$(MODULE)" $(PYTEST_ARGS)

test-container-module:
	docker run --rm -it \
		--network=market \
		-e ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
		-e CONFIG_DIRECTORY=/app/config \
		-v $(CONFIG_DIRECTORY):/app/config:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		.venv/bin/pytest -m "$(MODULE)" $(PYTEST_ARGS)

# -----------------------------------------------------------------------
# Tests — buyer machine (in-network, realistic two-machine topology)
# -----------------------------------------------------------------------
# Runs the buyer-side e2e from a one-shot container attached to the seller's
# compose network, so discovery resolves the registry-advertised seller URL
# (bob-storefront:8001) and the `market` subprocess reaches it directly — no
# host port-forward or --seller override. Uses `docker run` (not `compose
# run`) so it works under daemonless podman, where the docker-compose
# provider can't reach a daemon.
#
# Prereqs: a lane's stack is up and the test image is built; a lane target
# below does both, and this target alone reruns markers against its stack.
#
# NETWORK defaults to the VM lane project's default network; each lane target
# passes its own.
NETWORK ?= simple-market-service_default
BUYER_MODULE ?= e2e_deal_buyer_cli or e2e_buy
# The VM lane's scenarios. `e2e_alkahest_escrow_codecs` and
# `e2e_alkahest_trusted_oracle` need only the chain and its funded buyer and
# seller wallets, and stay here; `multi_registry` reads VM's two registries;
# `e2e_non_erc20_settlement` settles native-token and ERC1155 escrows against
# the dev chain's own deployments. `e2e_vm_real_provisioning` is in no lane: it
# provisions on a real KVM host an operator provides, which the pipeline never
# has, and runs from the operator's machine through `test-module`.
E2E_MODULE ?= e2e_vm_payment_deal or e2e_vm_payment_purchase or e2e_deal or e2e_deal_buyer_cli or e2e_buy or multi_registry \
              or e2e_compute_dynamic_listings or e2e_alkahest_escrow_codecs \
              or e2e_alkahest_trusted_oracle \
              or e2e_listing_shapes or e2e_vm_introduction \
              or e2e_non_erc20_settlement
# The API-credit lane's scenarios. The payment deal runs against the lane's
# payments double.
E2E_APICREDITS_MODULE ?= e2e_credits_deal or e2e_credits_payment_deal
# The bare-metal lane's scenarios. `e2e_bare_metal_deal` is in neither lane: it
# needs a real whole host to SSH into, which the pipeline never has.
E2E_BARE_METAL_MODULE ?= e2e_bare_metal_publication or e2e_bare_metal_introduction \
                         or e2e_bare_metal_unbacked_introduction or e2e_bare_metal_mock_deal \
                         or e2e_bare_metal_payment_deal

# The runner's profiles, from config/: each lane target layers the shared
# payments profile and its own, `docker,payments-lane,<lane>-lane`, so the
# payment scenarios reach the lane's payments double; unset, the runner has no
# payments target, as a run against none does. A rerun against a lane's stack
# passes that lane's list. The lane CA is mounted where config-payments-lane.yml's
# ca_bundle_path names it; nothing else reaches the runner's environment.
RUNNER_PROFILES ?= docker

test-buyer-machine:
	docker run --rm \
		--network=$(NETWORK) \
		-e ACTIVE_PROFILES=$(RUNNER_PROFILES) \
		-e CONFIG_DIRECTORY=/app/config \
		-v $(abspath $(CURDIR)/../tools/lane-double-controls/tls/lane-ca.pem):/run/payments-lane-double/lane-ca.pem:ro \
		-v $(CURDIR)/tests:/app/tests:ro \
		-v $(CURDIR)/src:/app/src:ro \
		-v $(CURDIR)/config:/app/config:ro \
		-v $(CURDIR)/conftest.py:/app/conftest.py:ro \
		-v $(CURDIR)/pyproject.toml:/app/pyproject.toml:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		.venv/bin/pytest -m "$(BUYER_MODULE)" $(PYTEST_ARGS)

# -----------------------------------------------------------------------
# Tests — CI (HTML report, no colour, exit-on-first-fail)
# -----------------------------------------------------------------------

test-ci:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest \
		--html=pytest-report.html \
		--self-contained-html \
		--no-header \
		-p no:cacheprovider \
		$(PYTEST_ARGS)

# -----------------------------------------------------------------------
# Tests — end-to-end lanes
# -----------------------------------------------------------------------
# Each lane is one market domain's stack, as a compose project of its own, so
# its network and volumes never mix with another lane's: `test-e2e-<lane>`
# takes its stack down, builds the images it runs, brings it up, and runs the
# lane's markers from the test image on its network under the lane's runner
# profiles. `e2e-<lane>-down` and `e2e-<lane>-logs` are the one other place each
# lane's files and project are named; the pipeline collects logs and tears down
# through them.
#
# A lane target names only its Compose files and project, and the run's
# provisioning mode. Every value the stack reads is in a committed file -- the
# overlays, the registry and site profiles, the secret overlays -- which is what
# lets a lane run without repository secrets; see dev-env/identities/README.md.
#
# The base stacks are assembled by `include`, which resolves each included
# file's relative paths against that file's own directory; the development
# bindings are layered with `-f`, because an including file cannot redefine a
# service it imported. Each project is named explicitly, so a local run and the
# pipeline share one network name whatever the checkout directory is called.

# PROVISIONING_MODE, `mock` unless the run says `real`, is exported to Compose,
# which gives it to the provisioning services as their last profile; anything
# else is refused before a stack is touched.
PROVISIONING_MODE ?= mock
export PROVISIONING_MODE
E2E_REQUIRE_PROVISIONING_MODE = $(if $(filter mock real,$(PROVISIONING_MODE)),,$(error PROVISIONING_MODE must be mock or real, not '$(PROVISIONING_MODE)'))

# Bring a lane's stack up. On failure, print the state and each container's
# output *here*, in the failing step: `up --wait` reports only which container
# went unhealthy, never why, and leaving it to the pipeline's log collection
# puts the answer in an artifact that has to be downloaded separately.
# $(1): the compose arguments.
define e2e_up
docker compose $(1) up -d --wait \
	|| { \
	  echo "::group::compose ps"; \
	  docker compose $(1) ps -a; \
	  echo "::endgroup::"; \
	  for svc in $$(docker compose $(1) ps -a --services); do \
	    echo "::group::logs $$svc"; \
	    docker compose $(1) logs --no-color --tail=120 "$$svc" || true; \
	    echo "::endgroup::"; \
	  done; \
	  exit 1; \
	}
endef

# Each lane runs the payments lane double (compose.payments-double.yml), and its
# payment storefronts settle against it. Once the stack is up, each storefront
# checks its payments access from its own container -- its configuration, its CA
# mount and its secret overlay's key -- by an authenticated read of the seller's
# own balance at the double, and a failed check fails the lane by name before any
# scenario runs, rather than leaving the payment scenarios to fail one by one. The
# check prints one JSON line naming the step that failed. The seller's account
# comes from the double's fixtures. $(1): the compose arguments; $(2): the
# storefront service; $(3): its command.
PAYMENTS_LANE_ENV := python3 -I $(abspath $(CURDIR)/../tools/payments-lane-double/scripts/lane_env.py)
define e2e_check_payments
docker compose $(1) exec -T $(2) \
	$(3) check-payments --account "$$($(PAYMENTS_LANE_ENV) seller-account)" \
	|| { echo "::error::$(2) cannot use the lane's payments double; its check-payments line above names the step" >&2; exit 1; }
endef

# The stacks run one after another, never side by side on one host: each names
# its chain container `anvil` and publishes fixed host ports (8545 in every
# stack; 8080 and 8081 in the VM and bare-metal stacks). The order is a recipe
# of recursive calls, not a list of prerequisites, because `make -j` runs a
# target's prerequisites concurrently and GNU Make 4.3 has no `.WAIT`. The
# pipeline runs each lane as a job of its own instead.
test-e2e:
	$(MAKE) test-e2e-vm
	$(MAKE) e2e-vm-down
	$(MAKE) test-e2e-bare-metal
	$(MAKE) e2e-bare-metal-down
	$(MAKE) test-e2e-apicredits

# VM lane: Bob's and Alice's storefronts and provisioning authorities, the two
# VM registries, the payments double, and the dev chain. Bob settles payments
# against the double; Alice does not.
E2E_VMS_PROJECT := simple-market-service
E2E_VMS_COMPOSE := -p $(E2E_VMS_PROJECT) -f compose.vms.yml -f compose.vms-local.yml \
	-f compose.payments-double.yml -f compose.vms-lane.yml

test-e2e-vm:
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	cd .. && docker compose $(E2E_VMS_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-vm
	cd .. && $(call e2e_up,$(E2E_VMS_COMPOSE))
	cd .. && $(call e2e_check_payments,$(E2E_VMS_COMPOSE),bob-storefront,market-storefront)
	$(MAKE) test-buyer-machine NETWORK=$(E2E_VMS_PROJECT)_default BUYER_MODULE="$(E2E_MODULE)" \
		RUNNER_PROFILES=docker,payments-lane,vms-lane

e2e-vm-down:
	cd .. && docker compose $(E2E_VMS_COMPOSE) down -v --remove-orphans

e2e-vm-logs:
	@cd .. && docker compose $(E2E_VMS_COMPOSE) logs --no-color

# Bare-metal lane: one site, the bare-metal storefront, its registry, the
# payments double, and the dev chain; the storefront runs its development
# configuration (domains/bare_metal/storefront/storefront.dev.toml and its
# secrets overlay); see compose.bare-metal-local.yml.
E2E_BARE_METAL_PROJECT := simple-market-bare-metal
E2E_BARE_METAL_COMPOSE := -p $(E2E_BARE_METAL_PROJECT) \
	-f compose.bare-metal.yml -f compose.dev.yml \
	-f compose.payments-double.yml -f compose.bare-metal-local.yml

test-e2e-bare-metal:
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	cd .. && docker compose $(E2E_BARE_METAL_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-bare-metal
	cd .. && $(call e2e_up,$(E2E_BARE_METAL_COMPOSE))
	cd .. && $(call e2e_check_payments,$(E2E_BARE_METAL_COMPOSE),bare-metal-storefront,bare-metal-storefront)
	$(MAKE) test-buyer-machine NETWORK=$(E2E_BARE_METAL_PROJECT)_default BUYER_MODULE="$(E2E_BARE_METAL_MODULE)" \
		RUNNER_PROFILES=docker,payments-lane,bare-metal-lane

e2e-bare-metal-down:
	cd .. && docker compose $(E2E_BARE_METAL_COMPOSE) down -v --remove-orphans

e2e-bare-metal-logs:
	@cd .. && docker compose $(E2E_BARE_METAL_COMPOSE) logs --no-color

# API-credit lane: the credits registry, service, storefront, and sample app,
# the lane's own compute-schema registry, the payments double, and the dev
# chain; see compose.apicredits-lane.yml.
E2E_APICREDITS_PROJECT := simple-market-apicredits
E2E_APICREDITS_COMPOSE := -p $(E2E_APICREDITS_PROJECT) -f compose.apicredits.yml \
	-f compose.apicredits-local.yml -f compose.payments-double.yml -f compose.apicredits-lane.yml

test-e2e-apicredits:
	@$(E2E_REQUIRE_PROVISIONING_MODE)
	cd .. && docker compose $(E2E_APICREDITS_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-apicredits
	cd .. && $(call e2e_up,$(E2E_APICREDITS_COMPOSE))
	cd .. && $(call e2e_check_payments,$(E2E_APICREDITS_COMPOSE),credits-storefront,apicredits-storefront)
	$(MAKE) test-buyer-machine NETWORK=$(E2E_APICREDITS_PROJECT)_default BUYER_MODULE="$(E2E_APICREDITS_MODULE)" \
		RUNNER_PROFILES=docker,payments-lane,apicredits-lane

e2e-apicredits-down:
	cd .. && docker compose $(E2E_APICREDITS_COMPOSE) down -v --remove-orphans

e2e-apicredits-logs:
	@cd .. && docker compose $(E2E_APICREDITS_COMPOSE) logs --no-color
