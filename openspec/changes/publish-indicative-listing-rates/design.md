# Design — publish indicative listing rates

## Context

Compute listings publish region, GPU model, form factor, and multi-dimensional
shape, and none of them publish a price. Negotiation-floor pricing exists but is
storefront-side policy input, resolved through a three-tier precedence and
explicitly not something that constructs a settlement option or reaches a buyer.

For backed supply that has been survivable: a buyer negotiates and discovers the
price. For supply agreed out of band it is not, because the entire value the
marketplace offers there is comparison before contact.

## Goals / Non-Goals

**Goals.** Publish a rate buyers can filter and compare on. Keep it on the shape
pricing is converging toward. Make it normative that nothing is constructed from
the number.

**Non-Goals.** No settlement participation, no honesty enforcement, no change to
negotiation-floor policy, no restriction to unbacked listings.

## Decisions

### The rate is a listing attribute, not a settlement option rate

This is the decision the whole change rests on, and it was settled during Goal 7's
design rather than here.

The mechanism these out-of-band deals settle through declines scalar
participation deliberately. Its design records the rejected alternative: encoding
exotic contracts as rates was considered and rejected, because the scalar
machinery exists for mechanisms that want it and this class of terms does not
reduce to one number. Publishing an indicative rate in `offer_resource` honours
that rather than reversing it — the seller states what they are asking, and the
agreed amount remains absent rather than zero.

Un-declining scalar participation was the alternative. Rejected: a rate inside a
settlement option is a number the runtime does arithmetic on and an accepted
obligation implies. For a deal whose terms are agreed elsewhere, nothing stands
behind that number, and putting it in the carrier that is supposed to be
authoritative about what was agreed misrepresents exactly the thing the carrier
exists to represent.

The consequence worth stating normatively is about construction, not credence: no
settlement option, escrow term, or accepted obligation is derived from the
published rate, and an agreed amount is absent until one is negotiated.

What this decision deliberately does **not** say is that a published rate is a
weaker kind of claim than a published compute shape. Every field in a listing is a
seller assertion — nothing in the marketplace verifies that a host has the RAM it
advertises either, and `compute_capacity_claim_from_order` describes even a backed
listing's dimensions as "the listing's fixed, seller-declared shape". A misleading
rate and a misleading shape are discovered the same way and reach the same control:
registry curation, out of band.

### The family-grouped shape, not a scalar

A single scalar plus a unit would be cheaper and would unblock this change today.
Rejected because `capacity-shape-pricing` already has three consumers for the
family-grouped shape, and a fourth private representation would be migrated by
whoever next touches pricing — at which point the migration is someone else's
cost, incurred to save this change a wait.

The price of that decision is honest and belongs in the record: this change is
blocked on `capacity-shape-pricing`, which is blocked on
`structured-capacity-requirements`, which is unstarted. Goal 7 therefore has a gap
it cannot close on its own schedule. That was accepted deliberately in exchange
for not blocking discovery, which `unbacked-listing-publication` delivers without
this change.

### Exact filters, failing on missing

Every `offer_resource` filter in `filter-spec.yaml` is `on_missing: fail`, and the
file states that an unknown spec cannot be assumed to satisfy a stated
requirement. Rate follows that convention for the same reason it exists: a
listing with no published rate has not shown it is under a buyer's maximum, and
returning it as though it had would make a rate-bounded query mean nothing.

The underreport-friendly `on_missing: pass` convention applies to
`accepted_escrows` and `settlement_options` paths, where tolerating a seller who
lists fewer options than they accept is the intent. That is not this case.

### Rates are not confined to unbacked listings

A backed seller may also want to advertise an asking rate, and confining the
field would make it a second encoding of backing — a reader could infer
"unbacked" from a rate's presence. Backing has its own field precisely so nothing
else has to carry it implicitly.

### No honesty control

Nothing keeps a published rate current or truthful, and a seller pays nothing to
advertise one they will not honour. The intended control is registry curation: an
operator delisting a storefront whose listings prove dishonest. That sits outside
the registry service boundary — directory curation and offline operator
signatures are explicitly not registry-service concerns — and is not implemented
in this repository.

Two consequences worth keeping straight rather than assuming away. The
enforcement mechanism does not exist here, so a deployment relying on it is
relying on its own operations. And because registries are independently operated,
buyer-experience feedback reaching a curator is a property of a particular
deployment rather than of the market.

**Revisit trigger:** the first evidence of published rates diverging
systematically from agreed ones, or the first operator request for a delisting
mechanism.

## Risks / Trade-offs

- **[Buyers read an asking rate as a quote]** → Partly mitigated by the normative
  statement that nothing is constructed from it, so no surface can present it as an
  agreed amount. Not fully mitigable: a number in a catalogue reads as a price, and
  the marketplace has no way to establish otherwise before a negotiation happens.
- **[The dependency chain slips]** → Goal 7's rate-comparison gap stays open for
  as long as it does. The mitigation is that discovery does not wait on it, which
  is the entire reason this change is separate.
- **[Rate and dimension shapes diverge]** → The rate attaches to the same
  family-grouped capability shape the dimensions use. If
  `publish-multidimensional-listing-shape` moves that shape, this change moves
  with it rather than pinning a copy.

## Open questions

- **Which rate periods are expressible?** Hourly is the obvious default, but
  out-of-band deals are commonly monthly or per-commitment. Whether the shape
  carries a period, and whether the filter normalizes across periods before
  comparing, is deferred to `capacity-shape-pricing`'s vocabulary rather than
  guessed here. A filter that compares an hourly rate against a monthly one
  without normalizing would be worse than no filter.
- **Does a rate-bounded query need a currency or token dimension?** Related, and
  likely answered by the same vocabulary.

## Migration Plan

1. Land `capacity-shape-pricing`.
2. Publish the rate on the family-grouped shape.
3. Add the filters.

Additive throughout. A listing that publishes no rate behaves as it does today
except that it is excluded from rate-bounded queries, which is the intended
semantics rather than a regression. Rollback is a code rollback; published rate
fields remain and are ignored by a restored reader.
