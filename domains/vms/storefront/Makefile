# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= storefront
GIT_SUFFIX := $(shell git rev-parse --short=9 HEAD)
# Appended to the image's tag; the root Makefile's IMAGE_SUFFIX. A suffixed build
# is tagged per change alone: a commit tag would keep one image per validated commit.
IMAGE_SUFFIX ?=

# Path to the monorepo .dist/ wheel directory, relative to domains/vms/storefront/.
# Used by uv when resolving pure-Python internal packages
# (arkhai-kit-policy, arkhai-compute-provisioning) that are
# distributed as wheels rather than editable source installs. The
# Dockerfile passes --find-links /dist on the uv sync CLI instead;
# this variable is for local development only.
DIST_DIR ?= ../../../.dist
# The image records the wheelhouse's digest, its build's cache key, which a
# missing declared wheel refuses.
WHEELHOUSE_DIGEST_COMMAND = python3 ../../../scripts/wheelhouse_digest.py

.PHONY: build build-images build-no-cache deploy deploy-storefront init reinit migrate test test-unit test-integration

init: reinit ## Resolve deps from verified wheels and create .venv.

migrate: ## Apply the storefront's database migrations; serve refuses a database without them
	uv run --find-links $(DIST_DIR) market-storefront-migrate

reinit: ## Force-reinstall verified internal wheels.
	python3 ../../../scripts/uv_project.py reinit

# build deliberately does NOT depend on reinit. reinit drives a host-side
# `uv sync` that resolves the [rl] extra (incl. torch) across whatever
# uv considers "supported platforms" for this project — on x86_64 Linux
# that decides no torch wheel exists and aborts, blocking the Docker
# build that doesn't need torch at all (INSTALL_RL_DEPS=false). The
# Docker build has its own self-contained `uv sync --find-links /dist`
# inside the builder stage; the host venv isn't on its critical path.
# Run `make reinit` explicitly when iterating on internal wheels in the
# local venv.
build: build-images

build-images:
	digest=$$($(WHEELHOUSE_DIGEST_COMMAND)) && \
	docker build --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false --build-arg WHEELHOUSE_DIGEST=$$digest -t ${IMAGE_NAME}:${IMAGE_TAG}$(IMAGE_SUFFIX) ../../..
	$(if $(IMAGE_SUFFIX),,docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX))

build-no-cache: ## Full Docker cache bust — use when .dist/ changes are not picked up by build-images.
	digest=$$($(WHEELHOUSE_DIGEST_COMMAND)) && \
	docker build --no-cache --ulimit nofile=65536 -f Dockerfile --build-arg INSTALL_RL_DEPS=false --build-arg WHEELHOUSE_DIGEST=$$digest -t ${IMAGE_NAME}:${IMAGE_TAG}$(IMAGE_SUFFIX) ../../..
	$(if $(IMAGE_SUFFIX),,docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-$(GIT_SUFFIX))

test: reinit test-unit test-integration ## Run all tests

test-unit: ## Run unit tests
	uv run --find-links $(DIST_DIR) pytest tests/unit/ -v

test-integration: ## Run integration tests (no real infrastructure required — event queue seam)
	ENABLE_EVENT_QUEUE=true \
	AGENT_WALLET_ADDRESS="" \
	uv run --find-links $(DIST_DIR) pytest tests/integration/ -v

deploy: deploy-storefront

# Buyers are pure HTTP clients (the `market` CLI / arkhai_vms_buyer
# library); they don't run a storefront. Use `make deploy-storefront`
# to bring up the seller; run `market buy ...` from the host or another
# container against `http://bob-storefront:8001`.
deploy-storefront:
	docker run --rm -d --name bob-storefront \
	--network market -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	-e XDG_CONFIG_HOME=/etc \
	-v $(CURDIR)/storefront.bob.toml:/etc/arkhai/storefront.toml:ro \
	arkhai:storefront

deploy-dev:
	docker run --rm -it --name bob-storefront \
	--network market -p 8001:8001 \
	--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun:/dev/net/tun \
	-e XDG_CONFIG_HOME=/etc \
	-v $(CURDIR)/storefront.bob.toml:/etc/arkhai/storefront.toml:ro \
	arkhai:storefront

stop:
	docker kill bob-storefront

status:
	curl -s -X GET http://localhost:8001/api/v1/system/status -H "X-Admin-Key: test-api-key" | jq .
