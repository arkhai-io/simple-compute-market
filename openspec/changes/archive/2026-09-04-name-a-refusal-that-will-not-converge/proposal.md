## Why

The `us_bank_transfer.v1` reclaim lane reports `convergence_timeout` at stage
`marketplace_lifecycle` after three minutes, naming nothing about why the
authority refused. Observed on a development run against Stripe test mode: the
stack came up healthy, the provider was ready, loopback webhooks verified, and
the run still ended with `refund: null` and a diagnostic that says only that a
stage did not converge.

`request_eligible_pretransfer_refund`
(`e2e-tests/tests/e2e/roles/scenarios/vms/hosted/network.py:795-809`) retries any
`409` or `503` for 180 seconds and then raises `TimeoutError("eligible hosted
refund did not converge")`. The authority's refusals in that range are not all
transient:

| authority code | status | nature |
| --- | --- | --- |
| `operation_conflict` | 409 | transient — lost the collect-versus-reclaim reservation |
| `reversal_unsupported` | 409 | permanent — the accepted profile forbids this reversal kind |
| `funding_relation_missing` | 503 | permanent for a push — no `checkout` or `payment_intent` relation exists |

So a refusal that can never succeed is retried a hundred times and then reported
as a timeout with its cause discarded. The caller cannot distinguish "the
authority is still working" from "the authority will never do this", and the
operator reading the evidence learns neither.

This matters most for `us_bank_transfer.v1` specifically. `config.py:108-113` in
the authority gives that profile the exact reversal policy `(RETURN,)`, while
`card.v1` and `us_ach_debit.v1` get `(CANCEL, REFUND)` — a push transfer cannot
be pulled back, so its only reversal is a fresh outbound payment. The reclaim
path also requires a `funding_provider_relations` row of kind `checkout` or
`payment_intent` (`authority.py:4538-4550`), which is a pull-funding shape. Which
of those two the lane actually hit is exactly what the swallowed status code
would have said, and exactly what the timeout threw away.

## What Changes

- The eligible-refund wait distinguishes a refusal it may retry from one it may
  not. `operation_conflict` remains retryable, because losing a compare-and-set
  race is the condition the wait exists for. A refusal the authority states as
  permanent ends the wait immediately and is reported with its own code.
- A refusal that ends the wait is carried into the run's diagnostic rather than
  replaced by `convergence_timeout`. The stage stays accurate; the cause stops
  being lost.
- A genuine timeout continues to be a timeout, and says what it was last
  refused with, so an exhausted retry is distinguishable from one that never
  received an answer at all.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: the Stripe-backed hosted evidence lane reports an
  authority refusal it cannot retry as that refusal, rather than as a
  convergence timeout in a later stage.

## Impact

- **Code**: `e2e-tests/tests/e2e/roles/scenarios/vms/hosted/network.py`
  (`request_eligible_pretransfer_refund`), and the driver's diagnostic
  construction in `e2e-tests/src/hosted_real_stripe/driver.py`.
- **Evidence**: the diagnostic gains the refusing code for this path. No
  evidence-schema version change is required to carry a code that already
  exists in the authority's error body.
- **Not established by this change.** Whether `us_bank_transfer.v1` reclaim can
  converge at all is a separate question this change makes answerable rather
  than answers. The profile's `(RETURN,)` policy and the reclaim path's
  requirement of a pull-funding relation may be genuinely incompatible, in
  which case the correct outcome is a named, immediate refusal — which is what
  this change produces — and any further work belongs to the authority.

### Non-Goals

- No change to which reversal kind the authority selects, to the per-profile
  reversal policy, or to the collect-versus-reclaim exclusion.
- No retry-count or timeout tuning; the defect is what the wait cannot
  distinguish, not how long it waits.
- No new authority endpoint, and no marketplace-side construction of a provider
  reversal.
