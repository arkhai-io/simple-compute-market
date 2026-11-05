# Proposal

## Why

A hosted bare-metal commitment can provision successfully while its storefront
never records availability unless a buyer calls a fulfillment status or access
route. Issue #338 identifies this gap: lifecycle servicing must adopt delivery
without depending on the buyer to drive it.

## What Changes

- Adopt an existing bare-metal fulfillment through the ordinary servicing cycle,
  preserving evidence validation, admission, deadlines and exact resource identity.
- Verify the equivalent VM commitment-to-availability path without legacy buyer
  status polling; change it only if the regression demonstrates the same defect.
- Keep physical end recovery independent when readiness observation fails.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deal-lifecycle`: compute servicing adopts available fulfillment independently
  of buyer polling and never redelivers an ended deal.

## Impact

Bare-metal lifecycle composition and both compute storefronts' integration tests.
No wire, database, configuration, dependency or deployment break is intended.
Payment commands, dispute policy, provisioning placement and new timers are
non-goals. Buyer evidence-log validation is an independent correction.

## Permanent documentation impact

- [x] Existing subsystem specification: `deal-lifecycle`.
- [x] Companion architecture: `openspec/specs/deal-lifecycle/architecture.md`.
- [ ] Repository-wide architecture: existing ownership boundaries are unchanged.

### Knowledge to promote

The servicing owner adopts existing physical readiness through its domain's
validated delivery path before declaring non-delivery; buyer reads do not own
progress. Preserve deadline and end-service admission when adopting readiness.
