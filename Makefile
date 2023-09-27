# Default if not provided.
PYTHON_VERSION ?= 3.11

.PHONY: build
build:
	@docker build --build-arg="PYTHON_VERSION=$(PYTHON_VERSION)" --output dist .
