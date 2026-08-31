## Why

`settlement-servicing` already requires that a post-collection loss "project an incident/manual status" and that a return after fulfillment "order domain-owned VM teardown and capacity cleanup to convergence". The runtime does the state half of both and none of the projection half. The authority hands the marketplace a `FundingIncidentProjection` on every `EscrowResult`; the hosted adapter stores it in mechanism state and the public settlement payload drops it. So an obligation parked by a card dispute and an obligation parked by an operator review are indistinguishable from outside, and no consumer can tell that a terminal obligation took its capacity service back.

Two protected e2e lanes are withheld on exactly this. `ach_return` and `post_collection_loss` report `excluded` with `loss_projection_unimplemented`, because each asserts a projection nothing produces: `fulfillment_blocked` for the pre-collection return, `operator_incident_observed` for the post-collection loss. They are the last two `us_ach_debit.v1` lanes in the bare-metal matrix that no evidence can reach.

## What Changes

- The hosted settlement payload every domain projects gains the authority's incident: its reference, kind, and evidence digest, alongside the status and reason it already carries. The incident is provider-neutral vocabulary the authority owns, so it crosses the boundary as-is rather than being re-derived.
- A named `fulfillment_blocked` projection states whether delivery survived the loss. It is true when an obligation reached a terminal state that took capacity service back — whether fulfillment never committed or committed and was then torn down. It is not a promise that fulfillment was prevented; the runtime fulfills at authoritative funding, so a return usually arrives after a machine exists.
- A post-collection loss reports and keeps serving. `vms` already declines to truncate a lease once collection succeeded, deliberately and by its own docstring; that behaviour is confirmed as the requirement rather than treated as an omission. A dispute the buyer may yet win must not pull a running machine out from under them.
- `bare_metal` stops asking for a cleanup its own lifecycle refuses. Its `on_terminal` calls `callbacks.cleanup` for every non-`collected` state, and `cleanup` raises `collection cannot be excluded; physical cleanup is frozen` for a `collected` lifecycle; the servicing worker catches every terminal-callback exception into a log, so today a bare-metal post-collection loss ends as a swallowed error. It must take the same report-and-keep-serving path the requirement names.
- The real-Stripe harness gains the three marketplace capabilities its bridge already dispatches and nothing implements: `induce_test_ach_return`, `induce_test_post_collection_loss`, and `wait_authoritative_loss`. The withheld-lane guard is removed and both lanes assert against the new projections.

Non-goals, explicitly:

- No dispute policy, arbiter selection, or adjudication. Whether a dispute is contested and by whom stays with the authority, as `disburse-a-settlement-disposition` already put out of scope.
- No revocation of a delivered machine on a post-collection loss, in any domain.
- No operator incident *resolution*. The released client exposes no method for `/api/v1/operator/incidents/{ref}/resolve`; those routes are operator-facing and the marketplace's only route to a loss is `EscrowResult.incident`. Resolution stays with the authority's operator.
- No new state in the shared lifecycle. `manual_required` already carries the parked obligation; this change projects what put it there.
- No change to how a loss is detected. `_escrow_status` already reads post-collection risk correctly and is not touched.

## Capabilities

### New Capabilities

None. The behaviour this change completes is already required by `settlement-servicing`; what is missing is its observable projection.

### Modified Capabilities

- `settlement-servicing`: `Profile-specific reclaim and loss remain authority-owned` gains the requirement that the projected incident be readable — reference, kind, and evidence digest — rather than only implied by a `manual_required` status, and states that a post-collection loss leaves capacity service running in every adopting domain. `Hosted adapter validation and state projection` gains `fulfillment_blocked` as a projected field with a stated meaning, next to the stable parked reason it already requires every domain to project identically.

## Impact

- `kit/hosted-settlement`: the adapter's public projection helpers gain incident and blocked-delivery projections beside `hosted_projected_reason`, so no domain can build a status payload that omits them by forgetting to.
- `kit/settlement-runtime`: no lifecycle change. `terminal_risk_monitoring`, `_escrow_status`, and the `manual_required` states stay as they are.
- `domains/vms/storefront`, `domains/apicredits/storefront`, `domains/bare_metal/storefront`: each hosted status payload carries the two new fields from the shared helpers. `bare_metal`'s `on_terminal` stops requesting a frozen cleanup.
- `e2e-tests`: three new marketplace lifecycle capabilities, removal of `_UNPROJECTED_LOSS_SCENARIOS`, and `_loss_evidence` reading real projections instead of failing closed.
- **Wire compatibility:** additive only. Two new optional fields on the hosted settlement status payload; no field is renamed, retyped, or removed. No persistence change — the incident is already stored in mechanism state and the receipt.
- **Externally blocked:** nothing. Signed producer `v0.4.2` already carries `normalized-funding-reversal.v1`, `payer-return-instructions.v1`, and `operator-recovery-redaction.v1`, and `EscrowResult.incident` is on the response the marketplace already polls. This is consumer-side work throughout.
- **Deferred:** qualifying the two lanes needs a marketplace release cut from the implementing commit, since a protected run executes the released commit. The lanes pass under a development run first; the protected run is the acceptance signal and follows the release.
