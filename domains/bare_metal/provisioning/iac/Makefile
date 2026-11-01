export UV_PYTHON := $(or $(shell cat ../../../../.python-version 2>/dev/null),$(error ../../../../.python-version not found))
.PHONY: test

test:
	uv run pytest tests -q -m 'not native'
	@echo 'Native account/kernel cleanup checks omitted from the default suite.'
