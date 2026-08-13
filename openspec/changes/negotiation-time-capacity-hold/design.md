# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `_place_capacity_hold` is called from three sites in `sync_negotiation.py`, each
  guarded by `decision.action == "accept"`.
- Its `deal_ref` carries `listing_id` and `negotiation_id` and no `escrow_uid`, so
  `reserve()`'s idempotency branch never applies to it today.
- `resize_reservation` supersedes atomically and mints a new
  `capacity_reservation_id`; it has no caller.
- `negotiation_threads` records `their_agent_id` and `terminal_state`, and a watchdog
  marks threads abandoned after `negotiation_timeout_seconds` (default 1800).
- Every negotiation entry point verifies an EIP-191 signature over operation,
  resource id, and timestamp, so a counter-offer is authenticated and non-repudiable.

## Goals / Non-Goals

**Goals:** close the race for capacity under active negotiation; keep inquiry free;
keep one reservation per negotiation.

**Non-Goals:** billing, the shape-change payload, settlement behavior, admission.

## Decisions

### The trigger is the first genuine counter-offer, not the inquiry

Three placement points were considered.

- **Terms acceptance (today).** The race stays open for the whole negotiation.
- **Inquiry.** Strongest guarantee, rejected: it makes a funded commitment a
  precondition for asking a question. Browsing becomes an on-chain act, and a buyer
  comparing ten listings funds ten commitments to do it.
- **Accepted: first genuine counter-offer.** The buyer has spent a signed round-trip and
  is asking the seller to move, which is the first point where intent is demonstrated
  rather than assumed. Holds then scale with serious negotiations rather than with
  browsing.

"Genuine" needs a definition that cannot be trivially satisfied: a counter-offer that
restates the listing's own terms is not a commitment to anything, and treating it as one
would reopen inquiry-time holding through the back door. The signed round-trip is the
cost that makes the trigger meaningful, and the definition should require the
counterparty to have actually proposed different terms.

### One reservation per negotiation, superseded rather than accumulated

`resize_reservation` mints a new `capacity_reservation_id` per call. A negotiation with
ten shape changes would leave ten rows if each were a fresh reserve, which compounds the
expiry and retention costs `capacity-reservation-lifecycle-hardening` addresses.

Superseding keeps exactly one live reservation per negotiation. The pre-settlement
idempotency key from that same prerequisite is what makes this robust to retries: a
repeated counter-offer returns the existing reservation rather than admitting a second.

### Inquiry stays free, and that is a property to protect rather than a default

The value of the non-consuming verification is precisely that it excludes nobody and
therefore need not be funded. It would be easy to erode — adding a small hold "just to
be safe" at inquiry, or charging a nominal amount for verification — and either would
reintroduce the browsing-costs-money problem this placement exists to avoid.

Stated as a decision so the property is defended deliberately rather than assumed.

### Holds are released on negotiation end, not left to lapse

A negotiation that fails or is abandoned leaves capacity held until its funded bound
expires. That is correct but wasteful: the capacity is available and nobody can have it,
and the buyer keeps paying for it.

Releasing promptly on a terminal negotiation state — including the watchdog's
abandonment path, which is where a vanished counterparty ends up — returns capacity and
stops the charge. The abandonment path matters more than the explicit ones, because a
counterparty that crashes is exactly the case that would otherwise hold capacity for the
full funded duration.

## Risks / Trade-offs

- **[A buyer counter-offers on many listings to hold capacity broadly]** → Priced, not
  prevented. They pay for every hold, which is the intended market behavior; the
  prerequisite change is what makes this acceptable rather than an abuse vector.
- **[Hold population grows substantially]** → The reason both prerequisites exist.
  Landing this change before them is the sequencing error to avoid.
- **[A trivial counter-offer is treated as genuine]** → Reopens inquiry-time holding;
  needs an explicit definition and a test that a restated-terms counter-offer does not
  place a hold.
- **[Release on abandonment races a concurrent commit]** → The reservation lifecycle
  already handles concurrent release and commit through the ledger's own transaction;
  this change adds a caller, not a new concurrency model.
- **[A negotiation holds capacity the buyer never intended to buy]** → True and
  acceptable: they funded it, and they can end the negotiation to release it.

## Migration Plan

1. Record the negotiation's reservation identity on the negotiation thread.
2. Move placement to the first genuine counter-offer; keep the acceptance path
   idempotent so a negotiation that reaches acceptance without a counter-offer still
   holds before settlement.
3. Supersede on requested-shape change.
4. Release on terminal negotiation state, including watchdog abandonment.

Step 2 is the behavioral boundary. Rollback is a code revert; holds placed early lapse
or commit normally under the restored code, since nothing about the reservation itself
differs.

## Open Questions

- **Should a seller-initiated counter-offer also place a hold?** The seller proposing
  different terms is a commitment of a kind, but the buyer has not yet funded anything.
  Deferrable: it changes the trigger's breadth, not the mechanism, and the buyer-side
  trigger is the one that closes the race.
- **Should a hold survive a negotiation's abandonment for a grace period, in case the
  counterparty returns?** Cheaper for a flaky client, worse for capacity utilization.
  Deferrable: it is a policy interval, not a structural question.
