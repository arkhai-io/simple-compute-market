# Design

## Context

Re-verified against the tree on 2026-10-01. The original planning-time context
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
- **The seller's reference amount** is
  `primary_rate_value(accepted_escrows[0])` scaled by the requested duration in
  `_seller_reference_amount`.
- **`RateValue` and `PER_UNIT_SECONDS` exist twice**, in `market_core.schemas`
  and `market_alkahest.schemas`.
- **`kit/capability-shape`** defines the family-grouped shape and its
  schema-driven flattening; it imports only the standard library. The compute
  family's schema is `COMPUTE_CAPABILITY_SCHEMA` in `domains/compute`
  (`arkhai_compute`), shared by the VM and bare-metal domains, with families
  `gpu` (`count`, required `model`), `cpu.count`, `memory.gib`, and
  `storage.gib`. Shapes are digested over their families.
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

**Goals:** a seller can state a price for each capacity family and have any
admissible shape priced from it; every listing priced today keeps exactly its
current price and option identities; every amount on the pricing path is exact;
the aggregator is replaceable without touching negotiation; the dead `min_price`
and `token` resolution is removed.

**Non-Goals:** protocol changes and the multiplier reinterpretation
(`negotiation-driven-capacity-resize`); admissibility
(`capacity-shape-envelope`); authoritative feasibility
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
nesting the pricing hint already uses for `gpu`. A family whose schema carries an
attribute is keyed by that attribute's value — in the compute schema only `gpu`,
keyed by `model` — and other families are not keyed. One nesting serves all three
tiers:

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

A family rate is asset-denominated and mechanism-neutral: it states what one unit
of the family costs per hour in one asset, and prices every clause paying in that
asset. A rate is positive decimal text in the asset's display units, the same form
a clause rate takes; an explicit zero is refused, so no family is ever priced at
zero by construction. Revisit trigger for the zero rule: a seller who needs to
commit a dimension at no charge. `per` must be a time unit, and every family rate
applied to one clause must name the same unit.

A rate is never a `ShapeField`: shapes are digested over their families, and a
rate must not change a listing's shape digest or identity.

### A listing is either flat-priced or shape-priced, decided by its GPU family

Every compute shape names the `gpu` family, so the GPU family decides the mode:

- **Shape-priced** — the listing's GPU model resolves a non-empty `rates` list.
  Its clauses state mechanism, asset, and mechanism input only. For each clause
  whose mechanism negotiates a scalar amount, the storefront evaluates the
  listing's own shape against the family rates in that clause's asset, through
  the aggregator, and supplies the result as the clause's `rate` and `per` before
  the mechanism compiles it. A clause whose mechanism declines the scalar
  (`contact-exchange.v1`, per `negotiation-protocol`'s "Scalar negotiation
  participation is a mechanism declaration") is passed through rateless in either
  mode: it carries no price to compose, and its mechanism refuses a rate.
- **Flat-priced** — no GPU rates resolve. A clause's own `rate` is the listing's
  rate whatever its shape, and a rateless Alkahest clause is a hidden reserve
  priced by the `default_min_price` floor, both exactly as today.

The published wire does not change in either mode: each settlement option still
carries one `amount` rate for the whole listing. Only where its value comes from
differs.

A candidate is refused, with a reason naming the family and asset, when:

- a shape-priced listing's clause also states its own `rate` (two sources for one
  price);
- a family the listing's shape names has no rate in the asset of a shape-priced
  clause whose mechanism negotiates a scalar (unpriceable, never free and never a
  hidden reserve — which also catches a mistyped asset);
- any non-GPU family resolves rates while the GPU family resolves none (a
  partially stated shape-priced intent).

Refusing the candidate, rather than dropping only the affected option, is
deliberate: a silently missing settlement option is a price change nobody stated.
It matches how the common clause contract already treats a malformed rate.

A family the listing's shape does not name is not priced, even if a rate resolves
for it: a dimension the shape omits is outside the listing's commitment (see
`openspec/specs/storefront-publication/spec.md`, "Every VM listing is a listing
shape"), so a buyer is not charged for it.

Worked example, one 18-decimal token, the rates above:
`{gpu: {count: 2, model: H100}, cpu: {count: 16}, memory: {gib: 128}}` prices at
`2×80 + 16×0.5 + 128×0.05 = 174.4` per hour, which the Alkahest mechanism scales
to `174400000000000000000` base units per hour. The GPU-only default listings of
an 8-card H100 pool price at 80, 160, … 640.

### Compatibility: the flat rate is never reinterpreted

This replaces the planning-time decision, which read an existing single-rate
listing as "a structure whose only priced dimension is the primary one" and
claimed that reproduced today's prices exactly. It does not: today's clause rate
is per listing, not per GPU, so reading it as a per-card rate multiplies the price
of every listing whose GPU count exceeds one — every default listing above the
first count.

| | Planning-time decision (superseded) | Accepted |
|---|---|---|
| Meaning of an existing clause `rate` | A GPU-only per-dimension rate | A flat listing rate, never reinterpreted |
| Existing listing prices after deploy | Change ×N for GPU count N > 1 | Identical |
| Option identities and republication | Every multi-GPU option's `option_id` changes; every such listing refreshes | Unchanged; nothing republishes |
| How per-family pricing starts | Implicitly, for everyone | Opt-in, by stating GPU `rates` |
| A family with no rate | Unpriceable | Unpriceable, per family and asset |

Under the accepted reading every configuration valid today publishes
byte-identical settlement options.

**Neither mode is a published asking rate.** `publish-indicative-listing-rates`
adds a listing-wide catalogue price on the published listing resource, from which
nothing is constructed. The two are distinct quantities. The family rates this
change introduces let a seller price a shape a buyer proposes; the asking rate
prices the one shape a listing advertises and is what a buyer compares on before
contacting anyone. A storefront **may** derive an asking rate by evaluating a
seller's family rates at the listing's advertised shape, where the seller's
declared policy says so. It is not required to, and neither quantity is read as
the other.

### Family rates resolve through the existing tiers, one whole list per family

Rates resolve through the precedence `pools-8` established — site-scoped
storefront pool override, pool hint, configured default — independently per
family, and per model within `gpu`. Within one family, a tier's `rates` list
replaces lower tiers' lists as a whole, the way a tier's `settlements` list does:
merging per asset across tiers would let one family's price for one asset come
from an override and for another asset from a default, a combination no one wrote.

A malformed family-rate hint is treated as absent, as every other malformed hint
field is, and is reported in system status. An override stating a rate for a
family the schema does not know, or a malformed rate, is refused at write.

### Price aggregation is a replaceable interface in `kit/capability-shape`

Real capacity is not linearly priced — the last GPU on a host is worth more than
the first, and the reservable capacity per dimension being a function of current
occupancy applies to price as much as to availability. Linear summation ships as
the only implementation; what makes that safe is that evaluation is reached
through an injectable aggregator, so a non-linear or coupled aggregator is a new
implementation behind an unchanged interface.

The interface takes a shape, the family rates for one asset, and the schema, and
returns either an exact price per time unit in the asset's display units or an
unpriceable result naming every family that has no rate. It does not assume the
price is a sum, and nothing downstream may assume it either: no caller may
reconstruct a total by multiplying one family's rate by its quantity.

The interface and the linear implementation live in `kit/capability-shape`
(`market_capability_shape`), beside the schema-driven traversal they need. That
module is a standard-library-only foundation kit, so buyers, storefronts, and the
bare-metal domain can all evaluate a shape. A separate `kit/capability-pricing`
distribution was considered and rejected: it would add a distribution, lock, and
wheel for one module whose only dependency is the shape kit itself. The domain's
composition selects the aggregator; operator configuration does not, so a
deployment has exactly one.

Evaluation is callable outside the negotiation path, so
`billable-capacity-reservations` can price a hold's burn rate and
`negotiation-driven-capacity-resize` a proposed shape without a refactor.

### `RateValue.per` stays a time unit; the quantity comes from the shape

A family rate is per unit per hour. Two ways to express that were considered:

1. Add a quantity dimension to `RateValue` alongside `per`.
2. Keep `RateValue` as-is and pair each family's rate with that family's own
   quantity from the shape at evaluation.

Option 2 is accepted. `RateValue` is on the wire, in option identity, and in
escrow obligation data, so widening it has the largest blast radius of anything
here; and the quantity is already present in the shape being priced — carrying it
in the rate too would let the two disagree. Under the flat-or-shape decision above
the published `RateValue` does not change at all: it still carries the whole
listing's rate. Recorded explicitly because option 1 looks simpler to anyone who
has not traced `RateValue`'s reach into settlement.

### Every amount is exact, and nothing rounds silently

The pricing path touches on-chain amounts, whose base units routinely exceed 64
bits. These rules apply to every value this change computes or feeds:

- **No binary floats, no context-limited arithmetic.** A decimal rate is parsed
  exactly into an integer coefficient and a scale from its digits
  (`Decimal.as_tuple()`), never through `float` and never through `Decimal`
  arithmetic under a precision context. Products and sums are Python `int`. The
  aggregator's result is rendered back as exponent-free decimal text.
- **The aggregator's result is exact.** A sum of products of finite decimals is a
  finite decimal, so no rounding happens inside evaluation. Converting it to base
  units is the consumer's step, with the consumer's stated rule: publication
  refuses a total that is not a whole number of base units (the mechanism's
  existing "more than N decimal places" refusal), and later consumers that quote
  (`negotiation-driven-capacity-resize`, `billable-capacity-reservations`) round
  up.
- **One exact conversion helper.** `kit/settlement-runtime` gains one helper,
  beside clause validation, that converts decimal rate text and an asset exponent
  to integer base units exactly, refusing a non-whole result and a result above
  `2**256 - 1`. The Alkahest and hosted mechanism scalers use it in place of
  context-limited `Decimal` multiplication. This touches two mechanism kits, but
  this change is what produces the long totals that expose the defect.
- **The reference amount is integer arithmetic.** `_seller_reference_amount`
  becomes `value * seconds // 3600` on Python `int`, matching `compute_rate_total`.
- **The floor is parsed exactly.** `default_min_price` keeps its meaning — a
  negotiation floor in base units per hour, used only for a hidden reserve — but is
  parsed as exact positive decimal text instead of through `float`, and the
  reference amount derived from it truncates to whole base units with integer
  arithmetic, as a rate-derived one does.
- **No amount in a fixed-width column.** Amounts stay decimal text in JSON or in
  `TEXT` columns, never a SQLite `INTEGER`.

### The rate structure is a storefront-served term of sale, not a registry field

The registry discards top-level listing fields outside its fixed column set (see
Context), so a top-level `rate_structure` would be silently lost. Placing it in
`listing_resource` would survive storage but put asset-denominated payment pricing
in the capacity description and add a term every comparison must classify.

Accepted: the registry receives what it receives today — each settlement option
carries its composed rate for the listing's own shape, which is what discovery
compares. The resolved family rates for a shape-priced listing are recorded on the
storefront's listing record as a term of sale — refreshed in place on change,
never part of the listing's identity, its shape digest, or any option's identity —
and returned by the storefront's listing read.

The record is a nullable `rate_structure` text column on the generic storefront
`listings` table, holding the domain's JSON: for a shape-priced VM listing, each
family the listing's shape names mapped to its resolved `rates` list, with the GPU
family already resolved to the listing's model; null for a flat-priced listing.
`storefront-publication`'s "Commercial mapping identity" keeps pricing on the
generic table and forbids a domain mapping carrying commercial fields, and the
column's content is opaque to core as `listing_resource`'s is. The registry
request is built field by field from the stored listing, so the column never
reaches a registry.

That read is unsigned. Whether a buyer may derive a quote from it, or needs the
structure bound into a signed negotiation response, is
`negotiation-driven-capacity-resize`'s decision, its first consumer. So is whether
any buyer needs the structure at discovery time; that would require the registry to
keep listing-level fields it currently discards, which is
`store-registry-listings-as-published`'s concern, and that change's accepted
carrier policy is the input to the decision.

### Scope edges found during planning

- **The local-table derivation path is flat-priced only.** Family rates resolve on
  the projection path, as site-scoped overrides do; the legacy local-table path,
  which `pools-9-retire-local-physical-authority` retires, never resolves them, in
  the same way overrides are inactive there.
- **Helm values do not expose family-rate defaults.** The storefront chart's
  `pricing` schema describes the hosted-fiat flat clause form. Helm deployments
  price shapes through pool hints and site-scoped overrides; adding
  `[pricing.defaults.<family>]` to the chart is a chart change no deployment needs
  yet. The chart keeps accepting `default_token_address` as a retired key.
- **The legacy pricing migration must not mistake family rates for legacy pricing.**
  It reports any `[pricing.defaults.gpu.<model>]` table as per-model legacy pricing
  needing manual clauses. It is narrowed to tables stating the retired `min_price`
  or `token`, so a model table carrying only `rates` or `settlements` is not a
  conflict.
- **Found, not changed here.** The legacy migration reads `default_min_price` as a
  display-unit rate for an Alkahest clause, while the negotiation floor reads the
  same key as base units per hour; this change documents the floor's unit and
  leaves the migration's reading, which only runs on pre-clause configurations.
  The API-credit domain computes its reference amount as
  `int(Decimal(str(unit)) * count)` under the default decimal context, the same
  class of defect fixed here for VM; it is outside this change's domain and is
  recorded as unowned work in the campaign index.

### The negotiated variable is unchanged here

This change states and evaluates rates; it does not change what a round
negotiates. Making the negotiated quantity a multiplier over the advertised
minimum is one deployment boundary with the field that lets a round carry a shape,
so both belong to `negotiation-driven-capacity-resize`. After this change every
existing negotiation prices exactly as before: a shape-priced listing's options
carry its composed rate, and the reference amount reads it as it reads any rate.

### The dead `min_price` and `token` resolution is removed

Per-model resolution of `min_price` and `token`, the candidate fields that carry
them, and the `[pricing.defaults.gpu.<model>].min_price/token` and
`default_token_address` defaults feed nothing, and leaving them makes the
resolver's documented contract false. They are removed.

Compatibility for inputs that still state them:

- **Stored site-scoped overrides.** `VmPoolOverrideTerms` (which forbids unknown
  fields) validates an override only at write. Derivation reads stored terms
  through `vm_override_view`, which takes the keys it names and ignores the rest,
  and holds a pool only when the kit cannot decode the stored JSON at all. A stored
  override still carrying `min_price` or `token` therefore stays readable once the
  keys leave the terms contract; derivation reports the retired keys per pool in
  its derivation report, which system status surfaces. A write stating them is
  refused. *Amended during planning:* the design originally said removal would
  hold such pools; the read path shows it would not, so no tolerant decoder is
  needed, only the report.
- **Configuration.** A configuration still stating the retired keys is accepted;
  they are not read, and startup reports them.
- **Unchanged:** the legacy pricing migration's reading of legacy inputs, which is
  its purpose; the legacy local tables' columns, whose retirement is
  `pools-9-retire-local-physical-authority`'s; and `default_min_price` as the
  hidden-reserve floor.

### The feasibility guard checks a requested shape, ordered before pricing

`has_matching_inventory_guard` answers "is this listing still what it says". The
predicate Section 5 adds answers "will the seller serve this shape", taking a
requested shape and the seller's constraints, and runs inside the VM
`evaluate_round` composition ahead of pricing so a shape the seller will not serve
is never quoted.

Section 5 is not part of the Sections 1–3 implementation. Its quantitative check
overlaps `capacity-shape-envelope`'s admissibility, it touches the negotiation path
rather than pricing and publication, and it has no live caller until
`negotiation-driven-capacity-resize` §2. Whether it moves into its own change
depending on `capacity-shape-envelope` is decided when Section 5 is taken up
(task 5.0).

## Risks / Trade-offs

- **[Linear pricing is wrong for real hardware]** → Accepted as a starting point.
  Mitigated by the aggregator seam and the prohibition on reconstructing totals
  outside it.
- **[A rate resolves partially and prices a shape from an incomplete structure]**
  → A named family with no rate in the clause's asset refuses the candidate.
  Priced-at-zero is impossible: zero rates are refused and absence never means
  zero.
- **[Composed totals expose the mechanisms' context-limited scaling]** → The
  shared exact conversion helper replaces it in both mechanism kits.
- **[Two aggregator implementations disagree on the same shape]** → Only one
  ships, and the domain's composition selects it.
- **[Mode confusion for operators]** → Mixed-mode candidates are refused with a
  reason, never silently resolved to one mode.
- **[Retiring override keys holds pools]** → Tolerant decoding of the two retired
  keys, reported in status.

## Migration Plan

1. Exact conversion helper, mechanism scalers, reference amount, and floor
   parsing. No published value changes for any rate a mechanism accepts today.
2. Aggregator interface and linear implementation in `kit/capability-shape`.
3. Family-rate resolution through the three tiers, override terms, and the dead
   `min_price`/`token` retirement with tolerant decoding.
4. Shape-priced clause composition at publication, and the rate structure on the
   storefront's listing record.

Every step is additive for existing configurations: none of them changes a
published option for a configuration that states no family rates. Rollback at any
point is a code revert. A storefront that had published shape-priced listings
then reads their rateless clauses as it does today on its next cycle: an Alkahest
clause becomes a hidden reserve priced by the floor, and a hosted clause, which
requires a rate, is refused. An operator reverting restores clause rates first.

## Open Questions

None. Whether a buyer reads the rate structure at discovery time or from a signed
round, whether the multiplier is bounded below at 1.0, and whether the quoted
price travels on the wire are `negotiation-driven-capacity-resize`'s. Whether
Section 5 becomes its own change is task 5.0's decision.
