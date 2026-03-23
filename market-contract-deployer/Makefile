IMAGE_NAME ?= arkhai
IMAGE_TAG  ?= contract-deployer
GIT_SUFFIX := $(shell git rev-parse --short HEAD)

build: build-images

build-images:
	docker build -f Dockerfile -t $(IMAGE_NAME):$(IMAGE_TAG) .
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG)-$(GIT_SUFFIX)
