# Support Quickstart

This quickstart packages the live support path for inspecting and cleaning up a
real market run. It is meant for an operator who needs to correlate order IDs,
job IDs, and VM targets without reconstructing the whole live run by hand.

Who this is for:

- a human support operator handling a broken or completed live run
- a coordinating agent/service that needs structured inspect and cleanup
  artifacts

This path assumes:

- the live isolated environment is already up
- you have a support context JSON with registry, provisioning, seller, and buyer
  identifiers
- the shared live contracts in `docs/standup/live-contracts.md` are in effect

## Required Inputs

- `context.json` from the live operator bundle
- seller and buyer order IDs
- optional job ID if you already know the matching create job

The support wrapper uses the same shared live contract as the rest of the
production-facing flows, so it records `order_id`, `job_id`, and `vm_target`
in a structured support artifact. The cleanup result also records
`reclaim_actions` for the destroy and undefine steps.

## 1. Inspect A Live Run

Inspect a live case and write a support artifact:

```bash
python scripts/run_market_support.py inspect \
  --context-path /tmp/market-human-buyer/context.json \
  --seller-order-id <seller-order-id> \
  --buyer-order-id <buyer-order-id>
```

If you already know the create job, pass `--job-id` to bypass job discovery.

The inspect artifact includes:

- the seller and buyer order statuses
- the matched provisioning job
- the VM host and target
- the canonical `request_url` and `auth_url`

## 2. Clean Up A Live Run

Close the orders and reclaim the VM:

```bash
python scripts/run_market_support.py cleanup \
  --context-path /tmp/market-human-buyer/context.json \
  --seller-order-id <seller-order-id> \
  --buyer-order-id <buyer-order-id> \
  --job-id <create-job-id>
```

If you omit `--job-id`, the support wrapper discovers the matching create job
from the live provisioning history.

The cleanup artifact includes:

- both order close results
- destroy and undefine job results
- the VM host and target
- the structured support correlation fields
- `reclaim_actions`

## Success Criteria

Treat the support path as successful only when all of the following are true:

- the inspect command produces a structured support artifact
- the support artifact correlates the order IDs, job ID, and VM target
- the cleanup command closes both orders and reclaims the VM
- the cleanup artifact records the reclaim actions

## Notes

- The support path is an operator role, not a buyer or seller role.
- Use the same `context.json` shape that the live operator bundle already
  produces.
- The shared live contracts define how support artifacts should be structured
  across order, job, and VM correlation.
- The current production entrypoint is the script wrapper above, not an
  installed `market support ...` subcommand yet.
