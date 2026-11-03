export UV_PYTHON := $(or $(shell cat ../../../.python-version 2>/dev/null),$(error ../../../.python-version not found))

.PHONY: test
test:
	uv run pytest tests -q

.PHONY: native-ansible-gate
native-ansible-gate:
	bash scripts/native_ansible_gate.sh
