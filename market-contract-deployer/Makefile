GIT_SUFFIX := $(shell git rev-parse --short HEAD)

build: build-images

build-images:
	docker build -f Dockerfile --build-arg CONTRACTS_IMAGE=arkhai:contracts-$(GIT_SUFFIX) -t arkhai:market-contract-deployer-$(GIT_SUFFIX) .