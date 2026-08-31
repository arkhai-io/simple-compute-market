## 1. Shared projection surface

- [ ] 1.1 Add an incident projection helper to `kit/hosted-settlement` beside `hosted_projected_reason`, reading the incident from the status receipt and mechanism state and returning the authority's `incident_ref`, `kind`, and `evidence_digest` unchanged, or an explicit absence when the authority raised none. Verify with `cd kit && make test` covering: an incident present in the receipt, an incident present only in mechanism state, no incident at all, and an incident whose `state` field is not projected.
- [ ] 1.2 Add a delivery-consequence helper to the same module returning `fulfillment_blocked`, derived from the terminal outcome and `collection_state` using the same predicate `_terminal_requires_lease_truncation` reads, so the projection and the truncation decision cannot disagree. Verify with `cd kit && make test` covering: never fulfilled and terminal uncollected (blocked), fulfilled then torn down (blocked), post-collection loss with collection succeeded (not blocked), and an ordinary collected obligation (not blocked).
- [ ] 1.3 Export both helpers from `market_hosted_settlement.__init__` alongside `hosted_projected_reason` and verify `cd kit && make test` still passes with no import cycle introduced.
- [ ] 1.4 Add a canary test asserting neither helper can return a provider identifier, message, or payload from `EscrowResult`, matching the existing secret-free projection canaries. Verify it fails when a provider field is deliberately threaded through.

## 2. Domain projections

- [ ] 2.1 Project both fields from `hosted_settlement_status` in `domains/vms/storefront`, and verify with `make test-storefront` that a post-collection loss reports `manual_required` with the incident and `fulfillment_blocked` false, and a pre-collection return reports it true.
- [ ] 2.2 Project both fields from the API-credit storefront status payload and verify with `make test-apicredits` that the same obligation shape carries identical field names and values as the VM projection.
- [ ] 2.3 Project both fields from the bare-metal storefront status payload and verify with `make test-storefront` that all three domains agree, exercising the shared-surface scenario in the spec delta.

## 3. Bare-metal terminal path

- [ ] 3.1 Change the bare-metal `on_terminal` to request `callbacks.cleanup` only for a terminal state where cleanup is permitted — an uncollected one — mirroring the predicate `vms` uses, rather than for every non-`collected` state. Verify with a test in `domains/bare_metal/storefront/tests` that a post-collection loss raises no `BareMetalHostedLifecycleError` and requests no teardown, and that a pre-collection return still cleans up.
- [ ] 3.2 Add a regression test asserting the servicing worker's terminal callback logs no swallowed exception on a post-collection loss for any of the three domains, so the frozen-cleanup defect cannot return unnoticed. Verify with `cd kit && make test` and `make test-storefront`.

## 4. Harness capabilities

- [ ] 4.1 Implement `wait_authoritative_loss` on the real-Stripe marketplace object so the bridge stops answering `available: false`, polling the hosted status until the projection reports an incident or the lane's timeout expires. Verify with the e2e unit suite that the bridge dispatches it and that a marketplace lacking it still reports `ProcessUnavailable` rather than passing.
- [ ] 4.2 Implement `induce_test_ach_return` and `induce_test_post_collection_loss` against the producer's test-mode helpers. Verify with the e2e unit suite; if the released authority exposes no exact helper for either, leave that lane reporting `ProcessUnavailable` and record which one in this task rather than substituting an approximation.
- [ ] 4.3 Remove `_UNPROJECTED_LOSS_SCENARIOS` and its guard in `_require_lane_admitted`, and have `_loss_evidence` read the real projections instead of failing closed. Verify with the e2e unit suite that `ach_return` requires `fulfillment_blocked` and `post_collection_loss` requires `operator_incident_observed`, and that neither lane is excluded any more.
- [ ] 4.4 Verify with `make test-release-tooling` and the full package suites (`make test`) that nothing else read the withheld-lane set.

## 5. Qualification

- [ ] 5.1 Run both lanes under a development run against the real Stripe test account with `make hosted-stripe-test-local`, and verify each reaches `complete` with no diagnostic. A development run qualifies nothing; it proves the lanes before a release is spent on them.
- [ ] 5.2 Cut a marketplace release from the implementing commit, because a protected run executes the released commit, and verify the release names the signed producer version this source consumes.
- [ ] 5.3 Run both lanes under a protected run with `make hosted-stripe-test` and verify each reaches `complete`. This is the acceptance signal for the change.

## 6. Promotion

- [ ] 6.1 Update the `add-bare-metal-hosted-settlement` matrix note to record the two lanes as qualified with the protected run's evidence path, workflow run, and bound release, matching how the interactive `card.v1` lanes were recorded.
- [ ] 6.2 Sync the two modified requirements into `openspec/specs/settlement-servicing/spec.md` and verify `openspec validate --changes project-an-authoritative-funding-loss --strict` passes before archiving.
