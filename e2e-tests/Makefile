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

build: build-images

build-images: reinit
	cd .. && docker build -t $(IMAGE_NAME):$(IMAGE_TAG) -f e2e-tests/Dockerfile .
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)

test:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest $(PYTEST_ARGS)

test-unit: reinit ## Unit tests only; no stack or external services
	.venv/bin/pytest tests/unit $(PYTEST_ARGS)

test-module:
	ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
	CONFIG_DIRECTORY=$(CONFIG_DIRECTORY) \
	.venv/bin/pytest -m $(MODULE) $(PYTEST_ARGS)

test-container-module:
	docker run --rm -it \
		--network=market \
		-e ACTIVE_PROFILES=$(ACTIVE_PROFILES) \
		-e CONFIG_DIRECTORY=/app/config \
		-v $(CONFIG_DIRECTORY):/app/config:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		.venv/bin/pytest -m $(MODULE) $(PYTEST_ARGS)

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
# The VM lane's scenarios. `e2e_alkahest_escrow_codecs` needs only the chain and
# stays here; `multi_registry` reads VM's two registries.
E2E_MODULE ?= e2e_deal or e2e_deal_buyer_cli or e2e_buy or multi_registry \
              or e2e_compute_dynamic_listings or e2e_alkahest_escrow_codecs \
              or e2e_listing_shapes or e2e_vm_introduction
# The API-credit lane's scenarios. The payment deal is blocked without a
# payments target and skips naming it.
E2E_APICREDITS_MODULE ?= e2e_credits_deal or e2e_credits_payment_deal
# The bare-metal lane's scenarios. `e2e_bare_metal_deal` is in neither lane: it
# needs a real whole host to SSH into, which the pipeline never has.
E2E_BARE_METAL_MODULE ?= e2e_bare_metal_publication or e2e_bare_metal_introduction \
                         or e2e_bare_metal_mock_deal

test-buyer-machine:
	docker run --rm \
		--network=$(NETWORK) \
		-e ACTIVE_PROFILES=docker \
		-e CONFIG_DIRECTORY=/app/config \
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
# writes the lane's environment file, takes its stack down, builds the images
# it runs, brings it up, and runs the lane's markers from the test image on its
# network. `e2e-<lane>-down` and `e2e-<lane>-logs` are the one other place each
# lane's files, project, and environment file are named; the pipeline collects
# logs and tears down through them.
#
# Every signer, wallet, buyer-path, and bearer-token value in the compose files
# is guarded with a required-variable form, so *any* compose subcommand that
# reads the config -- down as much as up -- refuses to run until all of them
# are set. They come from committed development values, which is what lets a
# lane run without repository secrets; see dev-env/identities/README.md. The
# environment file is generated first and passed to every compose invocation,
# and it is a file rather than an eval of captured make output: a recursive
# make implies -w and would print "Entering directory" into the capture, and
# compose reading the file itself has nothing to quote wrong. Down and logs
# write it only when no run has, since the bare-metal file carries deadlines
# generated at each run. `PROVISIONING_MODE` reaches the environment targets
# unchanged; see the root Makefile.
#
# The base stacks are assembled by `include`, which resolves each included
# file's relative paths against that file's own directory; the development
# bindings are layered with `-f`, because an including file cannot redefine a
# service it imported. Each project is named explicitly, so a local run and the
# pipeline share one network name whatever the checkout directory is called.

# Bring a lane's stack up. On failure, print the state and each container's
# output *here*, in the failing step: `up --wait` reports only which container
# went unhealthy, never why, and leaving it to the pipeline's log collection
# puts the answer in an artifact that has to be downloaded separately.
# $(1): the environment file; $(2): the compose arguments.
define e2e_up
docker compose --env-file "$(1)" $(2) up -d --wait \
	|| { \
	  echo "::group::compose ps"; \
	  docker compose --env-file "$(1)" $(2) ps -a; \
	  echo "::endgroup::"; \
	  for svc in $$(docker compose --env-file "$(1)" $(2) ps -a --services); do \
	    echo "::group::logs $$svc"; \
	    docker compose --env-file "$(1)" $(2) logs --no-color --tail=120 "$$svc" || true; \
	    echo "::endgroup::"; \
	  done; \
	  exit 1; \
	}
endef

# Write a lane's environment file only if no run has. $(1): the file;
# $(2): the root Makefile's environment target.
e2e_env_if_missing = test -f "$(1)" || $(MAKE) -s --no-print-directory $(2) > "$(1)"

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
# VM registries, and the dev chain.
E2E_VMS_ENV ?= $(CURDIR)/../.e2e-vms.env
E2E_VMS_PROJECT := simple-market-service
E2E_VMS_COMPOSE := -p $(E2E_VMS_PROJECT) -f compose.vms.yml -f compose.vms-local.yml

test-e2e-vm:
	cd .. && $(MAKE) -s --no-print-directory e2e-vms-dev-env > "$(E2E_VMS_ENV)"
	cd .. && docker compose --env-file "$(E2E_VMS_ENV)" $(E2E_VMS_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-vm
	cd .. && $(call e2e_up,$(E2E_VMS_ENV),$(E2E_VMS_COMPOSE))
	$(MAKE) test-buyer-machine NETWORK=$(E2E_VMS_PROJECT)_default BUYER_MODULE="$(E2E_MODULE)"

e2e-vm-down:
	cd .. && $(call e2e_env_if_missing,$(E2E_VMS_ENV),e2e-vms-dev-env)
	cd .. && docker compose --env-file "$(E2E_VMS_ENV)" $(E2E_VMS_COMPOSE) down -v --remove-orphans

e2e-vm-logs:
	@cd .. && $(call e2e_env_if_missing,$(E2E_VMS_ENV),e2e-vms-dev-env)
	@cd .. && docker compose --env-file "$(E2E_VMS_ENV)" $(E2E_VMS_COMPOSE) logs --no-color

# Bare-metal lane: one site, the bare-metal storefront, its registry, and the
# dev chain. Every value comes from `make e2e-bare-metal-dev-env`, which
# generates the publication deadlines at each run; see
# compose.bare-metal-local.yml.
E2E_BARE_METAL_ENV ?= $(CURDIR)/../.e2e-bare-metal.env
E2E_BARE_METAL_PROJECT := simple-market-bare-metal
E2E_BARE_METAL_COMPOSE := -p $(E2E_BARE_METAL_PROJECT) \
	-f compose.bare-metal.yml -f compose.dev.yml -f compose.bare-metal-local.yml

test-e2e-bare-metal:
	cd .. && $(MAKE) -s --no-print-directory e2e-bare-metal-dev-env > "$(E2E_BARE_METAL_ENV)"
	cd .. && docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-bare-metal
	cd .. && $(call e2e_up,$(E2E_BARE_METAL_ENV),$(E2E_BARE_METAL_COMPOSE))
	$(MAKE) test-buyer-machine NETWORK=$(E2E_BARE_METAL_PROJECT)_default BUYER_MODULE="$(E2E_BARE_METAL_MODULE)"

e2e-bare-metal-down:
	cd .. && $(call e2e_env_if_missing,$(E2E_BARE_METAL_ENV),e2e-bare-metal-dev-env)
	cd .. && docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) down -v --remove-orphans

e2e-bare-metal-logs:
	@cd .. && $(call e2e_env_if_missing,$(E2E_BARE_METAL_ENV),e2e-bare-metal-dev-env)
	@cd .. && docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) logs --no-color

# API-credit lane: the credits registry, service, storefront, and sample app,
# the lane's own compute-schema registry, and the dev chain; see
# compose.apicredits-lane.yml.
E2E_APICREDITS_ENV ?= $(CURDIR)/../.e2e-apicredits.env
E2E_APICREDITS_PROJECT := simple-market-apicredits
E2E_APICREDITS_COMPOSE := -p $(E2E_APICREDITS_PROJECT) -f compose.apicredits.yml \
	-f compose.apicredits-local.yml -f compose.apicredits-lane.yml

test-e2e-apicredits:
	cd .. && $(MAKE) -s --no-print-directory e2e-apicredits-dev-env > "$(E2E_APICREDITS_ENV)"
	cd .. && docker compose --env-file "$(E2E_APICREDITS_ENV)" $(E2E_APICREDITS_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-e2e-apicredits
	cd .. && $(call e2e_up,$(E2E_APICREDITS_ENV),$(E2E_APICREDITS_COMPOSE))
	$(MAKE) test-buyer-machine NETWORK=$(E2E_APICREDITS_PROJECT)_default BUYER_MODULE="$(E2E_APICREDITS_MODULE)"

e2e-apicredits-down:
	cd .. && $(call e2e_env_if_missing,$(E2E_APICREDITS_ENV),e2e-apicredits-dev-env)
	cd .. && docker compose --env-file "$(E2E_APICREDITS_ENV)" $(E2E_APICREDITS_COMPOSE) down -v --remove-orphans

e2e-apicredits-logs:
	@cd .. && $(call e2e_env_if_missing,$(E2E_APICREDITS_ENV),e2e-apicredits-dev-env)
	@cd .. && docker compose --env-file "$(E2E_APICREDITS_ENV)" $(E2E_APICREDITS_COMPOSE) logs --no-color
