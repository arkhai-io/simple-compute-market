# Host Quickstart

This is the compute-host operator path for validating and optionally enrolling a
KVM host through the checked-in infrastructure automation.

The operator uses:

- `scripts/enroll_compute_host.py`

Who this is for:

- a compute-host operator validating or enrolling a real KVM host
- a coordinating agent/service that needs machine-readable readiness or
  enrollment artifacts

The wrapper is intentionally thin and builds on the existing IaC surface:

- `compute-provisioning-iac/ansible/inventory/hosts`
- `compute-provisioning-iac/scripts/run_acceptance_validation.sh`

## Required Inputs

- `--kvm-host` matching an alias in
  `compute-provisioning-iac/ansible/inventory/hosts`
- access to the checked-in Ansible inventory and playbooks
- optional `--run-acceptance` when you want the real acceptance path

The inventory contract is the source of truth for:

- `host_alias`
- `ansible_host`
- `ansible_user`
- `gpus`

## Check Ready

```bash
python scripts/enroll_compute_host.py check-ready \
  --kvm-host btc1
```

This runs the repo-local validation surface first:

- `validate-inventory`
- `validate-playbooks`
- `validate-tests`

If you want the heavier live path too, add `--run-acceptance`.

## Enroll

```bash
python scripts/enroll_compute_host.py enroll \
  --kvm-host btc1 \
  --run-acceptance
```

The enroll flow uses the same validation surface and then runs the real
acceptance runner through
`compute-provisioning-iac/scripts/run_acceptance_validation.sh`.

Optional inputs:

- `--vm-name` to control the acceptance VM name
- `--skip-host-kit` to skip the host-kit playbook
- `--extra-vars-file` for extra acceptance variables

## Output

The wrapper writes a structured host artifact that records:

- `host_alias`
- `ansible_host`
- `ansible_user`
- `gpus`
- whether acceptance ran
- the selected acceptance VM name

## Notes

- This is operator-facing and intentionally keeps the privileged IaC surface in
  one place.
- The current production entrypoint is the script wrapper above, not an
  installed `market host ...` subcommand yet.
- For agent or platform coordination, the resulting artifact aligns with the
  shared live role contracts.
