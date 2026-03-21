# Rollback Audit

## Goal

Audit the documented rollback and failure-handling path.

## Inputs

- `docs/standup/canary.md`
- `docs/e2e-runbook.md`
- `docs/production-canary.md`

## Procedure

1. Verify that failed canaries have a documented cleanup path for jobs, orders, and VMs.
2. Confirm the rollback docs preserve enough identifiers for incident review.
3. Flag every missing reclamation or retry-precondition step.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the rollback path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
