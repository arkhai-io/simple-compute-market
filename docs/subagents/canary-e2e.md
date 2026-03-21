# Canary E2E Audit

## Goal

Audit the live canary validation path from repo gates through cleanup.

## Inputs

- `docs/standup/canary.md`
- `docs/e2e-runbook.md`
- `docs/production-canary.md`
- `scripts/prod_canary_smoke.py`

## Procedure

1. Verify the gate sequence, live verification, smoke command, and success criteria.
2. Confirm the documented `--vm-host`, `CANARY_VM_HOSTS`, and SSH verification behavior.
3. Flag every missing input, cleanup step, or runner assumption.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the canary path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
