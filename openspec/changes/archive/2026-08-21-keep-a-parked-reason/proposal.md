## Why

A real ACH lane against the Stripe test account parked with
`status='manual_required', funding_reason=None`. The settlement-servicing
specification already forbids that exactly: *"A `manual_required` projection
carrying no reason MUST NOT occur."*

The reason is not missing at the moment of parking — it is written correctly,
by the operation that parked the deal, into the mechanism state under
`manual_reason`. It is then deleted. Every operation writes the mechanism state
whole rather than merging, and a status poll builds its state from the
authority's current answer, which names no reason because the authority is
answering normally: what was refused was the collection, not the status. The
buyer polls continuously, so a parked reason survives roughly one poll
interval.

The result is worse than never recording it. An operator who looks quickly sees
the reason and an operator who looks later does not, and nothing distinguishes
"parked for a reason nobody recorded" from "parked for a reason since
overwritten".

## What Changes

- While an obligation is parked, the reason it was parked for survives every
  later write to its mechanism state. A write that names its own reason still
  wins; only the absence of one is filled.
- The reason is cleared when the park is cleared, not before.
- This is fixed once in the shared runtime rather than in each mechanism: the
  runtime is what owns the operation states that make an obligation parked, and
  what defines the key the reason is written under. An adapter answers for the
  authority's current view and cannot know the marketplace is still parked.

No requirement changes. This is a defect against a requirement already in
`settlement-servicing`, which is why this change carries `skip_specs: true`.

## Capabilities

### Modified Capabilities

None. See above.

## Impact

- `kit/settlement-runtime/src/market_settlement_runtime/runtime.py`
- Regression coverage in `kit/settlement-runtime/tests/unit/test_runtime.py`,
  written from the lane that produced the defect.
