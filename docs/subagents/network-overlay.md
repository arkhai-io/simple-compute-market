# Network Overlay Audit

## Goal

Audit the ZeroTier and FRP overlay requirements used by the deployed stack.

## Inputs

- `docs/standup/zerotier-frp.md`
- `README.md`
- `compute-provisioning-iac/README.md`

## Procedure

1. Verify controller setup, member authorization, FRP credential flow, and overlay reachability assumptions.
2. Confirm which services join ZeroTier directly and which use FRP.
3. Flag every missing authorization, DNS, or firewall step.
4. Do not assume prior chat context.

## Output Contract

- pass/fail judgment for the overlay path
- file/line references for every gap
- blockers
- missing commands, env files, or verification steps
