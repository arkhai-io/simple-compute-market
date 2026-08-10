# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `reserve()` reads `escrow_uid = deal.get("escrow_uid")` and skips its dedupe branch
  entirely when the key is absent. `_place_capacity_hold` never supplies it.
- `_expire_stale_holds` queries `state == reserved AND hold_expires_at IS NOT NULL`,
  materializes every match, and evaluates `parse_utc(...) > now` per row in Python.
- `hold_expires_at` is written as `datetime.now(timezone.utc) + timedelta(...)` rendered
  with `.isoformat()`.
- `db.py` indexes `state`, `escrow_uid`, `settlement_resource_id`, and
  `backing_resource_id`. `hold_expires_at` is unindexed.
- `expire_due_holds()` exists as the watchdog entry point and its docstring states its
  purpose: an idle site with no incoming requests, where the lazy path never runs.
- `CapacityReservationWatchdog` polls it every 60s by default.
- Terminal states (`released`, `release_failed`, `provisioning_failed`) have no pruning
  path anywhere.

## Goals / Non-Goals

**Goals:** idempotency that applies to the caller that actually places holds; expiry
cost proportional to due rows rather than held rows; bounded table growth.

**Non-Goals:** admission semantics, hold placement, hold billing, state vocabulary.

## Decisions

### The idempotency key generalizes rather than being replaced

`escrow_uid` remains a valid key; a durable negotiation identity becomes an additional
one. Replacing the escrow key would break the retry protection that already works for
settlement-time reserves, and the two identities coexist naturally: a hold placed during
negotiation is later committed under the same reservation once an escrow exists.

The key must be *durable* — stable across a retry of the same logical placement, and
distinct between two genuinely different placements for the same listing. A negotiation
identity satisfies both; a listing identity does not, since two buyers negotiating the
same listing must each get their own reservation.

Worth stating because the obvious near-miss is keying on `listing_id`, which is present
in `deal_ref` today and would silently collapse two buyers' holds into one.

### Expiry moves from string comparison in Python to a range query

The current form cannot use an index and cannot filter in the database, which is why the
cost tracks held rows rather than due rows. Storing the instant in a comparable form and
indexing it turns the sweep into a bounded selection.

Existing rows carry ISO strings, so this is a data migration rather than a
reinterpretation. Both representations must not be read by the same code path — a
half-migrated table where some rows compare correctly and some do not is worse than
either form alone, so the migration converts rather than adding a parallel column read
opportunistically.

### The lazy check narrows; it does not disappear

Removing lazy expiry entirely would let a hold that expired one second ago block an
admission until the next sweep, converting a correctness property into a timing race.
The lazy check is kept where an operation's own correctness depends on current
availability — the admission path — and dropped from the paths that merely read.

This is the decision most likely to be over-applied. "Move expiry to the watchdog" is
the wrong summary: the watchdog owns the *bulk* sweep of an idle site, and admission
keeps its own due-row check, which is cheap once the query is bounded.

### Retention is bounded by time and by reference, not by count

A terminal reservation may still be referenced by a settlement record or by an
in-flight reconciliation. Retention therefore keeps a row until both a time window has
elapsed and nothing references it, rather than trimming to a row count.

A count-based cap is rejected because it makes retention depend on unrelated traffic: a
busy period would evict rows a settlement record still needs.

## Risks / Trade-offs

- **[Migration converts timestamps incorrectly for rows written across a timezone or
  format variation]** → The stored values are produced by one code path with an explicit
  UTC timezone, so the input format is narrow; the migration should still fail loudly on
  an unparseable value rather than defaulting it, since a defaulted expiry either leaks
  capacity or releases it early.
- **[A hold expires between the narrowed lazy check and the admission decision]** →
  Unchanged from today: both run inside the same transaction and the same lock.
- **[Retention deletes a row a future feature needs]** → Retention is time-plus-reference
  bounded and configurable; the conservative default is a long window, since the problem
  being solved is unbounded growth, not disk pressure.
- **[Generalized idempotency masks a genuine second placement]** → Only if the key is
  reused for a different logical placement. The durability requirement above is what
  prevents it, and it needs a test asserting two buyers on one listing get two
  reservations.

## Migration Plan

1. Add the comparable expiry representation and its index; backfill existing rows;
   fail loudly on an unparseable value.
2. Switch expiry to the range query; narrow the lazy check to the admission path.
3. Accept the negotiation identity as an idempotency key and supply it from the
   storefront's hold placement.
4. Add retention, defaulted conservatively.

Rollback after step 1 is a code revert; the added column is inert to a restored reader.

## Open Questions

- **Should retention be enforced by the same watchdog or a separate one?** The sweep
  and the prune have different natural intervals. Deferrable: it is a scheduling detail
  that changes no requirement.
- **Should a released reservation's capacity event history be retained after the
  reservation row is pruned?** Events are a separate table with their own consumers.
  Deferrable until retention is actually configured tightly enough to matter.
