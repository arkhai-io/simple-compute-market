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

**Goals.** Publish a rate buyers can filter and compare on. Keep it independent of
the negotiation-side pricing work and forward-compatible with it. Make it normative
that nothing is constructed from the number.

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

### One rate per listing, not a per-dimension structure

An earlier version of this design made the rate adopt `capacity-shape-pricing`'s
family-grouped shape, and accepted a dependency on that change and transitively on
the unstarted `structured-capacity-requirements`. That was wrong about what
`capacity-shape-pricing` is for.

That change exists because negotiation has one degree of freedom, so a seller
cannot answer "what would this cost with more RAM and fewer GPUs" — which is why
`_reject_unsupported_resource_shape_request` rejects a buyer who names a shape at
all, and why `_place_capacity_hold` records that seller policy prices only the
listing's advertised shape. Per-dimension rates, an injectable aggregator, and a
negotiated rate multiplier all exist to price a shape the buyer proposes.

A published asking price prices a shape that does not vary. A listing advertises
one shape; the seller's price for it is one number. Decomposing it per dimension
would build the machinery for a question this surface never asks.

**Forward compatibility, which is what makes this safe rather than expedient.**
When `capacity-shape-pricing` gives a listing a minimum rate structure, the
published asking price is that structure evaluated at the advertised shape. The
field keeps its shape and its meaning; only where the number comes from changes.
That is an internal change with no schema migration behind it, which is not true
of the reverse — publishing a per-dimension structure now would commit buyers and
registries to a shape before the change that defines it has been designed.

**The accepted limitation.** A seller pricing RAM and GPUs differently cannot
express that here, and a buyer comparing two listings that bundle different RAM is
comparing bundled prices. Unbundling belongs to `capacity-shape-pricing`, which is
building it for the negotiation side; a second decomposition here would be exactly
the duplication that change exists to prevent. **Revisit trigger:** the first
buyer request to filter or sort on a per-dimension rate, or `capacity-shape-pricing`
landing.

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
- **[A flat rate is later regretted]** → If per-dimension comparison turns out to
  be what buyers actually want, this field becomes a summary of something richer
  rather than the whole story. Acceptable because the field survives that change
  intact — it becomes a derived value — and because the alternative was blocking
  comparison behind two unstarted changes.
- **[Rate and dimension shapes diverge]** → The rate attaches to the same
  family-grouped capability shape the dimensions use. If
  `publish-multidimensional-listing-shape` moves that shape, this change moves
  with it rather than pinning a copy.

## Open questions

- **Which rate periods are expressible, and does the filter normalize across
  them?** Hourly is the obvious default, but supply arranged out of band is
  commonly priced monthly or per commitment. A filter comparing an hourly rate
  against a monthly one without normalizing would be worse than no filter. This is
  now ours to decide rather than deferred to another change's vocabulary.
- **How is the rate's asset expressed?** A listing already names assets in its
  settlement options, so the asking rate either reuses that vocabulary or states
  its own. Comparing two rates in different assets is the same normalization
  problem as comparing two periods, and probably wants the same answer.

## Migration Plan

1. Publish the asking rate with its asset and period.
2. Add the filters.

Additive throughout. A listing that publishes no rate behaves as it does today
except that it is excluded from rate-bounded queries, which is the intended
semantics rather than a regression. Rollback is a code rollback; published rate
fields remain and are ignored by a restored reader.
