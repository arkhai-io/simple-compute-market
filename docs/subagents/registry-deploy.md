# Registry Deploy Audit

## Goal

Audit the deployed registry path end to end.

## Inputs

- `docs/standup/registry.md`
- `erc-8004-registry-py/README.md`
- `erc-8004-registry-py/Dockerfile`
- `.github/workflows/docker-build-push-erc8004-registry.yml`

## Procedure

1. Verify the image source, env contract, container launch, and health checks.
2. Confirm the docs distinguish local development from deployed execution.
3. Flag every missing secret, host path, or verification command.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the deployed registry path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
