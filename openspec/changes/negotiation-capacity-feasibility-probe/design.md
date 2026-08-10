# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `_place_capacity_hold` is called only when `decision.action == "accept"`, at three
  call sites in `sync_negotiation.py`. Nothing consults the site authority earlier.
- `kit/site`'s `probe()` runs `_expire_stale_holds`, then the same `_find_candidate`
  used by `reserve()`, and returns the match payload without writing. It is the
  non-consuming twin of the admission path, not an approximation of it.
- `SiteCapacityClient.probe` and `core_storefront`'s aggregate client both expose it;
  `vm_job_spec_service` already calls it in the fulfillment path.
- `probe` takes the ledger's process-wide `threading.RLock`, the same lock as `reserve`,
  `commit`, and `release`.
- `has_matching_inventory_guard` reads an advisory snapshot and compares two categorical
  fields.

## Goals / Non-Goals

**Goals:** fail an unservable shape during negotiation; keep unservable distinct from
unacceptable; consume nothing.

**Non-Goals:** holding earlier, admissibility, pricing, protocol fields, or removing the
race.

## Decisions

### Probe rather than hold

Holding during negotiation would guarantee the capacity, and that guarantee is exactly
what makes it dangerous: an unbilled hold lets one buyer exclude others at no cost, and
solving that requires the whole capacity-economics design — a billable reservation, a
funded buyer account, and a hold lifecycle that charges for held time.

Probing gets most of the benefit for none of that cost. The buyer learns the shape is
unservable at the moment they ask rather than after terms are agreed, and no state is
created, so there is nothing to abuse and nothing to clean up. The residual gap is the
race, addressed below.

This ordering is deliberate: the early-failure benefit and the exclusivity guarantee are
separable, and shipping the first without the second is what lets multidimensional shape
negotiation proceed while capacity economics stays parked.

### Unservable and unacceptable are different outcomes

Collapsing them would tell a buyer "no" without saying whether to change the ask or wait.
Those lead to opposite next moves, and a buyer who reads a transient shortage as a
rejected shape will renegotiate a shape that was fine.

The two are also answered by different authorities: unacceptable comes from seller
policy and declared pool bounds, unservable from the site ledger. Keeping the outcomes
distinct keeps that separation visible instead of laundering both through one error.

### Admissibility is evaluated first, when available

When `capacity-shape-envelope` is present, a shape outside the pool's declared bounds is
rejected before any probe. A seller that would never sell 64 GPUs should not ask the
site whether it has 64 free. This ordering keeps site round trips proportional to
plausible asks rather than to all asks, which matters because of the lock below.

The two changes are independent and may land in either order; this one degrades to
probing every checked round when the envelope capability is absent.

### The result is explicitly advisory

`probe()` and `reserve()` share `_find_candidate`, so a probe's answer is exactly what a
reservation would have decided at that instant — and only at that instant. Two
concurrent negotiations can both be told yes.

This is accepted rather than mitigated, and stated in the requirement rather than left
to be discovered. The system already has this property: the projection is advisory and
the reconciler's "ignorance is not zero" rule already treats unknown availability as
usable, corrected authoritatively at reserve time. This check is strictly better
information than that, arriving strictly earlier, with the same guarantee.

Implying a guarantee that does not exist would be worse than the current silence,
because a buyer would stop expecting the reservation to fail.

### Round-trip cost is real and is why the check is bounded

`probe` takes the ledger's process-wide lock, so negotiation traffic contends with real
admission traffic. The check therefore runs when the requested shape is one the seller
would actually serve, not on every message, and not for a shape already known
inadmissible.

Recorded because "probe consumes nothing" invites the conclusion that it is free. It
consumes no capacity; it does consume the ledger's serialization point.

## Risks / Trade-offs

- **[Negotiation load reaches the ledger's lock]** → Bounded by ordering admissibility
  first and checking only shapes worth checking. If it becomes a problem, the fix is the
  ledger's concurrency, which is already flagged in the capacity-economics analysis and
  is not this change's to make.
- **[A probe succeeds and the reservation later fails]** → Accepted and specified. The
  outcome is unchanged from today; only the odds improve.
- **[Callers read the probe as a guarantee]** → The likeliest misuse. Mitigated by
  naming it in the requirement and by keeping the non-consuming property explicit at the
  call site rather than implicit in the method name.
- **[Site unreachable during negotiation]** → Must not silently pass or silently fail.
  An indeterminate check needs an explicit disposition; degrading to today's behavior —
  proceed, and let the hold at acceptance be authoritative — is the compatible choice.

## Migration Plan

Additive; no migration and no persisted state. Rollback is a code revert; negotiations
lose the early check and fail at acceptance as they do today.

## Open Questions

- **Should a probe failure be retried within the same round, or reported immediately?**
  A transient shortage may clear in seconds. Deferrable: it is a policy detail that
  changes no requirement, and immediate reporting is the honest default.
- **Should the probe result inform a counter-offer with what *is* servable?** Attractive
  — `probe` returns a match payload with availability — but it turns a feasibility check
  into a shape recommender, which needs `capacity-shape-envelope`'s range query and a
  negotiation vocabulary for suggestions. Deferrable and better decided once shape
  counter-offers exist.
