## ADDED Requirements

### Requirement: Deterministic provider dispatch idempotency

The Ansible fulfillment provider MUST submit create and teardown jobs
through the job service's contract-based deduplication path, with a
deterministic idempotency key derived from `allocation_id` and action
kind (`create` or `teardown`). A repeated dispatch for the same
allocation and action MUST return the originally-submitted job rather
than submitting a duplicate.

This is distinct from and does not replace `pools-3`'s "Idempotent
fulfillment identity" requirement, which governs whether
`FulfillmentService.create`/`teardown` accept or reject a retried
*request* (equivalent vs. conflicting, at the `allocation_id` boundary).
This requirement governs whether an *accepted* request's dispatch to the
underlying job runner is itself safe to retry — the layer below
`FulfillmentService`, exercised specifically by the durable
`dispatch_pending` recovery sweep this change introduces (see
`design.md`, "`SettlementRecord` shape" and "commit ↔ async-dispatch
failure window"). Prior to this change, `AnsibleFulfillmentProvider`
called the job service without a contract, bypassing its existing
`(allocation_id, action_kind, idempotency_key)` uniqueness constraint
entirely — confirmed by inspection, not assumed — so a recovery-driven
retry of a `dispatch_pending` `SettlementRecord` would have submitted a
second, duplicate Ansible job for the same physical operation.

#### Scenario: Recovery sweep retries a pending dispatch

- **WHEN** a `SettlementRecord` is found in `dispatch_pending` state by
  the periodic recovery sweep and `FulfillmentService.create` is retried
  for that allocation
- **THEN** at most one Ansible create job is ever dispatched for that
  allocation, and the retry observes the originally-submitted job rather
  than a new one

#### Scenario: Recovery sweep retries a pending teardown dispatch

- **WHEN** a `SettlementRecord` is found in `teardown_dispatch_pending`
  state by the periodic recovery sweep and `FulfillmentService.teardown`
  is retried for that allocation
- **THEN** at most one Ansible teardown job is ever dispatched for that
  allocation, and the retry observes the originally-submitted job rather
  than a new one

#### Scenario: Concurrent duplicate dispatch races

- **WHEN** two callers submit create (or two callers submit teardown)
  for the same allocation concurrently
- **THEN** the job service's uniqueness constraint resolves the race so
  both callers observe the same job identity and only one job is ever
  enqueued
