## Why

Interruptible publication, dry-run negotiation evaluation, reservation inspection, and dry-run/live lease truncation already exist, but operators lack one active-deal view, canonical typed client, settlement-split execution, reusable strategy runner, and a durable cross-authority evidence model.

## What Changes

- Add a seller control-plane view of active interruptible agreements with the identifiers needed to inspect authoritative site and settlement state.
- Add typed client models/methods for interruption planning and execution.
- Calculate, validate, submit, receipt, retry, and reconcile splitter settlement declarations rather than returning `splitter_declaration_pending`.
- Add a reference strategy runner with dry-run/live guards and explicit policy/version/config evidence.
- Define durable decision evidence separately from best-effort stage-event observability and reference authoritative site/chain state.
- State: **Retained and substantially narrowed to residual automation.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: Expose authenticated active-interruptible-agreement control and durable strategy decision evidence.
- `settlement-servicing`: Execute and reconcile settlement-split declarations for interruption.
- `site-capacity`: Keep lease truncation distinct from proven physical teardown/release state.

## Dependencies and Related Changes

- Uses existing interruption planning/truncation APIs and settlement servicing; does not depend on storefront database pruning.
- Must preserve POOLS-7 fulfillment/teardown authority when that cutover lands.

## Non-Goals

- Do not standardize a plugin vocabulary before multiple strategy implementations require it.
- Do not treat a storefront audit event as proof of site teardown or chain settlement completion.
- Do not make best-effort `stage_events` the sole durable decision record.

## Impact

Touches storefront admin APIs/persistence/client, a reference runner, settlement splitter integration, site-state correlation, auth/audit configuration, and HTTP/end-to-end tests.
