# Clean-Room Acceptance Checklist

## Scope

Use this checklist to confirm that a competent operator can start from
`docs/standup/overview.md`, follow the deployed runbooks, reach
`docs/production-canary.md`, and complete the validation loop in
`docs/e2e-runbook.md` without relying on tribal knowledge beyond the required
external credentials and infrastructure access.

## Required Inputs

Before treating the clean-room rerun as valid, capture:

- the exact repo revision under test
- the isolated environment identifier
- the host-local env bundle paths under `/etc/simple-market-service/`
- the external resources listed in `docs/standup/overview.md`
- the final canary runner log path (`prod-canary.log`)
- the release gate proof command that consumed that log

## Acceptance Checklist

1. Start from `docs/standup/overview.md` rather than from an ad hoc deployment note.
2. Follow the stand-up sequence in order and use the linked component runbooks for registry, provisioning, seller, buyer, and resource seeding.
3. Source the host-local canary env bundle and verify the same runner contract described in `docs/production-canary.md`.
4. Run the repo-side gates and the env-bundle validator before the live canary attempt.
5. Verify health, registration, and seller inventory from the same machine that will execute the canary.
6. Run the isolated canary either manually or through `.github/workflows/deployed-canary.yml`.
7. Preserve `prod-canary.log` and confirm it contains the emitted order IDs, provisioning job ID, and the final JSON payload.
8. Feed that proof into `python scripts/run_release_gate_checks.py --deployed-canary-log <path-to-prod-canary.log> ...`.
9. If the canary fails, execute `scripts/prod_canary_rollback.py --log-path <path-to-prod-canary.log>` and capture the cleanup result.
10. Record exact blockers. If none remain, explicitly note that the clean-room rerun passed.

## Evidence

Record the following before signoff:

- commit SHA:
- isolated environment:
- canary runner host:
- canary log path:
- release gate command:
- rollback command, if used:
- blocker summary:

Current repo-side rerun on 2026-03-21 found no repo-documentation blocker that
would prevent a competent operator from following the stand-up path.

Final isolated-canary signoff is recorded in
`docs/isolated-canary-signoff-2026-03-20.md`.
