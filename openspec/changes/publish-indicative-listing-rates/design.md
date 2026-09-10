# Design — publish indicative listing rates

## Context

Compute listings publish region, GPU model, form factor, and multi-dimensional
shape. Negotiation-floor pricing exists but is storefront-side policy input,
resolved through a three-tier precedence and explicitly not something that
constructs a settlement option or reaches a buyer.

A seller-advertised price is not entirely absent from the published shape, and it
is worth being precise about where it already exists, because that placement is
what constrains this change. `AcceptedEscrow.rates` is documented as the
"canonical pricing+escrow advertisement" and carries a per-hour price, with an
empty list meaning hidden reserve; `filter-spec.yaml` publishes both
`accepted_escrows[*].rates` and `settlement_options[*].rates` alongside a required
`asset`. What does not exist is any filter over a rate value — every rate-adjacent
filter in the specification reads `literal_fields.token` or `mechanism`, never an
amount.

So the accurate statement of the gap is not that compute listings publish no
price. It is that the only published price lives inside a settlement carrier, is a
number the runtime does arithmetic on, and is absent entirely for the supply this
change exists to serve. For backed supply that has been survivable: a buyer
negotiates and discovers the price. For supply agreed out of band it is not,
because the entire value the marketplace offers there is comparison before
contact.

## Goals / Non-Goals

**Goals.** Publish a rate buyers can filter and compare on. Keep it independent of
the negotiation-side pricing work and forward-compatible with it. Make it normative
that nothing is constructed from the number, and that a rate carries the period and
asset it is quoted in.

**Non-Goals.** No settlement participation, no honesty enforcement, no change to
negotiation-floor policy, no restriction to unbacked listings, no cross-period or
cross-asset normalization.

## Decisions

### The rate is a listing attribute, not a settlement option rate

This is the decision the whole change rests on, and it was settled during Goal 7's
design rather than here.

The mechanism these out-of-band deals settle through declines scalar
participation deliberately. Its design records the rejected alternative: encoding
exotic contracts as rates was considered and rejected, because the scalar
machinery exists for mechanisms that want it and this class of terms does not
reduce to one number. Publishing an asking rate on the listing shape honours
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

### A separate listing-level field, with its relationship to a mechanism rate stated

The asking rate is a new field on the published listing shape rather than a filter
over the rate a listing already advertises inside `accepted_escrows[*].rates` or
`settlement_options[*].rates`.

**Making the existing carrier filterable was the alternative, and it fails on the
supply this change exists to serve rather than on preference.** `contact-exchange.v1`
options are rateless — the mechanism declines scalar participation, which is
recorded in `ARCHITECTURE.md` and in the mechanism's own archived design. Supply
agreed out of band settles through exactly that mechanism, so those listings carry
no escrow rate and no option rate at all. A filter over the settlement carrier
would leave precisely the target supply unfilterable while making the settlement
carrier the comparison surface, which means reopening the decision above rather
than working around it.

**A stated equality between the two was the other alternative, and it has no
well-defined referent.** A listing may accept several escrows across several
chains, each with its own token and its own rate, so "the asking rate must equal
the advertised floor" does not name one number. Scoping the rule to the escrow in
the same asset is definable but makes it fire only where a seller has already said
the same thing twice, and it buys a consistency rule someone has to enforce, test,
and keep true through republication.

So the relationship is stated rather than enforced, which is what closes the
"two published prices with no stated relationship" objection without inventing an
enforcement surface:

- They are different carriers with different meanings. A mechanism rate governs
  what the runtime constructs; the asking rate governs nothing.
- They are not required to agree, and where they disagree neither corrects the
  other. A buyer comparing on one and negotiating against the other is the
  ordinary relationship between every published field and its negotiated outcome.
- Neither is derived from the other. A storefront MUST NOT populate the asking
  rate from a mechanism rate, and MUST NOT write the asking rate into a settlement
  option, escrow term, or obligation. Deriving it would make the field's
  provenance unreadable — a buyer could not tell whether the seller asked for that
  number or the storefront computed it — and it is undefinable anyway for a
  listing advertising escrows in several assets.

A seller who publishes an asking rate they will not honour lands in the same class
as one who publishes a GPU model they do not have. That control is registry
curation, out of band, and is unchanged by this decision.

**Revisit trigger:** the first buyer request to filter on an escrow or option rate
value, which is a different feature from this one and would need its own reasoning
about the settlement carrier.

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

### The asset is an opaque identifier, and the rate is decimal text

A rate is uninterpretable without the asset it is quoted in, so the field carries
one. The question was whether to express it as the structured token metadata the
negotiation path uses or as something narrower.

`SettlementPublicationClause` in `kit/settlement-runtime` already answers this for
the publication surface, and the asking rate reuses that answer rather than
stating a second one. That clause carries `asset` as a trimmed, non-empty **opaque
string**, `rate` as positive **decimal text** without an exponent, and `per` as a
canonical lowercase unit, with a validator requiring rate and unit to be supplied
together. On the query side, `asset` is a typed field descriptor restricted to
equality operators — `EQUAL`, `NOT_EQUAL`, `IN`, `NOT_IN` — so assets are already
matched and never ordered or converted anywhere in the system.

**Structured token metadata was the alternative and is rejected as too narrow.**
`ERC20TokenMetadata` carries a contract address, decimals, and a chain ID, all of
which presume an on-chain ERC-20. A seller arranging supply out of band commonly
prices in a currency, and the marketplace is composing off-chain settlement
mechanisms — hosted fiat is already a registered mechanism with three funding
profiles. Requiring token metadata would exclude the exact sellers unbacked
listings exist to serve and would need widening the moment an asking rate is
quoted in anything a chain does not mint. An opaque identifier is the shape that
survives that.

**Decimal text rather than base units, for two independent reasons.** Base units
are uninterpretable without decimals, which is why `TokenResource` has to pair an
amount with its metadata and why an amount alone means nothing; decimal text needs
no companion field to be read. And amounts in this domain routinely exceed what a
64-bit number holds — an 18-decimal token's base units pass 2^53 at ordinary
values, JSON numbers are IEEE-754 doubles in most parsers, and SQLite INTEGER is
int64. The repository already handles this by keeping decimal-digit strings on the
wire, and the publication clause already chose text for the same reason.

**A rate bound carries an asset and a period, and all three travel together.** A
query bounded at `5` cannot be evaluated without knowing five of what and per
what, so a rate-bounded query names the asset and the period, and publication
refuses a rate missing either. This mirrors the existing `require_complete_rate`
invariant rather than inventing a rule.

**Assets match, they are not converted** — the same rule the period takes, and on
stronger grounds. Converting a period is trivial arithmetic rejected below on
demand-side grounds. Converting an asset is not arithmetic at all: it needs an
external exchange rate that moves continuously, which would make a filter result
depend on when it ran and would put the marketplace in the business of valuing
assets — a surface it does not have and this change does not open. A listing
quoting an asset the query did not name is excluded.

**Revisit trigger:** the first request to compare rates across assets, which needs
a valuation source and is a different feature from filtering.

### Exact filters, failing on missing

Every published-shape filter in `filter-spec.yaml` is `on_missing: fail`, and the
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

### The period is `hour`, because that is all parity means

The rate carries the period it is quoted per, drawn from the same canonical
time-unit vocabulary settlement rates already use — and that vocabulary currently
holds exactly one entry. `PER_UNIT_SECONDS` in `core/src/market_core/schemas.py`
is `{"hour": 3600}`. `RateValue.per` defaults to `"hour"`. The VM settlement path
computes `total_price = hourly_rate.amount * duration_seconds // 3600` with the
divisor inline, and the bare-metal buyer CLI refuses a listing that does not
"advertise an hourly rate".

So parity with what the VM and bare-metal domains support is `hour` and nothing
else. There is no second time period in the system to be at parity with. API credits
use counted units (`per="token"`), which `compute_rate_unit_total` explicitly
separates from time-unit rates, so they are a different axis rather than a second
period.

**The limitation this accepts.** Supply arranged out of band is commonly priced
monthly or per commitment — this design said so itself before the decision was made.
A seller who prices that way cannot express it in this version; they publish an
hourly equivalent or no rate. That is a real gap for the exact sellers unbacked
listings exist to serve, and it is accepted because adding a time period means
adding it to `PER_UNIT_SECONDS` and to every arithmetic path that reads it, which is
settlement work rather than publication work. **Revisit trigger:** a second entry in
`PER_UNIT_SECONDS`, or the first seller request to publish a non-hourly asking rate.

### The filter matches the period rather than normalizing across it

A rate-bounded query names the period it is asking about, and a listing quoted in a
different period does not match — it is excluded rather than converted.

Normalizing was the alternative and is rejected on demand-side grounds rather than
arithmetic ones. A buyer shopping for on-demand capacity at an hourly rate is not
looking for supply quoted monthly, because a monthly quote signals a monthly
commitment. Converting one to the other would return supply whose *terms* the buyer
did not ask for, dressed as a price match. Excluding it is the more useful answer
even though the arithmetic is trivial.

With one period in the vocabulary this rule has no observable effect today. It is
stated now so that adding a second period does not silently turn every hourly query
into a cross-period comparison.

## Risks / Trade-offs

- **[Buyers read an asking rate as a quote]** → Partly mitigated by the normative
  statement that nothing is constructed from it, so no surface can present it as an
  agreed amount. Not fully mitigable: a number in a catalogue reads as a price, and
  the marketplace has no way to establish otherwise before a negotiation happens.
- **[A listing publishes two prices that disagree]** → Accepted rather than
  solved. A backed listing may carry both an asking rate and a mechanism rate, and
  nothing reconciles them. Mitigated by stating the relationship normatively — the
  mechanism rate governs construction, the asking rate governs nothing, and
  neither is derived from the other — so a reader can tell which number binds. A
  seller whose two numbers disagree is making a misleading assertion, which reaches
  the same out-of-band control as every other misleading published field.
- **[An opaque asset identifier is ambiguous across deployments]** → Two
  storefronts could name the same asset differently, or the same string could mean
  different things to different registries. Accepted: the identifier is exactly as
  opaque as `settlement_options[*].asset` already is, so this adds no ambiguity
  the comparison grammar does not already carry, and an equality-only filter
  cannot silently mis-order two assets the way a conversion could.
- **[Hourly-only excludes the sellers this serves]** → Out-of-band supply is often
  priced monthly, and those sellers publish an hourly equivalent or nothing.
  Mitigated only by the revisit trigger; the alternative is adding a time period to
  the settlement vocabulary, which is not this change's surface.
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

None. The asset question is resolved above; its revisit trigger is a request to
compare rates across assets.

## Migration Plan

1. Publish the asking rate with its asset and period.
2. Add the filters.

Additive throughout. A listing that publishes no rate behaves as it does today
except that it is excluded from rate-bounded queries, which is the intended
semantics rather than a regression. Rollback is a code rollback; published rate
fields remain and are ignored by a restored reader.
