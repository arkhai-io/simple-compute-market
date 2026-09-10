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

**Goals.** Publish a rate buyers can filter and compare on, authored by the seller
who owns the capacity. Give the filter engine the two primitives that requires.
Keep the rate independent of the negotiation-side pricing work and
forward-compatible with it. Make it normative that nothing is constructed from
the number, and that a rate carries the period and asset it is quoted in.

**Non-Goals.** No settlement participation, no honesty enforcement, no change to
negotiation-floor policy, no restriction to unbacked listings, no cross-period or
cross-asset normalization, no change to the existing `number` value type.

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

**The accepted limitation.** A seller pricing RAM and GPUs differently cannot
express that here, and a buyer comparing two listings that bundle different RAM is
comparing bundled prices. Unbundling belongs to `capacity-shape-pricing`, which is
building it for the negotiation side; a second decomposition here would be exactly
the duplication that change exists to prevent. **Revisit trigger:** the first
buyer request to filter or sort on a per-dimension rate.

### The asking rate is a catalogue price; a rate structure never reinterprets it

Forward compatibility with `capacity-shape-pricing` needs stating more carefully
than an earlier version of this design managed. It asserted that when that change
lands, the published asking price simply *becomes* the minimum rate structure
evaluated at the advertised shape — which presumes a seller policy nobody has
chosen, and which reads as though the two are the same quantity.

They are not. The two future concepts are distinct:

- **the asking rate** — one listing-wide catalogue price for the advertised shape,
  published to buyers, from which nothing is constructed;
- **the minimum rate structure** — per-dimension negotiation-side pricing, so a
  seller can price a shape a buyer proposes.

A storefront **may** derive the asking rate by evaluating the structure at the
advertised shape, where that is the seller's chosen policy. It is not required to,
and the structure does not replace, subsume, or reinterpret the asking rate.

This matters because `capacity-shape-pricing`'s current text says "a listing today
advertises one rate" and interprets an existing single rate as "a structure whose
only priced dimension is the primary one." Read against the negotiation-floor rate
that sentence is about, that is correct. Read against a published asking rate — a
second kind of single advertised rate, which did not exist when it was written — it
would silently redefine the catalogue price as a primary-dimension rate. That
change's design and its `storefront-publication` delta are amended in the same
step so the two cannot be read as the same quantity.

The field survives either way, which is what makes this safe rather than
expedient: its shape and meaning do not change, only where a storefront may source
the number. That is not true of the reverse — publishing a per-dimension structure
now would commit buyers and registries to a shape before the change that defines
it has been designed.

### The asset is an opaque identifier, and the amount is exact decimal text

A rate is uninterpretable without the asset it is quoted in, so the field carries
one. The question was whether to express it as the structured token metadata the
negotiation path uses or as something narrower.

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
prices in a currency, and the marketplace is composing off-chain settlement
mechanisms — hosted fiat is already a registered mechanism with three funding
profiles. Requiring token metadata would exclude the exact sellers unbacked
listings exist to serve and would need widening the moment an asking rate is
quoted in anything a chain does not mint. An opaque identifier is the shape that
survives that.

**Decimal text, for two reasons in order of directness.** The operative one is
exact decimal semantics: a binary float cannot represent ordinary decimal prices —
`0.1` has no exact double — so any float encoding introduces error at the values
this field will mostly hold, which rules out the existing `number` type. The second
rules out the integer alternative: base-unit integers cannot express a fraction at
all, need a companion decimals field to be interpreted, and overflow what a 64-bit
integer holds once an 18-decimal asset's exponent is folded in. Decimal text needs
no companion field and loses nothing. Note the asking amount is deliberately *not*
base units, so the overflow argument is about why integers were rejected rather
than about this encoding.

**A rate bound carries an asset and a period, and all three travel together.** A
query bounded at `5` cannot be evaluated without knowing five of what and per
what, so a rate-bounded query names the asset and the period, and publication
refuses a rate missing either. This mirrors the existing rate-and-unit-together
invariant on the settlement publication clause rather than inventing a rule.

**Assets match, they are not converted** — the same rule the period takes, and on
stronger grounds. Converting a period is trivial arithmetic rejected below on
demand-side grounds. Converting an asset is not arithmetic at all: it needs an
external exchange rate that moves continuously, which would make a filter result
depend on when it ran and would put the marketplace in the business of valuing
assets — a surface it does not have and this change does not open. A listing
quoting an asset the query did not name is excluded.

**Revisit trigger:** the first request to compare rates across assets, which needs
a valuation source and is a different feature from filtering.

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
every other registry deployment's spec. A new type leaves those untouched and
makes the choice visible in the specification a registry serves.

Two properties make this cheaper than it looks. `ValueType` is a closed `Literal`,
so the vocabulary extension is one entry plus a coercion branch and the range
domain. And the buyer side already renders `Decimal` exactly, so it needs one
mapping entry to `QueryValueType.DECIMAL` and no rendering change at all.

The ordering consequence is real and belongs in the migration plan: a registry
running the current engine, handed a filter spec declaring `decimal_text`, fails to
load that spec rather than ignoring the unknown type, because `FilterDecl` forbids
extras and `ValueType` is closed. The engine ships before any spec that uses it.

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
meaningful query in its own right — "listings quoted in this asset" — rather than
an error.

Spec validation rejects a `requires` entry naming an undeclared filter, naming
itself, or participating in a cycle. Those are specification defects that would
otherwise surface as a query that can never be satisfied.

**Hardcoding the rule was the alternative and is not available.** A conditional
naming `asking_rate` in generic registry or `RegistryClient` code would violate
`registry-discovery`'s requirement that the compiler resolve every rule from the
active filter specification and add no domain fields. The engine's neutrality is
the property that lets one registry serve the compute, API-credit, and
introduction schemas, and spending it on the first field that needs a
co-requirement would be spending it permanently.

The mechanism is not without precedent here. `strict.<name>` is already a
cross-cutting query key resolved before the criterion loop, and
`_extract_strict_overrides` already validates that its target names a declared
filter — so a declared relationship between query keys is an existing shape in this
engine rather than a new concept.

### The seller states the asking rate at the origin site's pool

The rate is authored where the capacity is, as a declaration on the origin site's
Resource Pool, projected to the storefront and published from the projection. It
is a sibling of the domain's per-model pricing structure inside the already
projected domain-owned `pricing` policy tag, not a member of it: the asking rate is
listing-wide by the decision above, so nesting it under a capability family or a
GPU model would contradict that.

No `resource-pool-management` change follows. That capability already declares
`pricing` a domain-neutral opaque policy tag with unknown tags remaining
forward-compatible, so the VM domain owns the shape it reads inside it — which is
what `pricing_resolution.py`'s own docstring already says about the family-grouped
GPU structure.

**Precedence, and the limit on it.** The origin pool's declaration is
authoritative. A storefront-local per-pool override and the storefront's `[pricing]`
config default participate **only for the storefront's own `home_site` pools**, and
never for a pool at another origin.

That limit is not a preference. `_local_pool_pricing`'s docstring records that
`compute_capacity_pools` is keyed on `pool_id` alone, is deliberately not being made
multi-site-aware, and that "a non-home_site pool simply has no pricing source
through this table at all". So the override tier is already structurally
unavailable off-site. The config default is available and must be refused: Goal 7
moves deliberately toward one storefront publishing for several seller sites, and a
storefront-wide default reaching another origin's listings would advertise the
aggregator's price as that seller's asking price. That is the same class of failure
as revealing the wrong seller's contact details — a disclosure of the wrong party's
commercial position, not a degraded result.

A pool with no declaration and no applicable default publishes no asking rate. Its
listings publish normally and are excluded from rate-bounded queries, which is the
intended semantics rather than a failure.

**Malformed declarations fail closed, diverging from the resolver's convention on
purpose.** `_VALID_HINT_FIELD` treats a wrongly-shaped hint field as absent and
falls through, and `pricing_resolution.py` justifies that: propagating a malformed
value into a commercial candidate is worse than falling through the way a missing
value already does. That reasoning does not carry here. Falling through means
either publishing no rate — silently dropping a price the seller believes they
advertised — or, for a `home_site` pool, publishing the storefront's default in
place of the seller's broken declaration, which is worse still. And unlike
`min_price`, this value is public buyer-facing information. So a malformed or
partial asking-rate declaration fails its pool closed, matching how a malformed
backing value and an unaccepted mode value already behave, and absent stays
distinct from malformed.

**Lifecycle.** Changing the amount, asset, or period republishes the existing
listing under the same durable identity: this is a published-shape change flowing
from a source declaration, which `unbacked-listing-publication` already routes
through source-publication reconciliation rather than capacity reconciliation.
Removing the declaration republishes the listing without a rate — it stays
discoverable and drops out of rate-bounded queries. A backing change is the only
transition that closes and republishes under a new identity, and a rate change is
not one.

### The published shape and query vocabulary are frozen here

These are public schema decisions, so the delta names them rather than leaving them
to implementation. An earlier version of this design said the rate attaches to "the
same family-grouped capability shape the dimensions use". That was wrong:
`publish-multidimensional-listing-shape` deliberately keeps the flattened
convention — `gpu_count`, `memory_gib` — directly inside the listing resource, and a
listing-wide bundled price does not belong to a capability family in any case.

The published shape, after `settle-listing-vocabulary`:

```json
{
  "listing_resource": {
    "gpu_count": 8,
    "memory_gib": 512,
    "asking_rate": {
      "amount": "5.00",
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
`requires: [asking_rate_asset, asking_rate_period]`.

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

### The period is a local asking-rate contract accepting `hour`

The rate carries the period it is quoted per, and this version accepts `hour` and
nothing else.

An earlier version of this design described the period as "drawn from the canonical
time-unit vocabulary settlement rates use", which overstates what exists.
`SettlementPublicationClause.per` validates only against a canonical-lowercase-token
regex, not against a list. `RateValue.per` is a free string defaulting to `"hour"`,
and counted units — `credit`, `token`, `request` — are valid values that
`compute_rate_unit_total` handles while explicitly refusing time units. So
`PER_UNIT_SECONDS`, which holds exactly `{"hour": 3600}`, is the set of periods
settlement *arithmetic* can scale by time, not a publication vocabulary.

Validating `period in PER_UNIT_SECONDS` is still the right implementation, because
it keeps publication from accepting a period no settlement path can scale. But the
normative rule is stated as this version accepting the currently supported
time-rate unit, and widening it stays a decision rather than a side effect.
Otherwise adding a period for settlement arithmetic would silently make it
publishable and activate the cross-period discovery path below, which is
deliberately unexercised in production today.

This is also what keeps the conceptual separation the rest of the design works to
establish: a counted unit like `token` is not a period, and nothing about the
asking rate should inherit from a settlement unit axis it has no relationship to.

**The limitation this accepts.** Supply arranged out of band is commonly priced
monthly or per commitment. A seller who prices that way cannot express it in this
version; they publish an hourly equivalent or no rate. That is a real gap for the
exact sellers unbacked listings exist to serve, and it is accepted because adding a
period means adding it to `PER_UNIT_SECONDS` and to every arithmetic path that
reads it, which is settlement work rather than publication work. **Revisit
trigger:** a second entry in `PER_UNIT_SECONDS`, or the first seller request to
publish a non-hourly asking rate.

### The filter matches the period rather than normalizing across it

A rate-bounded query names the period it is asking about, and a listing quoted in a
different period does not match — it is excluded rather than converted.

Normalizing was the alternative and is rejected on demand-side grounds rather than
arithmetic ones. A buyer shopping for on-demand capacity at an hourly rate is not
looking for supply quoted monthly, because a monthly quote signals a monthly
commitment. Converting one to the other would return supply whose *terms* the buyer
did not ask for, dressed as a price match. Excluding it is the more useful answer
even though the arithmetic is trivial.

With one accepted period this rule has no observable effect today. It is stated now
so that accepting a second period does not silently turn every hourly query into a
cross-period comparison.

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
- **[A new value type fragments the filter vocabulary]** → `decimal_text` beside
  `number` means two numeric comparison domains, and a spec author can pick the
  wrong one. Accepted deliberately: the alternative retypes a value type other
  deployments' specs already use. Mitigated by making the type's comparison domain
  normative in `registry-discovery` rather than leaving it to the engine.
- **[Declarative co-requirements are more engine than this feature needs]** → One
  field's need has produced a general grammar extension. Accepted because the
  alternative violates a normative requirement rather than merely being less
  elegant, and because spec-driven neutrality is what lets one engine serve three
  schemas.
- **[Registry and buyer versions skew]** → A registry serving a spec with
  `decimal_text` or `requires` needs an engine that understands both, and a buyer
  compiling against an older filter-spec ETag is already rejected with 412. The
  new risk is deployment ordering, handled in the migration plan.
- **[An opaque asset identifier is ambiguous across deployments]** → Two
  storefronts could name the same asset differently, or the same string could mean
  different things to different registries. Accepted: the identifier is exactly as
  opaque as `settlement_options[*].asset` already is, so this adds no ambiguity
  the comparison grammar does not already carry, and an equality-only filter
  cannot silently mis-order two assets the way a conversion could.
- **[No storefront default off-site means remote listings often carry no rate]** →
  An aggregating storefront cannot fill the gap for a seller who declares nothing,
  so those listings stay out of rate-bounded discovery. Accepted: the alternative
  advertises the aggregator's price as the seller's, and a missing rate is an
  honest absence while a borrowed one is a false assertion.
- **[Failing a pool closed on a malformed rate is harsher than the resolver's
  convention]** → A typo in a pricing declaration stops that pool's listings
  rather than degrading them. Accepted for a public buyer-facing value with no
  lower tier to fall through to off-site; the divergence and its reason are
  recorded above so a later reader does not "fix" it toward the resolver's
  fall-through behaviour.
- **[Hourly-only excludes the sellers this serves]** → Out-of-band supply is often
  priced monthly, and those sellers publish an hourly equivalent or nothing.
  Mitigated only by the revisit trigger; the alternative is adding a time period to
  the settlement vocabulary, which is not this change's surface.
- **[A flat rate is later regretted]** → If per-dimension comparison turns out to
  be what buyers actually want, this field becomes a catalogue summary of something
  richer rather than the whole story. Acceptable because the field survives that
  change intact and because the alternative was blocking comparison behind two
  unstarted changes.

## Open questions

None. The asset expression, the two registry primitives, the seller's authoring
authority, and the frozen wire and query vocabulary are all decided above.

## Migration Plan

1. Extend the filter engine: `decimal_text` and `requires`, on both the registry
   and the buyer compiler, with spec validation for malformed, self-referential,
   and cyclic `requires`.
2. Add the origin-pool asking-rate declaration and its projection, and publish the
   `listing_resource.asking_rate` object from it.
3. Add the four filter declarations to `core/registry/filter-spec.yaml`.

Step 1 before step 3 is a hard ordering rather than a preference: a registry
running the current engine fails to load a spec declaring `decimal_text` or
`requires`, because `FilterDecl` forbids unknown keys and `ValueType` is a closed
literal. Deploy the engine before the spec that uses it.

Additive throughout for listings. A listing that publishes no rate behaves as it
does today except that it is excluded from rate-bounded queries, which is the
intended semantics rather than a regression. Adding filters changes the spec's etag
and buyers re-fetch, without a version bump. Rollback is a code rollback plus
reverting the spec entries; published `asking_rate` objects remain and are ignored
by a restored reader.
