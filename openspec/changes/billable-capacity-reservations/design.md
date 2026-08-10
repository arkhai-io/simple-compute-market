# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `_place_capacity_hold` runs only on `decision.action == "accept"`. Its TTL comes from
  `settings.capacity.hold_ttl_seconds` (default 900), capped by the pool's
  `max_reservation_hold_seconds` policy tag through `capped_hold_seconds`.
- `CapacityReservation` carries `hold_expires_at` and no rate, price, or funding
  reference.
- `resize_reservation` supersedes rather than mutating: it releases and re-reserves in
  one transaction and mints a new `capacity_reservation_id`.
- `SettlementObligation` is mechanism-neutral and already carries `maker`, `claimant`,
  `amount`, `asset`, `expiration_unix`, `conditions`, `mechanism`, and `params`, with
  the docstring noting a penalty bond as seller-posts/buyer-claims — the mirror of what
  is needed here.
- `add-settlement-plan-shapes` builds durable per-obligation identity, materialization,
  condition, collection, reclaim, attempt, and receipt state, and generates interval
  escrows "deterministically from accepted total/duration/schedule."
- `kit/alkahest` has no standing-account abstraction; "account" means an EOA throughout.
  `chain_probe` is an `eth_getCode` startup validator, not a balance read.
- There is no rate limiting anywhere in the storefront.

## Goals / Non-Goals

**Goals:** holding capacity costs the holder; the cost scales with capacity-time rather
than identity; a hold's duration is bounded by what the holder funded; a shape change
reprices.

**Non-Goals:** hold placement point, standing accounts, rate structure definition,
admission semantics, identity-based limits.

## Decisions

### Price exclusivity; do not rate-limit it

Rate limiting and per-identity caps were considered and rejected. Both target identity,
and identity is free to mint, so both are evaded by an attacker and felt by a legitimate
buyer. A cap also produces the wrong market behavior at the limit: a buyer willing to pay
for a hundred concurrent holds is refused, which is a strange thing for a marketplace to
do.

Pricing targets the actual scarce quantity — capacity-time under exclusive claim. An
attacker holding a hundred reservations pays for a hundred reservations, and a hundred
addresses cost the same as one. This is why the change carries no anti-abuse mechanism
of its own: the pricing *is* the mechanism.

The corollary is that anything which does not exclude other buyers must stay free.
Non-consuming feasibility verification creates no exclusivity and must never be charged,
or the system would be charging for information rather than for scarcity.

### Maximum hold duration is derived, not configured

Today TTL is configuration capped by policy. Under billing, the honest bound is what the
holder funded divided by the burn rate — a hold cannot outlive its funding, and a
configured TTL that exceeds it would promise capacity that stops being paid for.

`hold_ttl_seconds` and `max_reservation_hold_seconds` therefore become **ceilings** on
the derived value rather than its source. Both keep their names and their capping
behavior, which is what they already do to each other; only the primary source changes.

Stated as a decision because the inverse — treating the funded amount as a cap on a
configured TTL — reads as equivalent and is not: it lets a hold expire with funds
remaining, which silently overcharges relative to the service delivered.

### The burn rate comes from the commercial rate structure, not a separate hold price

A second price for the same capacity would drift from the first and would need its own
resolution, configuration, and override tiers. The burn rate is the same rate structure
`capacity-shape-pricing` resolves, evaluated against the held shape. That change's
requirement that price aggregation be reachable outside the negotiation path is what
makes this possible without duplicating the resolver.

A consequence worth surfacing: holding capacity and consuming it are then priced from
one structure, so a seller who raises rates raises both together and cannot accidentally
make holding cheaper than using.

### Charging reuses the obligation lifecycle but not the interval generation rule

`add-settlement-plan-shapes` builds exactly the durable machinery a hold charge needs —
per-obligation identity, materialization, collection, reclaim, receipts, and
resumability. What does not transfer is how obligations are generated: interval escrows
come from an accepted total, duration, and schedule, and before agreement there is no
accepted total.

A hold's obligation is generated instead from the burn rate and the funded maximum
duration, with the collectable amount determined by elapsed held time and the remainder
returned. Reusing the lifecycle while replacing the generation rule is the whole of the
integration; inventing a parallel payments path alongside it is the thing to avoid, and
would be the natural mistake since a hold charge feels unlike a settlement.

### Supersede reprices; it does not carry the old rate forward

`resize_reservation` already mints a new reservation rather than mutating, which is the
correct foundation: the new shape gets a new rate, and the remaining affordable duration
is recomputed from the funds still uncommitted. Carrying the old rate forward would let a
buyer resize into a more expensive shape at the cheaper rate.

Because supersede is atomic and rolls back when the new shape has no candidate, the
repricing must be inside the same transaction — a resize that succeeds at the ledger
but fails to reprice would leave capacity held at the wrong rate, and that is the
failure mode most likely to be missed.

### Funds verification: read or proof, chosen at the domain layer

Chain reads through view functions are cheap; chain writes are not. Two shapes work and
the choice is not forced by this change's contracts:

- The seller reads the buyer's committed balance directly, which needs a view function
  and an RPC round trip per verification.
- The buyer supplies a proof of committed funds that the seller consumes, which needs no
  read but needs the proof to be verifiable and fresh.

Both are recorded because the choice interacts with the deferred standing-account work:
a per-negotiation commitment makes reading trivial (the commitment is the negotiation's
own), while a standing account makes proof more attractive (the balance changes
independently of any one negotiation). The requirement below is written to admit either.

## Risks / Trade-offs

- **[A buyer's funds run out mid-hold]** → The derived duration is exactly the point at
  which that happens, so it is expiry, not a special case. The hold lapses through the
  existing expiry path.
- **[Charging for a hold that the seller could not ultimately fulfill]** → A hold the
  seller fails to honor should not be charged. The obligation's conditions must gate
  collection on the hold having actually excluded others for the elapsed time, not on
  the clock alone.
- **[Buyers face a funding step before they can negotiate seriously]** → Real friction,
  and the reason the standing account exists as a follow-on. Accepted for now; the
  alternative is uncompensated exclusion.
- **[Two prices for capacity drift apart]** → Prevented structurally by deriving the
  burn rate from the commercial rate structure rather than configuring it separately.
- **[Repricing on supersede is missed]** → Named above as the most likely miss; it needs
  a test asserting a resize into a more expensive shape charges the new rate.

## Migration Plan

1. Reservation carries a burn rate and a funded bound; both nullable, unused.
2. Hold obligation generation and lifecycle, reusing the per-obligation machinery.
3. Derived maximum duration, with the existing TTL settings demoted to ceilings.
4. Supersede repricing inside the existing atomic transaction.
5. Funds verification at the domain layer, in whichever of the two shapes is chosen.

Steps 1–2 are inert without 3. Step 3 is the behavioral boundary: after it, a hold
without committed funds cannot be placed, which is a buyer-visible change and the
deployment boundary.

## Open Questions

- **Is the unconsumed remainder returned per hold, or netted across a negotiation's
  holds?** Netting is cheaper in chain writes and interacts with the standing account.
  Deferrable: it changes settlement mechanics, not the requirement that the remainder be
  returned.
- **Does a seller who declines to honor a hold owe anything beyond forgoing the
  charge?** A penalty bond is the existing vocabulary for it, and
  `add-settlement-plan-shapes` is already building seller-funded bonds. Deferrable and
  better decided once hold charging is real.
