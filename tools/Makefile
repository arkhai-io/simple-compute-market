# Images of the tools the lanes and the local release run beside the market. Each
# builds from the repository root, so its Dockerfile can copy the wheelhouse its
# lock resolves from; none is pushed. The root's `make build-tools` runs `build`.

IMAGE_SUFFIX ?=
REPO_ROOT := ..

.PHONY: build build-payments-lane-double build-mediation-lane-double

build: build-payments-lane-double build-mediation-lane-double ## Build every lane double's image

# The lanes' payments double.
build-payments-lane-double: ## Build the payments double's image
	docker build --ulimit nofile=65536:65536 \
		-f payments-lane-double/Dockerfile \
		-t arkhai:payments-lane-double$(IMAGE_SUFFIX) $(REPO_ROOT)

# The lanes' mediation double.
build-mediation-lane-double: ## Build the mediation double's image
	docker build --ulimit nofile=65536:65536 \
		-f mediation-lane-double/Dockerfile \
		-t arkhai:mediation-lane-double$(IMAGE_SUFFIX) $(REPO_ROOT)
