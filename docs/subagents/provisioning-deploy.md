# Provisioning Deploy Audit

## Goal

Audit the deployed async provisioning API and worker path.

## Inputs

- `docs/standup/provisioning.md`
- `async-provisioning-service/README.md`
- `async-provisioning-service/start.sh`
- `compute-provisioning-iac/README.md`

## Procedure

1. Verify the image source, env contract, Redis/DB requirements, and worker startup.
2. Confirm how `SSH_PRIVATE_KEY` and `MANAGEMENT_VARS_YAML` reach the container.
3. Flag every missing host path, auth requirement, or health check.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the deployed provisioning path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
