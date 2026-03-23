IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= test-env
GIT_SUFFIX := $(shell git rev-parse --short HEAD)
FOUNDRY_VERSION := v1.5.1

build: build-images

build-images:
	docker build -f Dockerfile --build-arg FOUNDRY_VERSION=${FOUNDRY_VERSION} -t $(IMAGE_NAME):$(IMAGE_TAG) .
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)

deploy:
	-docker network create market
	docker run -d --rm --network market --name anvil -p 8545:8545 -e ANVIL_IP_ADDR=0.0.0.0 $(IMAGE_NAME):$(IMAGE_TAG)

# tests that the test-env container is reachable and state was loaded. It should just dump a huge blob at you.
smoke:
	curl -s -X POST http://localhost:8545 -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"anvil_dumpState","params":[],"id":1}'