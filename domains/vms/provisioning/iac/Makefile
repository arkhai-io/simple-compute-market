.PHONY: validate validate-inventory validate-playbooks validate-tests validate-acceptance

validate: validate-inventory validate-playbooks validate-tests

validate-inventory:
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-inventory -i ansible/inventory/hosts --list >/dev/null

validate-playbooks:
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/frp/frp-server-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/frp/docker-app-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/host-kit/vm-setup.yaml --syntax-check
	ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts ansible/playbooks/single-tenant/vm-operations.yaml --syntax-check

validate-tests:
	python3 -m unittest discover -s tests -p 'test_*.py' -v

validate-acceptance:
	./scripts/run_acceptance_validation.sh --kvm-host "$${KVM_HOST:?set KVM_HOST to a kvm_hosts inventory alias}"
