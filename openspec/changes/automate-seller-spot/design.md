## Context

The storefront can publish interruptible listings, dry-run negotiation decisions, inspect site reservations, and dry-run or truncate a lease. Successful live interruption emits a basic stage event, but no active-agreement view or canonical client exists, dry runs are not durably recorded, splitter declarations remain pending, and no strategy runner exists. Site release and chain settlement are separate authorities.

## Goals / Non-Goals

**Goals:** complete residual control-plane, typed client, splitter execution, reference runner, and durable evidence.

**Non-Goals:** equate truncation with teardown/release, standardize premature plugins, or rely solely on best-effort logs.

## Decisions

- Build an authenticated read model referencing storefront agreement/listing, site reservation/fulfillment, and settlement identifiers without copying their authoritative state.
- Persist each strategy evaluation with stable decision ID, policy name/version/config digest, input snapshot references, selected action/reason, dry-run flag, and resulting operation IDs. Project it to stage events for observability.
- Execute interruption as resumable steps: validate current state, calculate/validate split, submit idempotently, record transaction/receipt, request lease truncation/teardown, and reconcile each authority independently.
- Provide a typed client and reference runner over public/admin APIs; strategy code never accesses storefront/site databases directly.
- Report partial states explicitly; `lease_truncated`, physical release, and splitter settlement are not one boolean transaction.

## Risks / Trade-offs

- **[Cross-authority partial failure]** → Persist step state and support idempotent reconciliation/repair.
- **[Strategy races lifecycle changes]** → Revalidate versions/terminal state before live action.
- **[Audit contains sensitive policy input]** → Store allowlisted evidence/digests and redact secrets.

## Permanent Documentation Promotion

Control/evidence belongs in `storefront-publication`; split execution in `settlement-servicing`; truncation versus release semantics in `site-capacity`/`physical-provisioning` architecture companions.
