.PHONY: validate validate-inventory validate-playbooks validate-tests validate-acceptance test

validate: validate-inventory validate-playbooks validate-tests

validate-inventory:
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-inventory -i ansible/inventory/hosts --list >/dev/null

validate-playbooks:
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/frp/frp-server-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/frp/docker-app-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/host-kit/vm-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/single-tenant/vm-operations.yaml --syntax-check

# uv-managed venv + pytest, consistent with every other package's test
# target in this repository -- previously ran through the bare system
# ``python3`` interpreter, the one test invocation in the repo that
# didn't go through ``uv run``.
test:
	uv run pytest tests -q

validate-tests: test

validate-acceptance:
	./scripts/run_acceptance_validation.sh --kvm-host "$${KVM_HOST:?set KVM_HOST to a kvm_hosts inventory alias}"
