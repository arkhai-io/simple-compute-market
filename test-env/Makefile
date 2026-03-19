GIT_SUFFIX := $(shell git rev-parse --short HEAD)
FOUNDRY_VERSION := v1.5.1

build: build-images

build-images:
	docker build -f Dockerfile --build-arg FOUNDRY_VERSION=${FOUNDRY_VERSION} -t arkhai:test-env-$(GIT_SUFFIX) .

deploy:
	-docker network create market
	docker run -d --rm --network market --name test-env -p 8545:8545 -e ANVIL_IP_ADDR=0.0.0.0 arkhai:test-env-$(GIT_SUFFIX)

# tests that the test-env container is reachable and state was loaded. It should just dump a huge blob at you.
smoke:
	curl -s -X POST http://localhost:8545 -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"anvil_dumpState","params":[],"id":1}'