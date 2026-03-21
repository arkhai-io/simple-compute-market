# IAC Host Kit Audit

## Goal

Audit the FRP and KVM host-kit setup path in `compute-provisioning-iac`.

## Inputs

- `compute-provisioning-iac/README.md`
- `compute-provisioning-iac/ansible/inventory/hosts`
- relevant playbook references in the README

## Procedure

1. Verify the documented phase order for FRP, KVM host setup, and provisioning deployment.
2. Confirm the inventory aliases and secret handoff requirements.
3. Flag every missing prerequisite, path drift, or host-state assumption.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the host-kit path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
