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

.PHONY: build venv test test-e2e test-e2e-vm test-e2e-bare-metal e2e-vm-down

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
# Prereqs: the stack is up (`docker compose up -d`) and the e2e-tests
# image is rebuilt with the buyer wheel (`make build` at the repo root, then
# `make -C e2e-tests build`).
#
# NETWORK defaults to the compose project's default network
# (<repo-dir>_default). Override if your project name differs.
NETWORK ?= simple-market-service_default
BUYER_MODULE ?= e2e_deal_buyer_cli or e2e_buy
E2E_MODULE ?= e2e_deal or e2e_deal_buyer_cli or e2e_buy or multi_registry \
              or e2e_compute_dynamic_listings or e2e_alkahest_escrow_codecs \
              or e2e_credits_deal or e2e_credits_payment_deal or e2e_listing_shapes or e2e_vm_introduction
# The bare-metal lane's scenarios. `e2e_bare_metal_deal` is in neither lane: it
# needs a real whole host to SSH into, which the pipeline never has.
E2E_BARE_METAL_MODULE ?= e2e_bare_metal_publication or e2e_bare_metal_introduction

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
# Tests — full local e2e stack
# -----------------------------------------------------------------------
# Rebuilds the runtime + test images, starts a clean compose stack, then runs
# the buyer-machine scenarios from inside the compose network. This target is
# intentionally heavier than test-module: it verifies the deployed images and
# clears persisted compose state before each run.
# Generated, never committed: the resolved paths of the committed development
# identities, in the form `docker compose --env-file` wants.
E2E_IDENTITY_ENV ?= $(CURDIR)/../.e2e-identities.env

# The base stack is assembled by `include`, which resolves each included file's
# relative paths against that file's own directory -- `domains/vms/compose.yml`
# and `domains/apicredits/compose.yml` need that and sit in different
# directories, so no single project directory could replace it. The development
# bindings are layered with `-f` because `include` refuses to let an including
# file redefine an imported service. See compose.local-identities.yml.
E2E_COMPOSE_FILES := -f docker-compose.yml -f compose.local-identities.yml

# Both lanes, one after the other. Each lane's stack runs its own `anvil`
# container under that fixed name, so the VM stack is taken down before the
# bare-metal stack comes up. CI runs the lanes as separate jobs instead.
test-e2e: test-e2e-vm e2e-vm-down test-e2e-bare-metal

e2e-vm-down:
	cd .. && docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) down -v --remove-orphans

test-e2e-vm:
	@# Every signer, wallet, buyer-path, and bearer-token value in the compose
	@# files is guarded with a required-variable form, so *any* compose
	@# subcommand that reads the config -- down as much as up -- refuses to run
	@# until all of them are set. They come from committed development values,
	@# which is what lets this run without repository secrets; see
	@# dev-env/identities/README.md.
	@#
	@# The env file is generated first and passed to every compose invocation
	@# below. Passing it only to `up` left `down` able to fail on the same
	@# interpolation, for a reason that has nothing to do with the run.
	@#
	@# The values reach compose through --env-file rather than an eval of
	@# captured make output: a recursive make implies -w and would print
	@# "Entering directory" into the capture, and compose reading the file
	@# itself has nothing to quote wrong.
	cd .. && $(MAKE) -s --no-print-directory e2e-dev-identities-env > "$(E2E_IDENTITY_ENV)"
	cd .. && docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) down -v --remove-orphans
	cd .. && $(MAKE) build-dev
	@# On failure, print the state and the container output *here*, in the
	@# failing step. `up --wait` reports only which container went unhealthy,
	@# never why: the reason is in that container's log. Leaving it to the
	@# `always()` collection step means the answer lands in an uploaded
	@# artifact that has to be downloaded separately, which is a slow loop for
	@# something the job log can carry.
	cd .. && docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) up -d --wait \
		|| { \
		  echo "::group::compose ps"; \
		  docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) ps -a; \
		  echo "::endgroup::"; \
		  for svc in $$(docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) ps -a --services); do \
		    echo "::group::logs $$svc"; \
		    docker compose --env-file "$(E2E_IDENTITY_ENV)" $(E2E_COMPOSE_FILES) logs --no-color --tail=120 "$$svc" || true; \
		    echo "::endgroup::"; \
		  done; \
		  exit 1; \
		}
	$(MAKE) test-buyer-machine BUYER_MODULE="$(E2E_MODULE)"

# -----------------------------------------------------------------------
# Bare-metal lane
# -----------------------------------------------------------------------
# One mock-profile site, the bare-metal storefront, its registry, and the dev
# chain, as a compose project of its own so its network and volumes never mix
# with the VM stack's. Every value comes from `make e2e-bare-metal-dev-env`,
# which generates the publication deadlines at each run; see
# compose.bare-metal-local.yml.
E2E_BARE_METAL_ENV ?= $(CURDIR)/../.e2e-bare-metal.env
E2E_BARE_METAL_PROJECT := simple-market-bare-metal
E2E_BARE_METAL_COMPOSE := -p $(E2E_BARE_METAL_PROJECT) \
	-f compose.bare-metal.yml -f compose.dev.yml -f compose.bare-metal-local.yml

test-e2e-bare-metal:
	cd .. && $(MAKE) -s --no-print-directory e2e-bare-metal-dev-env > "$(E2E_BARE_METAL_ENV)"
	cd .. && docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) down -v --remove-orphans
	cd .. && $(MAKE) build-dev
	@# As in test-e2e-vm: on failure, print each container's own output here,
	@# in the failing step, rather than only in the uploaded artifact.
	cd .. && docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) up -d --wait \
		|| { \
		  echo "::group::compose ps"; \
		  docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) ps -a; \
		  echo "::endgroup::"; \
		  for svc in $$(docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) ps -a --services); do \
		    echo "::group::logs $$svc"; \
		    docker compose --env-file "$(E2E_BARE_METAL_ENV)" $(E2E_BARE_METAL_COMPOSE) logs --no-color --tail=120 "$$svc" || true; \
		    echo "::endgroup::"; \
		  done; \
		  exit 1; \
		}
	$(MAKE) test-buyer-machine NETWORK=$(E2E_BARE_METAL_PROJECT)_default BUYER_MODULE="$(E2E_BARE_METAL_MODULE)"
