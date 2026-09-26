# Design — publish indicative listing rates

## Context

Compute listings publish region, GPU model, form factor, and multi-dimensional
shape. Negotiation-floor pricing exists but is storefront-side policy input,
resolved through a three-tier precedence and explicitly not something that
constructs a settlement option or reaches a buyer.

A seller-advertised price is not entirely absent from the published shape, and it
is worth being precise about where it already exists, because that placement is
what constrains this change. `AcceptedEscrow.rates` carries every rate-bearing
field of an escrow template — a per-hour price for an ERC-20 escrow — with an empty
list meaning hidden reserve; `filter-spec.yaml` publishes both
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

**Bare metal is Goal 7's primary target domain.** Out-of-band supply is
overwhelmingly whole machines. This change therefore has to work for bare metal,
not only for VM, and bare metal cannot yet carry it: bare-metal publication reads
its pools' projected declarations but publishes no capability shape and no unbacked
listing. Each of those is owned by another change (see "Domain scope and
dependencies").

**The generic registry cannot evaluate the rate this change publishes, and that is
part of this change's scope rather than an implementation detail.** Two capability
gaps, both in the schema-driven filter engine:

`_Range.min` and `_Range.max` in `core/registry/src/api/filter_eval.py` are typed
`float | int | None`, `_coerce_scalar` parses `value_type: number` with
`float(raw)`, and range evaluation reads only resolved values satisfying
`isinstance(v, (int, float))`. A decimal-text listing value is therefore not
merely rounded — it is excluded from the comparison entirely and matches no range
at all. The buyer side is already correct: `_value_type` maps a filter-spec
`number` to `QueryValueType.DECIMAL` and `_scalar` renders a `Decimal` with
`format(value.normalize(), "f")`, no binary-float conversion anywhere. Precision is
constructed correctly, transmitted correctly, and destroyed at the server.

`FilterDecl` sets `extra="forbid"` and carries `name`, `path`, `query_name`,
`query_aliases`, `op`, `value_type`, `alias_kind`, `on_missing`, and `indexed` —
no relationship between filters. `build_criteria` iterates supplied parameters
independently. So "a rate bound requires an asset and a period" has no declarative
expression, and a `requires:` key added to the YAML would fail spec validation
rather than be ignored.

Neither can be worked around locally. `registry-discovery` requires that a buyer
resource-query compiler "MUST resolve every field, operator, type, alias, and
missing-value rule from the active registry filter specification" and "MUST NOT
add domain fields", and that a registry compile filters from its configured
filter-spec "rather than hardcoding a concrete market schema". A conditional
naming `asking_rate` inside generic registry or client code would violate a
normative requirement, not merely a convention.

## Goals / Non-Goals

**Goals.** Publish a rate buyers can filter and compare on, per listing shape,
stated by the site that owns the capacity and overridable by the storefront that
publishes it. Give the filter engine the two domain-neutral primitives that
requires, and nothing rate-shaped. Serve VM and bare metal through one
declaration form. Keep the rate independent of the negotiation-side pricing work
and forward-compatible with it. Make it normative that nothing is constructed from
the number, and that a rate carries the period and asset it is quoted in.

**Non-Goals.** No settlement participation, no honesty enforcement, no bound on
an agreed price, no change to negotiation-floor policy, no restriction to unbacked
listings, no cross-period or cross-asset normalization, no change to the existing
`number` value type, and no rate concept in the registry engine.

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
advertises either; `compute_capacity_claim_from_order` builds a claim from exactly
the quantities a listing's shape declares, and nothing checks the declaration
against the hardware. A misleading rate and a misleading shape are discovered the
same way and reach the same control: registry curation, out of band.

These are statements about what a storefront builds, so they are promoted to
`storefront-publication`, not to `registry-discovery`.

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

So the relationship is stated rather than enforced:

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

**Revisit trigger:** the first buyer request to filter on an escrow or option rate
value, which is a different feature from this one and would need its own reasoning
about the settlement carrier.

### One rate per listing shape, not a per-dimension structure

The asking rate prices a listing shape: the whole, fixed bundle one listing
advertises. A pool that publishes a 1-GPU and an 8-GPU shape publishes two
listings and two rates; a pool-wide rate would price them identically, which is
wrong for every seller whose pool offers more than one shape.

It is not decomposed per dimension. `capacity-shape-pricing` exists because
negotiation has one degree of freedom, so a seller cannot answer "what would this
cost with more RAM and fewer GPUs" — which is why `_validate_vm_opening` refuses a
buyer whose requested shape differs from the listing's (`resource_shape_not_negotiable`).
Per-dimension rates, an injectable aggregator, and a negotiated rate multiplier all
exist to price a shape the buyer proposes. A published asking price prices a shape
that does not vary.

**The accepted limitation.** A seller pricing RAM and GPUs differently cannot
express that here, and a buyer comparing two listings that bundle different RAM is
comparing bundled prices. Unbundling belongs to `capacity-shape-pricing`, which is
building it for the negotiation side; a second decomposition here would be exactly
the duplication that change exists to prevent. **Revisit trigger:** the first
buyer request to filter or sort on a per-dimension rate.

### The asking rate is a catalogue price; a rate structure never reinterprets it

The two future concepts are distinct:

- **the asking rate** — one catalogue price for one advertised listing shape,
  published to buyers, from which nothing is constructed;
- **the minimum rate structure** — per-dimension negotiation-side pricing, so a
  seller can price a shape a buyer proposes.

A storefront **may** derive the asking rate by evaluating the structure at the
advertised shape, where that is the seller's chosen policy. It is not required to,
and the structure does not replace, subsume, or reinterpret the asking rate.
`capacity-shape-pricing`'s design already carries this reading: its single-rate
compatibility rule names the negotiation-side rate and excludes a published asking
rate explicitly.

The field survives either way: its shape and meaning do not change, only where a
storefront may source the number. That is not true of the reverse — publishing a
per-dimension structure now would commit buyers and registries to a shape before
the change that defines it has been designed.

### The asset is an opaque identifier, and the amount is exact decimal text

A rate is uninterpretable without the asset it is quoted in, so the field carries
one.

`SettlementPublicationClause` in `kit/settlement-runtime` already answers this for
the publication surface, and the asking rate reuses that answer rather than
stating a second one. That clause carries `asset` as a trimmed, non-empty **opaque
string**, `rate` as positive **decimal text** without an exponent, and requires the
rate and its unit to be supplied together. On the query side, `asset` is a typed
field descriptor restricted to equality operators — `EQUAL`, `NOT_EQUAL`, `IN`,
`NOT_IN` — so assets are already matched and never ordered or converted anywhere in
the system.

**Structured token metadata was the alternative and is rejected as too narrow.**
`ERC20TokenMetadata` carries a contract address, decimals, and a chain ID, all of
which presume an on-chain ERC-20. A seller arranging supply out of band commonly
prices in a currency, and hosted fiat is already a registered mechanism with three
funding profiles. An opaque identifier is the shape that survives that.

**Decimal text, for two reasons in order of directness.** A binary float cannot
represent ordinary decimal prices — `0.1` has no exact double — which rules out the
existing `number` type. And base-unit integers cannot express a fraction, need a
companion decimals field to be interpreted, and overflow 64 bits once an
18-decimal asset's exponent is folded in. The asking amount is deliberately *not*
base units, so the overflow argument is about why integers were rejected rather
than about this encoding.

**A rate bound carries an asset and a period, and all three travel together.** A
query bounded at `5` cannot be evaluated without knowing five of what and per
what, so a rate-bounded query names the asset and the period, and publication
refuses a rate missing either. This mirrors the rate-and-unit-together invariant
on the settlement publication clause rather than inventing a rule.

**Assets match, they are not converted.** Converting an asset needs an external
exchange rate that moves continuously, which would make a filter result depend on
when it ran and would put the marketplace in the business of valuing assets. A
listing quoting an asset the query did not name is excluded. **Revisit trigger:**
the first request to compare rates across assets, which needs a valuation source
and is a different feature from filtering.

### The registry gains two domain-neutral primitives and nothing rate-shaped

The registry is deliberately more domain-agnostic than a storefront or the
provisioning service: it serves compute, API-credit, and introduction schemas
today, and not every market has a rate — an NFT market has a sale price with no
period. So the division of ownership is strict:

- **Engine code** (`core/registry`, `core/registry-client`) gains an exact-decimal
  value type and declarative filter co-requirements. Neither names a rate, an
  asset, a period, or any compute field, and both are opt-in: a specification that
  declares neither behaves exactly as today, down to its etag. An NFT sale price
  would use the decimal type with no co-requirement at all.
- **The compute filter specification** (`core/registry/filter-spec.yaml`) is
  compute-owned data the generic registry serves. It declares the `asking_rate`
  object in its `listing_shape` and the four filters over it. Everything
  rate-specific, including the `hour` period, lives here or in the storefront.
- **The storefront** refuses an incomplete or invalid rate at publication.

**Registry-side refusal of a malformed rate was considered and is not available.**
The registry validates the full `listing_shape` only in its dry-run route;
`reject_retired_listing_shape` records that full enforcement at the publish
boundary "would reject listings this registry has accepted for as long as it has
existed", and deliberately refuses only retired spellings. Declaring `asking_rate`
in the compute `listing_shape` therefore makes the dry run and the served
self-description accurate, and nothing more. The storefront, which builds the
listing, is the only boundary that refuses it.

### Exact decimal comparison is a declared registry capability

The filter engine gains a new declarative value type rather than a change to the
existing one:

```yaml
value_type: decimal_text
```

Its wire and listing representation is a JSON string; its comparison domain is
Python `Decimal`. Range bounds parse to `Decimal`, resolved listing values are
accepted when they are decimal-text strings, and comparison is exact.

**Changing `number` was the alternative and is rejected.** `number` is declared on
`sla` today and on every JSON-number field a future spec declares; retyping its
comparison domain would silently change the semantics of existing filters and of
every other registry deployment's spec.

`ValueType` is a closed `Literal`, so the vocabulary extension is one entry plus a
coercion branch and the range domain. The buyer side already renders `Decimal`
exactly, so it needs one mapping entry to `QueryValueType.DECIMAL` and no rendering
change.

A registry running the current engine, handed a filter spec declaring
`decimal_text`, fails to load that spec rather than ignoring the unknown type,
because `FilterDecl` forbids extras and `ValueType` is closed. The engine ships
before any spec that uses it.

### Filter co-requirements are declared, not hardcoded

`FilterDecl` gains a `requires` list naming other declared filters that must be
supplied alongside it:

```yaml
- name: asking_rate_max
  requires: [asking_rate_asset, asking_rate_period]
```

Both the registry and the buyer query compiler read it from the specification. A
query supplying a filter without its co-requirements is refused; the dependency is
one-directional, so supplying an asset or a period without a bound remains a
meaningful query in its own right. `requires` names filter `name`s; the buyer
compiler maps them to the query names a buyer writes.

Spec validation rejects a `requires` entry naming an undeclared filter, naming
itself, or participating in a cycle.

**Hardcoding the rule was the alternative and is not available.** A conditional
naming `asking_rate` in generic registry or `RegistryClient` code would violate
`registry-discovery`'s requirement that the compiler resolve every rule from the
active filter specification and add no domain fields. The engine's neutrality is
the property that lets one registry serve the compute, API-credit, and
introduction schemas.

The mechanism is not without precedent. `strict.<n>` is already a cross-cutting
query key resolved before the criterion loop, and `_extract_strict_overrides`
already validates that its target names a declared filter.

**Version skew is safe in both directions.** An older buyer ignores `requires` and
cannot pre-validate the rule, but the registry refuses the query, so the registry's
refusal is authoritative. A newer buyer against an older specification treats an
absent `requires` as empty.

### An undeclared co-requirement leaves the specification's etag unchanged

The etag is a SHA-256 over the canonical encoding of the specification's version,
listing shape, and every filter declaration serialized field by field
(`model_dump(exclude_none=False)`). Its contract is that it changes when the
semantics a buyer compiled against change. A `requires` field defaulting to `[]`
would add `"requires": []` to every filter of every deployment's specification —
compute, API credits, and introductions alike — and rotate every etag on the engine
upgrade alone, with no semantic change anywhere.

The practical cost of that rotation would be small: buyers fetch the specification
on every command, the etag is recorded in explanation output but never replayed,
and no fixture pins one. It is still refused, because a rotation that does not mean
a semantic change weakens the only signal the etag exists to give, and the engine
already has the rule this follows: schema identity participates in the etag only
when a specification declares it.

So a filter declaring no co-requirement serializes — into the etag and into the
served body — exactly as it does under an engine without the capability. The
existing precedent test (`test_etag_unchanged_for_specs_without_schema_identity`)
builds its expected payload from the model's own dump and so would not catch a new
defaulted field; the new guarantee is pinned against a literal digest instead.

### The seller states a rate per shape, beside the shape rather than inside it

A site declares asking rates on a Resource Pool in a new `asking_rates` policy tag,
keyed by offering mode like `listing_shapes`. Each entry names the capability
shape it prices and the rate:

```yaml
policy_tags:
  listing_shapes:
    vm:
      - {gpu: {model: H100, count: 1}}
      - {gpu: {model: H100, count: 8}, memory: {gib: 512}}
  asking_rates:
    vm:
      - shape: {gpu: {model: H100, count: 1}}
        amount: "2.10"
        asset: usd
        period: hour
      - shape: {gpu: {model: H100, count: 8}, memory: {gib: 512}}
        amount: "16.00"
        asset: usd
        period: hour
```

An entry applies to the listing whose shape has the same canonical digest. The
matching is exact; a shape that is priced nowhere publishes no rate.

**Inside the shape was the first alternative, and it is not available.** A VM
listing shape is strictly family-grouped and the VM vocabulary rejects a key it
does not define. More importantly, the shape's digest is part of the listing's
derivation identity, so a rate inside it would turn every price change into a
close-and-republish rather than an update in place.

**Wrapping each `listing_shapes` entry (`{shape, rate}`) was the second, and it
does not serve bare metal.** A bare-metal pool states no shape list; its listings'
shapes are derived from each Physical Resource. A wrapped entry would give VM and
bare metal two declaration forms for one concept. A keyed list works for stated,
generated, and derived shapes alike — a site may price a VM default-generated shape
by naming it.

**Inside the domain-owned `pricing` tag was the third, and it is rejected in favour
of a kit-owned tag.** VM and bare metal read the declaration identically, so it is
one shared reader and one structural check at every pool-write surface, exactly as
`listing_shapes` has. Leaving it inside an opaque domain-owned tag would make the
same structure domain-owned twice. This is a `resource-pool-management` change: a
new domain-neutral key whose structure the kit validates at write time and whose
shape vocabulary and accepted periods the reading domain validates.

`capacity-shape-pricing` rejected a parallel rate map beside its shape because that
map was keyed by the shape's own families and could fall out of step with them.
This list is keyed by the whole shape — the listing's identity — so an entry either
names a published shape or has no effect, and an entry with no effect is reported.

### The storefront has final authority over the published rate

Precedence follows the listing-shape pattern: the site states an opinion and the
storefront may override it.

1. The storefront's site-scoped pool override, when it states asking rates.
2. Otherwise, the pool's `asking_rates` declaration.
3. Otherwise, no asking rate.

An override's asking rates replace the pool's as a whole list, like its shapes and
settlement clauses. Unlike shapes, an empty list is accepted and means the
storefront publishes no asking rate for that pool: withholding a price is a
legitimate commercial choice, whereas an empty shape list would stop sales, which
is done by closing listings. Rates stay keyed by shape across the tiers, so an
override that states shapes but no rates still takes the pool's rates for every
shape the two share.

The override is available for a pool at any site the storefront publishes for. It
is an explicit, per-site, per-pool statement by the storefront operator, so it is
compatible with one storefront publishing for several seller sites.

**There is no storefront configuration default.** A default keyed by GPU model has
nothing to identify a shape, and a storefront-wide default reaching another site's
listings would advertise the aggregator's price as that site's without anyone
having stated it. Every published rate is therefore either the site's own
declaration or an explicit override.

**Rejected: a home-site-only configuration default.** An earlier version of this
design let the storefront's `[pricing]` default and the legacy home-site override
row resolve an asking rate for home-site pools only. The site-scoped override store
superseded the reasoning: it applies to any site, and the legacy home-site tier is
being retired. Keeping a home-site carve-out would make one site special in a model
built for many.

**Rejected for now: a site-declared range enforced at provisioning.** The fuller
form of the hints pattern would let the site declare a range, bound the storefront
override within it, and have provisioning refuse a deal agreed outside it, as site
admission refuses a shape that does not fit. It is deferred, not refused, because:

- nothing commercial crosses the provisioning boundary today — a reservation
  carries no price — so the agreed rate would have to join the capacity claim;
- mechanisms normalize decimal prices to base units at publication and have no
  reverse conversion to compare an agreed amount with a decimal bound;
- the storefront's negotiation floor would have to be clamped to the site's floor,
  or a buyer would learn of the refusal only after funding;
- the site would see only what the storefront reports;
- none of it applies to unbacked listings, which are never provisioned, so it is
  not on Goal 7's path.

**Revisit trigger:** the first seller site that needs to bound what a storefront
publishing on its behalf may advertise or agree. The declaration form above admits
range fields beside the rate without restructuring.

This asymmetry with settlement defaults is deliberate. A storefront's configured
settlement clauses already reach every site's listings, because a mechanism rate
is the storefront's own settlement term as the counterparty. The asking rate states
a price for the listing's origin, so it comes only from the origin's declaration or
from an explicit per-site override.

### Malformed declarations fail their pool closed

A pool-write surface refuses an `asking_rates` value that is structurally
malformed. The reading storefront then validates what the kit cannot: that each
shape is in its domain's vocabulary, that no two entries price the same shape, and
that each period is one this version accepts. A declaration or override failing
any of those holds the pool's listings — neither published, closed, nor refreshed —
and is reported, as an unreadable shape list already is.

This diverges from `_VALID_HINT_FIELD`, which treats a wrongly-shaped pricing hint
field as absent and falls through, on purpose. Falling through here means silently
dropping a price the seller believes they advertised, and unlike `min_price` this
value is public buyer-facing information. An absent declaration and a malformed one
stay distinct.

### A rate is a term of sale, so a change refreshes the listing in place

Under `storefront-publication`'s "A listing's identity is the physical resource it
offers", price is a term of sale: a change updates the listing in place and keeps
its identity. The asking rate therefore joins the term fields the storefront's
listing comparison refreshes (`TERM_RESOURCE_FIELDS` in
`domains/vms/listings/listing_comparison.py` for VM), and is excluded from every
shape digest.

Changing an entry's amount, asset, or period republishes the listing under its
existing identity. Removing an entry, or the declaration, republishes the listing
without a rate: it stays discoverable and drops out of rate-bounded queries.

### The published shape and query vocabulary are frozen here

The asking rate is a sibling of the flattened dimension fields inside
`listing_resource`, not nested under a capability family:

```json
{
  "listing_resource": {
    "gpu_model": "H100",
    "gpu_count": 8,
    "ram_gb": 512,
    "asking_rate": {
      "amount": "16.00",
      "asset": "usd",
      "period": "hour"
    }
  }
}
```

The filter declarations, matching the existing `alias_kind` sugar convention:

| Filter name | Path | Op | Type |
|---|---|---|---|
| `asking_rate_max` | `$.listing_resource.asking_rate.amount` | `range` (`upper_bound`) | `decimal_text` |
| `asking_rate_min` | `$.listing_resource.asking_rate.amount` | `range` (`lower_bound`) | `decimal_text` |
| `asking_rate_asset` | `$.listing_resource.asking_rate.asset` | `in` | `string` |
| `asking_rate_period` | `$.listing_resource.asking_rate.period` | `in` | `string` |

All four are `on_missing: fail`. Both bounds declare
`requires: [asking_rate_asset, asking_rate_period]`. Their buyer-facing query names
are an open question below.

### Exact filters, failing on missing

Every published-shape filter in `filter-spec.yaml` is `on_missing: fail`, and the
file states that an unknown spec cannot be assumed to satisfy a stated requirement.
Rate follows that convention for the same reason it exists: a listing with no
published rate has not shown it is under a buyer's maximum.

The underreport-friendly `on_missing: pass` convention applies to
`accepted_escrows` and `settlement_options` paths, where tolerating a seller who
lists fewer options than they accept is the intent. That is not this case.

### Rates are not confined to unbacked listings

A backed seller may also want to advertise an asking rate, and confining the field
would make it a second encoding of backing. Backing has its own field precisely so
nothing else has to carry it implicitly.

### No honesty control

Nothing keeps a published rate current or truthful, and a seller pays nothing to
advertise one they will not honour. The intended control is registry curation: an
operator delisting a storefront whose listings prove dishonest. That sits outside
the registry service boundary and is not implemented in this repository. Because
registries are independently operated, buyer-experience feedback reaching a curator
is a property of a particular deployment rather than of the market.

**Revisit trigger:** the first evidence of published rates diverging
systematically from agreed ones, or the first operator request for a delisting
mechanism.

### The period is a local asking-rate contract accepting `hour`

The rate carries the period it is quoted per, and this version accepts `hour` and
nothing else.

`SettlementPublicationClause.per` validates only against a canonical-lowercase-token
regex, not against a list. `RateValue.per` is a free string defaulting to `"hour"`,
and counted units — `credit`, `token`, `request` — are valid values that
`compute_rate_unit_total` handles while explicitly refusing time units. So
`PER_UNIT_SECONDS`, which holds exactly `{"hour": 3600}`, is the set of periods
settlement *arithmetic* can scale by time, not a publication vocabulary. The table
exists in both `market_core.schemas` and `market_alkahest.schemas`; parity is checked
against `market_core.schemas`, the lower layer.

Validating the period against that table keeps publication from accepting a period
no settlement path can scale. But the normative rule is stated as this version
accepting the currently supported time-rate unit, and widening it stays a decision
rather than a side effect of adding a period for settlement arithmetic.

**The limitation this accepts.** Supply arranged out of band is commonly priced
monthly or per commitment; such a seller publishes an hourly equivalent or no rate.
**Revisit trigger:** a second entry in `PER_UNIT_SECONDS`, or the first seller
request to publish a non-hourly asking rate.

### The filter matches the period rather than normalizing across it

A listing quoted in a different period than the query names does not match — it is
excluded rather than converted. A buyer shopping for on-demand capacity hourly is
not looking for supply quoted monthly, because a monthly quote signals a monthly
commitment. With one accepted period this rule has no observable effect today; it
is stated so that accepting a second period does not silently turn every hourly
query into a cross-period comparison.

### Domain scope and dependencies

The declaration, precedence, validation, and publication rules above are one
implementation serving both compute-family domains. They reach each domain as
follows.

- **VM** publishes listing shapes from resource-pool projections, joins the
  site-scoped override store, and refreshes terms in place today. It needs nothing
  from another change to publish an asking rate.
- **Bare metal** needs three things, the first of which is now in place:
  - it must read its pools' projected declarations —
    `bare-metal-publication-reads-pool-declarations`, complete;
  - it must publish a capability shape per listing, since the shape is the rate's
    key, and must join the site-scoped override store for the storefront tier —
    `bare-metal-listing-shapes`. That change also makes bare-metal listings visible
    to the compute schema's dimension filters, which read top-level
    `listing_resource` fields that bare metal currently nests under `capabilities`;
  - it must publish unbacked listings at all — `unbacked-bare-metal-listings` — for
    the supply Goal 7 exists to serve to carry a rate.

Implementation of this change therefore waits on the first two. Its system
evidence for unbacked supply waits on `unbacked-bare-metal-listings` for bare
metal and `compose-contact-exchange-across-compute` for VM. The registry primitives
have no domain dependency and may land first.

## Risks / Trade-offs

- **[Buyers read an asking rate as a quote]** → Partly mitigated by the normative
  statement that nothing is constructed from it. Not fully mitigable: a number in a
  catalogue reads as a price.
- **[A listing publishes two prices that disagree]** → Accepted rather than
  solved, and stated normatively so a reader can tell which number binds.
- **[A new value type fragments the filter vocabulary]** → `decimal_text` beside
  `number` means two numeric comparison domains. Accepted: the alternative retypes a
  value type other deployments' specs already use. Mitigated by making the type's
  comparison domain normative.
- **[Declarative co-requirements are more engine than this feature needs]** →
  Accepted because the alternative violates a normative requirement, and because
  spec-driven neutrality is what lets one engine serve three schemas.
- **[Registry and buyer versions skew]** → A registry serving a spec with
  `decimal_text` or `requires` needs an engine that understands both. Handled by
  the migration ordering; existing specifications are unaffected, etag included.
- **[An opaque asset identifier is ambiguous across deployments]** → Accepted: the
  identifier is exactly as opaque as `settlement_options[*].asset` already is, and
  an equality-only filter cannot mis-order two assets the way a conversion could.
- **[A storefront may publish a rate its site never stated]** → Accepted: the
  storefront has final authority, and an override is an explicit per-site act
  reported in system status. A site that needs to bound it waits on the deferred
  range decision.
- **[A seller must price each shape separately]** → A pool offering many shapes
  needs many entries. Accepted: a rate for a bundle is only meaningful for that
  bundle, and deriving one from another is per-dimension pricing.
- **[Failing a pool closed on a malformed rate is harsher than the resolver's
  convention]** → Accepted for a public buyer-facing value; the divergence is
  recorded above so a later reader does not "fix" it toward fall-through.
- **[Hourly-only excludes the sellers this serves]** → Mitigated only by the
  revisit trigger.
- **[Bare metal waits on two changes]** → The primary target domain cannot publish
  a rate until its publication reads declarations and publishes shapes. Accepted:
  a bare-metal-specific declaration form would be a second implementation of the
  same concept, against the rule that domains use the same kit mechanisms.

## Open questions

- **Buyer-facing query names for the two bounds.** The shared query language
  allows each field once per query, and both bounds share one path, so they need
  distinct `query_name`s. The existing convention gives the bare field name to a
  lower bound (`gpu_count`). Undecided whether `asking_rate` names the upper bound
  (buyers mostly bound price from above) with `asking_rate_min` for the lower, or
  both keep suffixed names. No task prescribes an answer; the filter-declaration
  task is a decision gate for it.

## Migration Plan

1. Extend the filter engine: `decimal_text` and `requires`, on both the registry
   and the buyer compiler, with spec validation for malformed, self-referential,
   and cyclic `requires`, and with an undeclared `requires` leaving existing
   specifications' serialization and etag unchanged.
2. Add the `asking_rates` policy tag and its structural check at every pool-write
   surface.
3. Add the asking-rate resolution, the override term, and publication of
   `listing_resource.asking_rate` for VM; then for bare metal once its dependencies
   have landed.
4. Add the `asking_rate` object to the compute `listing_shape` and the four filter
   declarations to `core/registry/filter-spec.yaml`.

Step 1 before step 4 is a hard ordering: a registry running the current engine
fails to load a spec declaring `decimal_text` or `requires`. Deploy the engine
before the spec that uses it.

Additive throughout. A pool with no `asking_rates` publishes as it does today, and
its listings are excluded from rate-bounded queries, which is the intended
semantics. Adding the filters changes the compute specification's etag and buyers
re-fetch, without a version bump; other specifications' etags do not change.
Rollback is a code rollback plus reverting the spec entries; published
`asking_rate` objects remain and are ignored by a restored reader, and stored
`asking_rates` tags remain opaque policy metadata to an older kit.
