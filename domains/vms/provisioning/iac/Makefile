# Every uv command in this Makefile uses the repository's declared Python version.
export UV_PYTHON := $(or $(shell cat ../../../../.python-version 2>/dev/null),$(error ../../../../.python-version not found))

.PHONY: validate validate-inventory validate-playbooks native-ansible-gate validate-tests validate-acceptance test

validate: validate-inventory validate-playbooks validate-tests

validate-inventory:
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-inventory -i ansible/inventory/ --list >/dev/null

# Every playbook's syntax check, from the one list the native Ansible gate also
# runs; it needs ansible-playbook on PATH.
validate-playbooks:
	scripts/validate_playbooks.sh

# The syntax checks and the tests that run shipped tasks through ansible-playbook,
# failing rather than skipping without ansible-core 2.17 to 2.19 and the
# ansible.posix json callback. The root `make test-provisioning-iac-native` runs
# it with the provisioning image's Ansible.
native-ansible-gate:
	scripts/native_ansible_gate.sh

# uv-managed venv + pytest, consistent with every other package's test
# target in this repository -- previously ran through the bare system
# ``python3`` interpreter, the one test invocation in the repo that
# didn't go through ``uv run``.
test:
	uv run pytest tests -q

validate-tests: test

validate-acceptance:
	./scripts/run_acceptance_validation.sh --kvm-host "$${KVM_HOST:?set KVM_HOST to a kvm_hosts inventory alias}"
