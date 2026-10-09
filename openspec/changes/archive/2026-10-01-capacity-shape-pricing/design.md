# Design

## Context

Re-verified against the tree on 2026-10-01, including `publish-indicative-listing-rates` as landed. The original planning-time context
(2026-08-06) described a per-GPU-model `min_price` as the price a listing
publishes; that stopped being true when publication pricing moved to typed
settlement clauses, and the decisions below are written against the tree as it is.

- **A listing's price is a settlement clause's rate.** Publication builds every
  VM listing's options from a complete list of typed clauses,
  `{mechanism, asset, rate, per, mechanism_input}`
  (`kit/settlement-runtime`'s `SettlementPublicationClause`). `rate` is positive
  decimal text in the asset's display units and `per` is a unit (`hour` is the
  only time unit `PER_UNIT_SECONDS` defines). The owning mechanism scales the
  rate to integer base or minor units and the result becomes
  `SettlementOption.rates: [RateValue(field="amount", per, value)]`. The option's
  `option_id` is a SHA-256 over its rates, so changing a published rate changes
  the option's identity.
- **A clause rate is a flat rate per listing-hour.** Nothing scales it by any
  quantity in the listing's shape. The default shape generator
  (`arkhai_vms.shape_generation.gpu_count_shapes`) publishes one listing per GPU
  count from one to the largest member's count, so every GPU-only default
  listing of one model publishes the same rate: a 1×H100 and an 8×H100 listing
  both cost the configured `100/hour`.
- **Clause lists resolve as whole lists per tier**, per GPU model: the
  site-scoped storefront pool override (else the legacy home-site row), then the
  pool hint `pricing.gpu.<model>.settlements`, then
  `[pricing.defaults.gpu.<model>].settlements`, then `[pricing].settlements`
  (`reconciler._projected_pool_rows` → `pricing_resolution.resolve_gpu_pricing`;
  `VmPublicationCycle._create_request` reads only `settlements` and
  `max_duration_seconds` from the result).
- **`min_price` and `token` resolution is dead.** `resolve_gpu_pricing` still
  resolves both per model through the three tiers, and the candidate carries
  them, but no publication or negotiation path reads either. The live floor is
  `[pricing].default_min_price`, read directly by `negotiation_runtime` and used
  by `extract_initial_price_from_order` only when a listing's first accepted
  escrow advertises no rate (a hidden reserve). Its unit is base units per hour.
  `default_token_address` is read only into the dead resolution and by the
  legacy pricing migration.
- **The seller's reference amount ignores the buyer's selection.** It is
  `primary_rate_value(accepted_escrows[0])` scaled by the requested duration in
  `_seller_reference_amount`, else the `default_min_price` floor. A settlement
  option bargains a scalar whenever it carries an `amount` rate, so a hosted
  option is scalar; but a hosted-only listing has no accepted escrow and
  negotiates against the floor, and a listing offering both mechanisms
  negotiates a hosted selection against the Alkahest rate, in another asset's
  units. `kit/negotiation-runtime` holds the buyer's pinned proposal where it
  calls the domain's `reference_amount` hook but does not pass it; the VM and
  API-credit storefronts are the hook's two implementers. The API-credit hook
  also computes `int(Decimal(str(unit)) * quantity)` under the default decimal
  context.
- **`RateValue` and `PER_UNIT_SECONDS` exist twice**, in `market_core.schemas`
  and `market_alkahest.schemas`.
- **`kit/capability-shape`** defines the family-grouped shape and its
  schema-driven flattening; it imports only the standard library. The compute
  family's schema is `COMPUTE_CAPABILITY_SCHEMA` in `domains/compute`
  (`arkhai_compute`), shared by the VM and bare-metal domains, with families
  `gpu` (`count`, required `model`), `cpu.count`, `memory.gib`, and
  `storage.gib`. Shapes are digested over their families.
- **Asking rates are a separate, landed term.** `publish-indicative-listing-rates`
  publishes a per-shape `asking_rate` on the listing resource, resolved from an
  override's `asking_rates` or the pool's declaration, never decomposed per
  dimension, and constructing nothing. An unreadable asking-rate declaration
  holds the pool rather than falling through to a lower tier. Pool writes on the
  provisioning service check its structure (`validate_asking_rates`) beside the
  other hint validators.
- **The registry keeps a fixed column set.** Its filter spec admits additional
  top-level listing properties, but the publish route stores only
  `listing_resource`, `accepted_escrows`, `settlement_options`, `demands`,
  `max_duration_seconds`, and `oracle_address`; any other top-level field
  validates and is discarded. The storefront serves its own listing record at
  the unauthenticated `GET /api/v1/listings/{listing_id}`.

Numeric hazards found in the same pass, all on paths this change touches or
feeds:

- `_seller_reference_amount` computes `Decimal(per_hour) * seconds // 3600`
  under the default 28-significant-digit decimal context. A base-unit rate with
  21 significant digits (an 18-decimal token priced at `123.456789012345678901`
  per hour) over a one-year duration needs 29 digits, so the product is silently
  rounded.
- `extract_initial_price_from_order` parses `default_min_price` with `float()`.
- The Alkahest and hosted mechanism scalers compute
  `Decimal(rate) * Decimal(10) ** exponent` under the same context. A rate with
  more than 28 significant digits is rounded before the "more than N decimal
  places" check runs, so a non-exact rate can pass as exact. A composed total is
  a more plausible source of such a rate than a hand-written one.

## Goals / Non-Goals

**Goals:** a seller can state a price for each capacity family and have any shape
priced from it; every listing priced today keeps its current price and option
identities wherever its rates convert exactly; every amount on the pricing path is
exact; the aggregator is replaceable without touching negotiation; the seller's
reference amount is the rate of the option the buyer selected; the dead `min_price`
and `token` resolution is removed.

**Non-Goals:** protocol changes and the multiplier reinterpretation
(`negotiation-driven-capacity-resize`); admissibility of a requested shape
(`capacity-shape-envelope`) and the seller's check of one ahead of pricing
(`negotiation-driven-capacity-resize`); authoritative feasibility
(`negotiation-capacity-feasibility-probe`); hold billing
(`billable-capacity-reservations`); any second aggregator implementation;
advertising the rate structure through the registry; retiring the
`default_min_price` floor.

## Decisions

### The rate lives inside the capability it prices

Rejected: a parallel rate-keyed map alongside the shape (`{"gpu": 2.20, "cpu": 0.01}`).
It is a second structure keyed by the same families, so every read has to join two
shapes and every write can desynchronize them — a family present in one and absent from
the other is representable and meaningless.

Accepted: a rate is stated under the family it prices, in the same family-grouped
nesting the pricing hint already uses for `gpu`. One nesting serves all three tiers:

```yaml
# pool hint (policy_tags) and the site-scoped override's terms, identically
pricing:
  gpu:    { H100: { rates: [{ asset: "0x9fe4…", rate: "80",   per: hour }] } }
  cpu:    { rates: [{ asset: "0x9fe4…", rate: "0.5",  per: hour }] }
  memory: { rates: [{ asset: "0x9fe4…", rate: "0.05", per: hour }] }
```

```toml
# configured defaults
[pricing.defaults.gpu.H100]
rates = [ { asset = "0x9fe4…", rate = "80",   per = "hour" } ]   # per card-hour
[pricing.defaults.cpu]
rates = [ { asset = "0x9fe4…", rate = "0.5",  per = "hour" } ]   # per vCPU-hour
[pricing.defaults.memory]
rates = [ { asset = "0x9fe4…", rate = "0.05", per = "hour" } ]   # per GiB-hour
[pricing.defaults.storage]
rates = [ { asset = "0x9fe4…", rate = "0.001", per = "hour" } ]  # per GiB-hour
```

A family rate is asset-denominated and mechanism-neutral: it states what one unit of
the family costs per hour in one asset, and prices every clause paying in that asset.
A rate is positive decimal text in the asset's display units, the same form a clause
rate takes, and an explicit zero is refused: a family the seller does not charge for
is one it states no rate for. `per` must be a time unit, and every family rate applied
to one clause must name the same unit. The entry keys are `rate` and `per`, the
settlement clause's, because a composed rate becomes a clause's `rate` and `per`;
the landed asking rate's `amount` and `period` describe a different, non-composing
quantity.

A rate is never a `ShapeField`: shapes are digested over their families, and a rate
must not change a listing's shape digest or identity.

### Which families are priced, and by what key, is an explicit domain projection

Rejected: inferring the pricing key from the schema — "a family whose schema carries
an attribute is keyed by it". `CapabilitySchema` permits several attributes and
several quantities per family, so the inference is ambiguous in general and only
happens to fit the compute schema today.

Accepted: the domain states a pricing projection over its schema — the families a
rate may be stated for, each priced by its one quantity field, and for a family
priced per attribute value, which attribute. For VM: `gpu` priced by `count` per
`model`; `cpu` by `count`; `memory` and `storage` by `gib`. A test asserts the
projection agrees with the schema: every priced family has exactly the named
quantity field, and every pricing key is one of that family's attributes. The
aggregator refuses a family the projection does not price.

### A listing is either flat-priced or shape-priced, and is never free

- **Shape-priced** — some family resolves a non-empty rate list for the listing.
  Its clauses state mechanism, asset, and mechanism input only. For each clause
  whose mechanism negotiates a scalar amount, the storefront evaluates the listing's
  own shape against the family rates in that clause's asset, through the domain's
  aggregator, and supplies the result as the clause's `rate` and `per` before the
  mechanism compiles it. A clause whose mechanism declines the scalar
  (`contact-exchange.v1`, per `negotiation-protocol`'s "Scalar negotiation
  participation is a mechanism declaration") is passed through rateless in either
  mode: it carries no price to compose, and its mechanism refuses a rate.
- **Flat-priced** — no family resolves rates. A clause's own `rate` is the listing's
  rate whatever its shape, and a rateless Alkahest clause is a hidden reserve priced
  by the `default_min_price` floor, both exactly as today.

No family is special. A family the listing's shape names with no rate in a clause's
asset contributes nothing to that clause's price: stating a quantity commits it, and
does not mean the seller charges for it. The derivation report lists each family a
listing includes without a rate, per asset, so an operator can see what is bundled;
nothing is held or refused for it.

What is refused is a free listing. A candidate is refused, with a reason naming the
asset, when a scalar-negotiating clause's composed price is zero — no family the
shape names has a rate in that clause's asset, the likeliest cause being a mistyped
asset. A listing that publishes no settlement option at a non-zero price is never
posted to a registry and so is never negotiated. A candidate is also refused when a
shape-priced clause states its own `rate`: two sources for one price.

A family the listing's shape does not name contributes nothing to *its* price either;
see the next decision for why its rate is still recorded.

Worked example, one 18-decimal token, the rates above:
`{gpu: {count: 2, model: H100}, cpu: {count: 16}, memory: {gib: 128}}` prices at
`2×80 + 16×0.5 + 128×0.05 = 174.4` per hour, which the Alkahest mechanism scales to
`174400000000000000000` base units per hour. The GPU-only default listings of an
8-card H100 pool price at 80, 160, … 640.

### The recorded rate structure is everything that could price a revised shape

The structure a shape-priced listing records serves two purposes that must not be
conflated: its own price uses only the families its shape names, while a revised
shape — `negotiation-driven-capacity-resize`'s quote for "the same GPUs, more
memory" — needs the rates of families the advertised shape omits. A GPU-only
default listing whose seller prices memory must therefore still record the memory
rate.

The recorded structure is every family's resolved rate list for the listing's GPU
model. Rates for other GPU models are not recorded: the model is part of the
listing's identity, so no revised shape of this listing can change it. A change to
any recorded rate is a change to the listing's terms and refreshes it in place,
including one for a family the listing's own shape omits, which leaves its price
unchanged.

### Compatibility: the flat rate is never reinterpreted

This replaces the planning-time decision, which read an existing single-rate listing
as "a structure whose only priced dimension is the primary one" and claimed that
reproduced today's prices exactly. It does not: today's clause rate is per listing,
not per GPU, so reading it as a per-card rate multiplies the price of every listing
whose GPU count exceeds one — every default listing above the first count.

| | Planning-time decision (superseded) | Accepted |
|---|---|---|
| Meaning of an existing clause `rate` | A GPU-only per-dimension rate | A flat listing rate, never reinterpreted |
| Existing listing prices after deploy | Change ×N for GPU count N > 1 | Identical where rates convert exactly |
| Option identities and republication | Every multi-GPU option's `option_id` changes; every such listing refreshes | Unchanged where rates convert exactly |
| How per-family pricing starts | Implicitly, for everyone | Opt-in, by stating family rates |

The promise is bounded by exactness. A configuration whose rates convert exactly
publishes byte-identical settlement options. Two inputs that are accepted today only
through precision loss are refused afterwards, deliberately: a clause rate with more
than 28 significant digits that is not a whole number of base units, which today's
context-limited arithmetic can round into an apparently exact amount; and a
`default_min_price` given as a binary float, such as a TOML or Helm number with a
fraction, which is refused when a hidden-reserve negotiation first needs the floor.

**Neither mode is a published asking rate.** `publish-indicative-listing-rates`
publishes a listing-wide catalogue price on the listing resource, from which nothing
is constructed and which is never decomposed per dimension. The two are distinct
quantities. Family rates let a seller price a shape a buyer proposes; the asking rate
prices the one shape a listing advertises and is what a buyer compares on before
contacting anyone. A storefront **may** derive an asking rate by evaluating a
seller's family rates at the listing's advertised shape, where the seller's declared
policy says so. It is not required to, and neither quantity is read as the other.

### Settlement-option identity follows the composed rate

The recorded rate structure is never hashed into any identity. A settlement
option's identity is what it is today: a digest over its mechanism, asset, rates, and
parameters. A shape-priced option's rate is the composed rate, so a family-rate
change that changes a listing's composed rate changes that option's `option_id`,
exactly as editing a flat clause rate does today. The listing's identity is
unchanged: price is a term of sale.

### Family rates resolve through the existing tiers, one whole list per family

Rates resolve through the precedence `pools-8` established — site-scoped storefront
pool override, pool hint, configured default — independently per family, and per
model within `gpu`. Within one family, a tier's `rates` list replaces lower tiers'
lists as a whole, the way a tier's `settlements` list does: merging per asset across
tiers would let one family's price for one asset come from an override and for
another asset from a default, a combination no one wrote. An explicitly empty list is
a statement, so it stops lower tiers from supplying that family.

### An unreadable rate holds the pool, and the reason is visible

A rate that a tier states but the storefront cannot read is not treated as absent.
Falling through would publish a lower tier's rate — a price nobody stated for this
pool — where an asking rate's fall-through publishes only no rate; so this follows
`publish-indicative-listing-rates`' rule for unreadable asking rates: the pool is
held. Its listings keep their last-published terms and stay negotiable; nothing is
published or refreshed from the misread rate until it is fixed.

Three layers, by what each can know:

1. **The provisioning service refuses a malformed hint at write.** Every pool-write
   surface already checks hint structure (`validate_asking_rates`,
   `validate_listing_shapes`). A structural check of `pricing` rate lists joins them:
   each `rates` value is a list of entries naming an `asset`, positive decimal-text
   `rate`, and unit-token `per`, with no asset twice. It knows no family name, so it
   stays domain-neutral, as the asking-rate structure check is. A site administrator
   learns of the problem when writing the hint.
2. **The storefront holds what it still cannot read**: a hint written before the
   check existed, a family its pricing projection does not price, a non-time unit, or
   a stored override that bypassed the write-time check.
3. **The reason is diagnosable.** Derivation records each held pool's unreadable
   rates — tier, family, and problem — in its per-site derivation report, which the
   storefront's system status serves, beside `unreadable_asking_rates`, and logs it
   once per change. An administrator asking why a hint has no effect finds the pool
   held and the exact entry that could not be read.

A malformed rate in the storefront's own configured defaults is the operator's own
input: the storefront refuses to start with it.

### Price aggregation is a replaceable interface in its own foundation kit

Real capacity is not linearly priced — the last GPU on a host is worth more than the
first, and the reservable capacity per dimension being a function of current
occupancy applies to price as much as to availability. Linear summation ships as the
only implementation; what makes that safe is that evaluation is reached through an
injectable aggregator, so a non-linear or coupled aggregator is a new implementation
behind an unchanged interface.

The interface takes a shape, one asset's family rates, and the domain's pricing
projection, and returns an exact price per time unit in the asset's display units. It
does not assume the price is a sum, and nothing downstream may assume it either: no
caller may reconstruct a total by multiplying one family's rate by its quantity.

The interface and the linear implementation live in a new foundation kit,
`kit/capability-pricing` (`market_capability_pricing`), which depends only on
`kit/capability-shape`. `kit/capability-shape` is capacity vocabulary — structure,
flattening, digest — and pricing is commercial evaluation over that vocabulary;
keeping them apart keeps the shape kit's responsibility what its documentation says
it is. Other homes were considered and rejected: `kit/settlement-runtime` knows no
shapes, and depending on the shape kit would put capacity vocabulary beneath
mechanisms that have none; `kit/resource-pools` is an authority-layer kit that buyers
and hold billing should not depend on; `kit/policy` is schema-free negotiation
middleware. The domain selects the aggregator — for VM, `arkhai_vms` binds it with
its pricing projection — and operator configuration does not, so a deployment has
exactly one.

Evaluation is callable outside the negotiation path, so
`billable-capacity-reservations` can price a hold's burn rate and
`negotiation-driven-capacity-resize` a proposed shape without a refactor.

### `RateValue.per` stays a time unit; the quantity comes from the shape

A family rate is per unit per hour. Two ways to express that were considered:

1. Add a quantity dimension to `RateValue` alongside `per`.
2. Keep `RateValue` as-is and pair each family's rate with that family's own
   quantity from the shape at evaluation.

Option 2 is accepted. `RateValue` is on the wire, in option identity, and in escrow
obligation data, so widening it has the largest blast radius of anything here; and the
quantity is already present in the shape being priced — carrying it in the rate too
would let the two disagree. The published `RateValue` does not change: it still
carries the whole listing's rate.

### Every amount is exact, and nothing rounds silently

The pricing path touches on-chain amounts, whose base units routinely exceed 64 bits.
These rules apply to every value this change computes or feeds:

- **No binary floats, no context-limited arithmetic.** A decimal rate is parsed
  exactly into an integer coefficient and a scale from its digits, never through
  `float` and never through `Decimal` arithmetic under a precision context. Products
  and sums are Python `int`. The aggregator's result is rendered back as
  exponent-free decimal text.
- **The aggregator's result is exact.** A sum of products of finite decimals is a
  finite decimal, so no rounding happens inside evaluation. Converting it to base
  units is the consumer's step, with the consumer's stated rule: publication refuses
  a total that is not a whole number of base units, and later consumers that quote
  (`negotiation-driven-capacity-resize`, `billable-capacity-reservations`) round up.
- **One exact conversion helper.** `kit/settlement-runtime` gains one helper, beside
  clause validation, that converts decimal rate text and an asset exponent to integer
  base units exactly, refusing a non-whole result and a result above `2**256 - 1`. The
  Alkahest and hosted mechanism scalers use it in place of context-limited `Decimal`
  multiplication.
- **Reference amounts are integer arithmetic.** The VM `_seller_reference_amount`
  becomes `floor(rate × seconds / 3600)` on exact values, matching
  `compute_rate_total`; the API-credit reference amount becomes exact integer
  multiplication of its unit rate by the quantity.
- **The floor is parsed exactly.** `default_min_price` keeps its meaning — a
  negotiation floor in base units per hour, used only where the selected option has
  no rate — but is parsed as exact positive decimal text instead of through `float`.
- **No amount in a fixed-width column.** Amounts stay decimal text in JSON or in
  `TEXT` columns, never a SQLite `INTEGER`.

### The seller's reference amount is the selected option's rate

A seller negotiates from what the buyer actually selected. The reference amount is
the amount rate of the option the buyer's proposal selects — the matched accepted
escrow for an escrow proposal, the settlement option matched by `option_id` for a
settlement selection — scaled by the requested duration. The `default_min_price`
floor applies only when that option advertises no rate: a genuine hidden reserve.

This fixes a defect that predates shape pricing: a hosted-only listing negotiated
against the floor, and a listing offering two mechanisms negotiated a hosted
selection against the Alkahest rate in another asset's units. Shape pricing makes it
more consequential, because each asset's option now carries its own composed rate.

Which artifact a proposal selects is one shared operation,
`selected_settlement_artifact` in `kit/policy`, beside the matchers it composes, so
the two domains cannot answer the question differently.

`kit/negotiation-runtime`'s `reference_amount` hook gains the buyer's pinned
proposal, which the runtime already holds where it calls the hook. Both implementers
change: the VM storefront's kit hook and its round hook read the selected option, and
the API-credit storefront takes the new argument, its reference amount reading the
selected option likewise and becoming exact.

### The rate structure is a storefront-served term of sale, not a registry field

The registry discards top-level listing fields outside its fixed column set (see
Context), so a top-level `rate_structure` would be silently lost. Placing it in
`listing_resource` would survive storage but put asset-denominated payment pricing in
the capacity description and add a term every comparison must classify.

Accepted: the registry receives what it receives today — each settlement option
carries its composed rate for the listing's own shape, which is what discovery
compares. The recorded rate structure is a nullable `rate_structure` text column on
the generic storefront `listings` table, holding the domain's JSON: for a
shape-priced VM listing, each family's resolved rate list for the listing's model;
null for a flat-priced listing. `storefront-publication`'s "Commercial mapping
identity" keeps pricing on the generic table and forbids a domain mapping carrying
commercial fields, and the column's content is opaque to core as
`listing_resource`'s is. It is added as an additive entry in the storefront's
versioned migration chain, which `add-database-migration-commands` will run from an
explicit command rather than at client construction; the entry needs no change when
it does. The registry request is built field by field from the stored listing, so the
column never reaches a registry. It is returned by the storefront's listing read.

That read is unsigned. Whether a buyer may derive a quote from it, or needs the
structure bound into a signed negotiation response, is
`negotiation-driven-capacity-resize`'s decision, its first consumer. So is whether any
buyer needs the structure at discovery time; that would require the registry to keep
listing-level fields it currently discards, which is
`store-registry-listings-as-published`'s concern, and that change's accepted carrier
policy is the input to the decision.

### Scope edges

- **The local-table derivation path is flat-priced only.** Family rates resolve on the
  projection path, as site-scoped overrides do; the legacy local-table path, which
  `pools-9-retire-local-physical-authority` retires, never resolves them.
- **Helm values do not expose family-rate defaults.** The storefront chart's `pricing`
  schema describes the hosted-fiat flat clause form. Helm deployments price shapes
  through pool hints and site-scoped overrides. The chart keeps accepting
  `default_token_address` as a retired key.
- **The legacy pricing migration must not mistake family rates for legacy pricing.** It
  is narrowed to model tables stating the retired `min_price` or `token`.
- **Found, not changed here.** The legacy migration reads `default_min_price` as a
  display-unit rate for an Alkahest clause, while the negotiation floor reads the same
  key as base units per hour; the migration only runs on pre-clause configurations.

### The negotiated variable is unchanged here

This change states and evaluates rates; it does not change what a round negotiates.
Making the negotiated quantity a multiplier over the advertised minimum is one
deployment boundary with the field that lets a round carry a shape, so both belong to
`negotiation-driven-capacity-resize`. A shape-priced listing's options carry its
composed rate, and the reference amount reads it as it reads any rate.

### The dead `min_price` and `token` resolution is removed

Per-model resolution of `min_price` and `token`, the candidate fields that carry them,
and the `[pricing.defaults.gpu.<model>].min_price/token` and `default_token_address`
defaults feed nothing, and leaving them makes the resolver's documented contract
false. They are removed.

- **Stored site-scoped overrides.** `VmPoolOverrideTerms` validates an override only at
  write. Derivation reads stored terms through `vm_override_view`, which takes the
  keys it names and ignores the rest, so a stored override still carrying `min_price`
  or `token` stays readable; derivation reports the retired keys per pool. A write
  stating them is refused.
- **Configuration.** A configuration still stating the retired keys is accepted; they
  are not read, and startup reports them.
- **Unchanged:** the legacy pricing migration's reading of legacy inputs; the legacy
  local tables' columns (`pools-9-retire-local-physical-authority`); and
  `default_min_price` as the hidden-reserve floor.

### Seller feasibility of a requested shape is not this change's

The planning-time Section 5 — checking a buyer-requested shape before pricing it — has
two halves with existing owners. Its quantitative half is
`capacity-shape-envelope`'s admissibility predicate. Its categorical half, and the
ordering of every check ahead of pricing, is `negotiation-driven-capacity-resize`'s
`evaluate_round` composition, which already orders admissibility, authoritative
feasibility, commercial feasibility, and pricing. The "Seller feasibility precedes
pricing" requirement moved with it. Nothing in this change waits on a requested shape
existing.

## Risks / Trade-offs

- **[Linear pricing is wrong for real hardware]** → Accepted as a starting point.
  Mitigated by the aggregator seam and the prohibition on reconstructing totals
  outside it.
- **[An unrated family is given away by mistake]** → A family without a rate is
  bundled by design; the derivation report lists every bundled family per asset, and
  a listing that would be free in an asset is refused.
- **[Composed totals expose the mechanisms' context-limited scaling]** → The shared
  exact conversion helper replaces it in both mechanism kits.
- **[Two aggregator implementations disagree on the same shape]** → Only one ships,
  and the domain selects it.
- **[Mode confusion for operators]** → A shape-priced clause that also states a rate is
  refused with a reason, never silently resolved to one mode.
- **[A malformed rate silently changes a price]** → Refused at write on the
  provisioning service, and held and reported on the storefront.
- **[The reference amount changes for live hosted listings]** → Intended: they
  negotiate from their advertised rate instead of the floor. In-flight negotiations
  pin their proposal, so a negotiation in progress at deployment continues from the
  selected option's rate.

## Migration Plan

1. Exact conversion helper, mechanism scalers, reference amounts, and floor parsing.
2. `kit/capability-pricing` with the aggregator interface and its linear
   implementation; the VM pricing projection.
3. The widened `reference_amount` hook and selected-option reference amounts.
4. Family-rate resolution through the three tiers, the provisioning-side structure
   check, the storefront hold and report, override terms, and the dead
   `min_price`/`token` retirement.
5. Shape-priced clause composition at publication, and the rate structure on the
   storefront's listing record.

Steps 1, 2, 4, and 5 change no published option for a configuration that states no
family rates and whose rates convert exactly. Step 3 changes what hosted selections
negotiate from, as intended. Rollback at any point is a code revert; a storefront that
had published shape-priced listings then reads their rateless clauses as it does today:
an Alkahest clause becomes a hidden reserve priced by the floor, and a hosted clause,
which requires a rate, is refused. An operator reverting restores clause rates first.

## Open Questions

None. Whether a buyer reads the rate structure at discovery time or from a signed
round, whether the multiplier is bounded below at 1.0, and whether the quoted price
travels on the wire are `negotiation-driven-capacity-resize`'s.

## Review dispositions

Design review of 2026-10-01, after the Sections 1–3 implementation:

| Finding | Disposition |
|---|---|
| The recorded structure omitted families the advertised shape does not name | Accepted: every resolved family is recorded |
| Option identity was said to exclude rates that change the composed rate | Accepted: corrected; the composed rate participates as any rate does |
| The seller reference ignores scalar settlement options | Accepted and fixed here, by widening the kit hook |
| The compatibility promise covered inputs accepted only through precision loss | Accepted: narrowed to exact inputs |
| Keyed families were inferred from schema attributes | Accepted: explicit pricing projection |
| Pricing in `kit/capability-shape` broadens a vocabulary kit | Accepted: new `kit/capability-pricing` |
| Section 5 blurs the completion boundary | Accepted: split between the envelope and resize |
| `add-database-migration-commands` should precede the migration | Not accepted: the entry is already in the versioned chain that change runs |
| Stale "tolerant decoding" rationale | Accepted: removed |

In the same discussion, a family without a rate was changed from "unpriceable" to
"not charged", with a free listing refused instead; and unreadable rates were changed
from "treated as absent" to "hold the pool", following the landed asking-rate rule.

Implementation review of 2026-10-01:

| Finding | Disposition |
|---|---|
| API credits priced an escrow proposal against the first accepted escrow, and refused a rateless selected option instead of using the floor | Accepted and fixed: both domains read the selected artifact through `selected_settlement_artifact` |
| The VM hosted-selection reference was proven only by unit tests | Accepted: integration case through `StorefrontClient.evaluate_negotiate` |
| Pricing rate-list validation was not proven at the provisioning API | Accepted: typed-client integration cases |
| Locks downstream of `arkhai-vms` looked stale | Resolved by the maintainer's `make lock`; the packaging note now records it |
| Database-backed reconciler and rate-structure tests sat under `unit/` | Accepted: moved to integration, with shared helpers |
| The VM reference reads rates through `market_alkahest.schemas` rather than core's mechanism-neutral copy | Not adopted: `test_architecture_imports.py` forbids domain concept modules from importing core packages, and the Alkahest kit's reader treats every option's `rates` alike. A neutral reader in a kit concept modules may use is possible later work |
| Closeout prose named two spec deltas where there are three | Accepted: corrected |

