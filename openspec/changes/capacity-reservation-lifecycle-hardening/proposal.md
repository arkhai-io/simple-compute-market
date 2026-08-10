## Why

Three properties of the capacity reservation row hold up only at today's volume, where
a hold exists for each accepted-but-unsettled deal. All three were found during the
capacity-economics sweep (2026-08-06) and each is independently a defect.

**Holds placed during negotiation are not idempotent.** `reserve()` dedupes by
`deal_ref["escrow_uid"]`, and the requirement documenting that behavior explains it
closes the crash-retry double-reserve gap. But `_place_capacity_hold` passes
`deal_ref={"listing_id", "negotiation_id"}` and no `escrow_uid`, because no escrow
exists before settlement. The guard is skipped entirely, so a retried acceptance mints
a second reservation for the same negotiation. The protection the requirement describes
does not apply to the one caller that places holds.

**Expiry is a full scan on every ledger operation.** `_expire_stale_holds` runs ahead of
every `probe`, `reserve`, `commit`, and `release`; it loads every row in the `reserved`
state with a non-null `hold_expires_at`, then parses ISO-8601 strings and compares them
in Python. `state` is indexed, `hold_expires_at` is not, and a string timestamp cannot
be range-compared in the query, so the work is proportional to open holds on every
request.

**Terminal reservations accumulate without bound.** A released, expired, or failed
reservation stays forever. Nothing prunes or archives, so the table grows with total
historical deal volume rather than with live capacity, and the scan above degrades with
it.

## What Changes

- Accept a durable negotiation identity as an idempotency key for `reserve()`, so a
  hold placed before an escrow exists is deduplicated the same way one placed after is.
- Store the hold-expiry instant in a form the database can range-compare, and index it,
  so expiry selects due rows instead of loading all held ones.
- Sweep expiry on a schedule rather than in the path of every ledger operation, keeping
  a lazy check only where correctness depends on it.
- Add retention for terminal reservations, so the table's size tracks live capacity plus
  a bounded window rather than all history.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: reservation idempotency covers a durable pre-settlement identity as
  well as an escrow identity; hold expiry is evaluated as a bounded query on a scheduled
  sweep rather than a full scan in every operation's path; terminal reservations are
  retained for a bounded window.

## Non-Goals

- Do not change what `reserve()` admits, how `_find_candidate` matches, or any
  dimension semantics.
- Do not change the reservation state vocabulary or the meaning of any state.
- Do not move where or when holds are placed — `negotiation-time-capacity-hold` owns
  that.
- Do not charge for held capacity — `billable-capacity-reservations` owns that.
- Do not remove the lazy expiry check where a correctness invariant depends on it; the
  goal is to stop it being an unbounded scan, not to delay expiry past the point where a
  stale hold could block an admission.
- Do not delete released reservations that a settlement record still references.

## Impact

- Affected code: `kit/site` (`ledger.py`'s `reserve`, `_expire_stale_holds`,
  `expire_due_holds`; `db.py`'s reservation columns and indexes),
  `provisioning/compute`'s `CapacityReservationWatchdog`, and the storefront's
  `_place_capacity_hold` where it supplies the idempotency key.
- Affected data: a migration to store hold expiry comparably and index it. Existing rows
  carry ISO strings and must be converted, not reinterpreted in place.
- Affected tests: `kit/site` ledger suites, watchdog tests, migration validation.
- Not affected: admission semantics, scheduling, fulfillment, settlement.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — re-confirm at implementation time; the
      capacity-reservation section describes the lifecycle, not its indexing.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Reservation idempotency covers a pre-settlement negotiation identity as well as an
  escrow identity — `openspec/specs/site-capacity/spec.md`, extending the existing
  "Reservation lifecycle" requirement.
- Hold expiry is a bounded, scheduled sweep and terminal reservations are retained for a
  bounded window — same capability.

## Dependencies and Related Changes

- Prerequisite for `negotiation-time-capacity-hold`, which raises hold volume from
  accepted deals to committed negotiations. Landing that change first would make all
  three defects worse at once.
- Independent of `billable-capacity-reservations`; either may land first.
- The idempotency defect is present today and worth fixing regardless of whether either
  of those changes proceeds.
