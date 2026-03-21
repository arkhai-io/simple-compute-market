# Seller Agent Audit

## Goal

Audit the deployed seller agent path end to end.

## Inputs

- `docs/standup/agent-seller.md`
- `core/entrypoint.sh`
- `core/agent/scripts/register_onchain.py`
- `core/Dockerfile`

## Procedure

1. Verify env-file persistence, ZeroTier requirements, registration, and verification steps.
2. Confirm the seller-specific inventory expectations and handoff into resource seeding.
3. Flag every missing host mount, capability, or identity capture step.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the seller deployment path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
