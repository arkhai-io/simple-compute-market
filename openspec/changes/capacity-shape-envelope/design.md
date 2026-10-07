# Design

## Context

Verified against the tree on 2026-10-07.

- **Nothing bounds a requested shape.** `has_matching_inventory_guard`
  (`domains/vms/negotiation/src/arkhai_vms_negotiation/policies.py`) checks a listing
  against its own source: every published source-derived field still matches, the
  published quantity fits what the source declares, and, for a capacity-backed
  listing, the quantity is free at its site. It says nothing about a shape a buyer
  proposes. Site admission bounds only physical capacity, offering mode, and the host
  requirement.
- **A VM listing's shape is stated or generated.** It comes from the storefront's
  site-scoped pool override when that states shapes, else the pool's `listing_shapes`
  hint for the mode, else the VM default generator
  (`arkhai_vms.shape_generation.gpu_count_shapes`, which takes members only). A stated
  list replaces the lower sources whole. A shape is a family-grouped mapping of
  scalars; `kit/resource-pools` validates the hint at every pool write with the shape
  kit's `shape_structure_problems`, and the VM storefront reads it with
  `vm_shape_problems`. An unreadable hint holds the pool's listings.
- **Overrides are stored by `kit/pool-overrides`** as JSON columns, `listing_shapes`
  among them; a market's contribution judges vocabulary before the live projection is
  fetched and judges feasibility, informationally, after it.
- **Pool policy travels as `policy_tags`** and reaches the storefront verbatim through
  the resource-pool projection; unknown tags are opaque metadata.
- **The precedent for a commercial evaluation over shapes is `kit/capability-pricing`**:
  a foundation kit depending only on `kit/capability-shape`, an interface plus one
  implementation, selected by the domain at composition.
- **`kit/site` reading pool state is a recorded exception.** `ARCHITECTURE.md`'s kit
  layers say no new site read of pool state may be added while it stands.
- **Omission already states no commitment** (`ARCHITECTURE.md`, "Omission states no
  commitment"): a dimension a VM shape omits is outside the listing's commitment.
- **Negotiation cannot yet carry a shape.** `negotiation-driven-capacity-resize` §2 adds
  it and fixes the seller's order: admissibility, authoritative feasibility
  (`negotiation-capacity-feasibility-probe`), commercial feasibility, pricing.
- **The compute schema has one quantity per family** (`gpu.count`, `cpu.count`,
  `memory.gib`, `storage.gib`) and marks `gpu.count` and `gpu.model` required.

## Goals / Non-Goals

**Goals:** one domain-neutral admissibility concept a seller's storefront evaluates per
listing; an interface that survives a move from a static range to coupled declared
constraints and supports dimension counter-proposals; constraints declared on the
listing shape they govern, filled by the storefront's configured default; publication
that never advertises an offer the seller's own policy excludes.

**Non-Goals:** occupancy-dependent bounds (availability, owned by
`negotiation-capacity-feasibility-probe` and site admission); ratios and any constraint
beyond `min` and `max`; a requirement that a dimension be stated; bare metal; pricing;
categorical constraints; site-enforced limits; disclosing constraints to buyers
(`publish-shape-bounds`); negotiation wiring (`negotiation-driven-capacity-resize`);
selecting individual listings from an override.

## Decisions

### D1. Admissibility is the storefront's own policy

Admissibility answers which capacity shapes a storefront will sell for a listing. It is
final because the storefront controls agreement: no other party can make it agree to a
shape. It is evaluated by the storefront, at publication and in negotiation. Site
admission is unchanged.

The authority test is `ARCHITECTURE.md`'s "Deciding which party is authoritative". The
site never sees price, so any price it publishes is a hint; it sees every claim
dimension, so it prevails on physical capacity, offering mode, and the host
requirement. A constraint a site states on a pool's listing shape is therefore an
input to the storefront's policy, advisory to the site exactly as pool pricing is.
Admissibility never overrides a constraint the site enforces, and admitting a shape
says nothing about whether the site will serve it.

Rejected: a site-enforced admission constraint (a new site read of pool state, seller
commercial policy inside the admission authority, and still a storefront pre-check);
both (two evaluators of one declaration); not building it (a seller could not exclude
a shape it has capacity for). A limit the site must enforce whichever storefront asks is
a site-admission constraint over claim dimensions and is outside this change.

### D2. A new foundation kit owns admissibility

`kit/capability-admissibility` (`market_capability_admissibility`) depends only on
`kit/capability-shape` and the standard library. It owns everything that reads a
constraint: splitting a listing shape into its base shape and its constraints, parsing a
constraint-only declaration, resolving tiers with each constraint form's merge rule,
and evaluation over `family.field` paths. The domain supplies its `CapabilitySchema`;
the kit knows no family or field name. `kit/resource-pools` calls the kit's structural
split at pool write, as it called the shape kit's structural check before. A coupled
form arrives as a new key inside the kit, with its own parsing, merge, and evaluation,
so no caller changes.

Rejected: `kit/site` (not site authority, and the read is forbidden);
`kit/resource-pools` (storefront commercial policy in an authority-layer kit, which
buyers would install to evaluate it); `kit/capability-shape` (capacity vocabulary, kept
free of commercial evaluation as pricing was); extending `kit/capability-pricing` (the
two change for independent reasons, share no code, and are reused apart); domain only (a
second domain would copy it).

### D3. Whole shape in, problems out, never readable bounds

Callers hold a `Declaration` and a `ResolvedPolicy` as opaque values; only the kit reads
their contents.

**Declaration handling.** Each takes a `tier` label that every problem it returns, and
every problem resolution later returns about it, carries:

- **`split_listing_shape(raw, *, tier, schema=None)`** returns the base shape — every
  field's committed value, with constrained fields reduced to their `offer` and
  constraint-only fields omitted — and either the shape's `Declaration` or its
  constraint problems. A base shape that is not structurally a shape is returned as
  the shape kit's problems, with no declaration. Without a schema it checks structure
  only, which is what the domain-neutral pool-write surfaces can know; with the
  domain's schema it also checks that every constrained path is a quantity the schema
  defines.
- **`parse_declaration(raw, *, tier, schema=None)`** parses a constraint-only document,
  the form the configured default takes: the same field syntax with no `offer`.
- **`resolve(declarations, schema)`**, given declarations highest tier first, returns a
  `ResolvedPolicy` or every problem found. Each constraint form owns its merge rule
  (D9). An empty range is a problem naming each tier's conflicting value. Which tiers
  apply, and in what order, is the caller's choice; what merging them means is the
  kit's. The policy keeps the schema it was resolved with.

**Evaluation on a `ResolvedPolicy`**, both taking shapes and neither exposing
unconditional bounds:

- **`admissibility_problems(shape)`** returns a tuple of problems, empty when
  admissible. A problem carries `paths` (a tuple, so a constraint relating several
  dimensions names all of them), a `code`, a `message`, and its tier. A shape that is
  malformed under the schema — bad structure, an undefined path, a value of the wrong
  kind — is reported as problems; the schema's required fields are not checked here.
- **`admissible_values(dimension, partial_shape)`** returns the values `v` for which the
  partial shape with the dimension set to `v` can still be completed to an admissible
  shape. Dimensions the partial shape does not state are free; a value it states for the
  dimension itself is ignored; `{}` is a valid partial shape stating nothing. A
  dimension that is not a quantity the schema defines, or a partial shape malformed
  under the schema, raises a typed request error carrying every problem, following the
  shape kit's convention for an operation that cannot return problems. An empty answer
  therefore always means a well-formed partial shape with no completion.

`admissible_values` carries a guarantee a counter-proposal policy relies on: fixing
dimensions one at a time, in any order, each to a value from the current answer, never
leaves a later answer empty and always ends at an admissible shape. A policy can build a
counter-shape in whatever priority it chooses without search and without assuming the
region is a box.

What protects callers from a later rewrite is that the whole shape goes in and no bounds
come out. A problem naming one path, or a range for one dimension ignoring the rest,
would encode the box in the return type.

Rejected: a readable `(min, max)` per dimension (every caller comparing locally encodes
the box); a range for one dimension given every other fixed (meaningless when the
remainder is inadmissible); problems carrying a per-dimension range; a
nearest-admissible-shape operation (which dimension to give up is negotiation policy); a
boolean predicate (publication and negotiation need the reason); merging, splitting, or
path checks outside the kit (each is a reader of constraints); unlabelled declarations
(the reports must name tiers, and callers may not read declarations to recover them).

Both evaluation operations ship with the static implementation. `admissible_values` has
a production caller in the VM default generator (D10) and is the primitive a dimension
counter-proposal change will use.

### D4. Admissible values are an opaque set

`admissible_values` returns an `AdmissibleValues` answering questions rather than
exposing its representation: `is_empty`, `contains(v)`, `at_most(v)` (the greatest
admissible value not above `v`), `at_least(v)`, `minimum`, and `maximum`. `maximum` is
`None` when unbounded; every accessor returns `None` on an empty set, so a caller checks
`is_empty` first. The static implementation backs it with an interval. An answer is
valid only for the partial shape it was computed from; a caller that caches an
unconditional answer as "the bounds" reads bounds directly.

Rejected: an interval type (cannot represent steps or gaps a later constraint produces);
an interval with a step (invites step arithmetic in callers); raising on an empty set's
accessors (forces exception handling on a normal answer).

### D5. Constraints are declared inline on the listing shape they govern

A stated listing shape — in a pool's `listing_shapes` hint or a storefront override's
`listing_shapes` — may give any quantity field a constraint mapping in place of its
scalar:

```yaml
listing_shapes:
  vm:
    - gpu:    { model: H100, count: { offer: 1, min: 1, max: 4 } }
      cpu:    { count: 16 }
      memory: { gib: { max: 512 } }
    - gpu:    { model: H100, count: { offer: 8, min: 4 } }
      cpu:    { count: 128 }
      memory: { gib: 1024 }
```

- **`offer`** is the value the listing sells; the listing's base shape carries it.
  **`min`** and **`max`** bound what an agreed shape may state for the field. Each is a
  positive integer, `min` is not above `max`, an `offer` lies within its own range, and
  a mapping states at least one key. A plain scalar is shorthand for `{offer: v}`.
- **A field with constraints and no `offer`** makes no commitment on that dimension and
  bounds what an agreed shape may state for it.
- **An `offer` alone says nothing about negotiability.** A fixed value is written with
  `min` and `max` equal to the offer.
- **Constraints apply to quantities only.** Given the schema, a constraint mapping on an
  attribute or an undefined field is a problem.
- **Strict keys.** A key other than `offer`, `min`, or `max` is a problem, so a later
  form — ratios, as a list on the numerator field, compared by integer
  cross-multiplication — reaching an older kit fails closed rather than being ignored.
- **The admissible region is the intersection of every constraint;** no constraint
  widens another.

The constraints sit on the dimension they govern, so no dimension path is restated, and
each listing carries the range around its own offer — the form a buyer will be shown.

Rejected:

- **A pool-level `shape_bounds` tag, keyed by mode, with named sections.** Restates every
  constrained path apart from the shapes, and an older storefront ignores an unknown tag
  and sells outside it.
- **A pool-level constraint block beside the shapes inside `listing_shapes`.** Still
  restates each path, and gives a pool-wide range to listings that differ.
- **Pool-level constraints stated on one shape's field.** A value on one shape would
  silently govern the others.
- **`value` for the committed number.** `offer` says what the listing sells.
- **Always the mapping form.** Rewrites every existing shape and makes attributes look
  constrainable.
- **Omitting the field name for a family with one quantity** (`gpu: {model: H100, offer:
  1}`). A change to the shape vocabulary itself, with no rule for a family that later
  gains a second quantity; recorded below.
- **A `step` key, ratios, or a requirement that a field be stated, now.** None is needed
  yet; strict keys let each be added safely.

### D6. A dimension a shape omits is free

A shape is admissible when the dimensions it states, with the ones it leaves free, can be
completed to an admissible shape — the meaning `admissible_values` has, so the two
operations never disagree. For `min` and `max`, an omitted field never violates.

This applies `ARCHITECTURE.md`'s "Omission states no commitment": a shape that omits a
dimension commits nothing on it, and the site supplies it. Constraints therefore govern
the dimensions an agreed shape states, not what is provisioned. A memory maximum does
not cap the memory a GPU-only deal receives; a ceiling on what is provisioned per deal
is a site-admission constraint and outside this change.

Whether a revised shape may add a dimension the listing omits, or drop one it states, is
negotiation policy, decided by `negotiation-driven-capacity-resize`.

Rejected: a `min` requiring the dimension to be stated (mixes a range with a
requirement); judging an omitted dimension at the pool default (site-decided and
provider-specific). A requirement that a dimension be stated cannot be a constraint
under completion semantics and would need its own check (Open Questions).

### D7. An absent constraint commits nothing

A listing, field, or side of a range with no constraint states no commitment on it.
Where no tier constrains a field, admissibility does not constrain it, and site
admission remains the backstop. This is what absence means, as an unrated family is in
pricing, not a permissive default awaiting a fail-closed alternative.

### D8. A listing whose policy cannot be computed closes

A listing's policy is the merge of its tiers (D9). When the storefront cannot compute
it, it fails closed for that listing alone:

- **Its constraints cannot be read** — a constraint on an attribute or an undefined
  field, or a key newer than the storefront's kit — in the pool hint or a stored
  override.
- **Its merged range is empty** — for example, the listing states `max: 4` and the
  configured default `min: 8`.

That listing is not published and an open listing for it closes; the pool's other
listings are unaffected. The report names the tier, the path, and the problem, or each
tier's conflicting value. A malformed configured default prevents the storefront from
starting, the same rule applied to its own input. A pool whose base shapes cannot be
read keeps the existing rule: no new listing, existing listings held.

Storefront policy that cannot be reconciled with what the site declared closes the
listing rather than holding it, so it is never silently ignored. The site cannot be
refused a projection; closing is the signal that reaches the site's administrator, who
then reconciles with the storefront's administrator. A hold remains right where nothing
the storefront stated is at stake: an override that states shapes replaces the hint, so
an unreadable hint concerns only the site. Pricing holds where this closes because a
last-published price is still an offer the storefront made; here the storefront cannot
say what it would sell.

Rejected: holding listings and refusing revised shapes (ignores the storefront's policy
while the listing stays open); closing every listing of the pool (punishes listings
whose policy is computable); ignoring the unusable constraint (sells beyond a stated
policy).

### D9. A listing's constraints merge per field with the configured default

A listing's policy resolves from two tiers, highest first: the listing's own
constraints, from whichever source stated its shape, and the storefront's configured
default for the mode. They merge per leaf (`family.field.min`, `family.field.max`): for
each leaf the higher tier stating it wins, and a tier that does not state a leaf leaves
the lower tier's value in place. The configured default states no `offer`.

```text
listing:   gpu.count {offer: 1, max: 4}
default:   gpu.count {min: 1, max: 16}     memory.gib {max: 512}
resolved:  gpu.count {offer: 1, min: 1, max: 4}     memory.gib {max: 512}
```

The configured default adds values where the site omits them. A listing may replace a
default's value, including with a wider one, but not remove it.

An override that states shapes replaces the hint's list whole, each of its shapes
carrying its own constraints, as stated shapes do today. It does not merge with the
hint's constraints: without a way to name the listing it adjusts, an override's shape is
a listing of its own. A generated shape has no constraints of its own, so its policy is
the configured default alone.

Rejected: an override block merged per field onto every listing of a pool (the
pool-level form rejected in D5, and superseded once an override can select listings);
no storefront tiers (undoes D1); whole-declaration replacement between a listing and the
default (drops the default's values the listing does not restate); intersection
(narrowing only, contradicting the advisory hint).

### D10. Publication never advertises an inadmissible offer

- **A stated listing shape** whose base shape is inadmissible under its resolved policy
  — its offer outside its range — is not published, an open listing for it closes, and
  it is reported with its tier and problems.
- **The VM default generator receives the default-only policy** and, for each GPU model,
  generates the counts from one to the largest declared that
  `admissible_values("gpu.count", {"gpu": {"model": m}})` contains, rather than
  generating and filtering. With no configured default it generates what it does
  today. Generated shapes are nobody's statement, so none is reported.
- **An override write is refused** when one of its shapes' constraints cannot be read
  with the domain's schema, resolves to an empty range against the configured default,
  or leaves its offer inadmissible. The check needs no site call: an override's shapes
  never merge with the live hint. It is the VM contribution's vocabulary check.
- **A pool write is refused** when a stated shape's constraints are structurally
  invalid; whether a constrained path is a quantity is the domain's to judge.
- **A listing's identity is its base shape.** The derivation digest is taken over the
  base shape, so changing a range does not change which listing it is; reconciliation
  re-evaluates the listing and closes it if its offer becomes inadmissible.
- **Asking rates match the base shape**, as they match a shape today.
- **Reports.** The per-site derivation report gains inadmissible listing shapes (tier,
  shape, problems) and unusable constraints (tier, path, problem, or each tier's
  conflicting value), served by system status beside `unreadable_asking_rates` and
  logged once per change.
- **Every shape the storefront agrees to is admissible** under the policy in force when
  it agrees; enforcing that in negotiation is `negotiation-driven-capacity-resize`'s
  composition.

### D11. Permanent destinations are confirmed in planning and review

`site-capacity` is not a destination: nothing about the site changes. The proposal's
`Knowledge to promote` names a provisional destination for each decision; planning and
review confirm or move them. Fixed: every negotiation rule belongs to
`negotiation-driven-capacity-resize`, because nothing here enforces them;
`docs/development/ARCHITECTURE.md` gains the foundation kit, the close-rather-than-hold
principle with an example, and, in "Omission states no commitment", that an offer
without a range commits nothing about negotiability.

### D12. VM only

The VM storefront composes admissibility: stated and generated shapes, the configured
default, publication, the override write check, reports, and — through
`negotiation-driven-capacity-resize` — negotiation.

Bare metal is out of scope. A bare-metal listing sells one whole machine whose shape is
its declaration and negotiates no shape, so a range around its offer constrains nothing
a buyer can ask for; the only effect would be filtering which machines are listed, which
is a listing policy, not admissibility. API credits is not a listing-shape domain.

The kit's neutrality is proven at the lowest level: an import-boundary test, and unit
tests against a synthetic schema with no compute vocabulary.

### D13. Buyer disclosure is a separate change

Disclosure is owned by `publish-shape-bounds`, so this change closes out without a
registry prerequisite. Its open representation question is answered here: a listing
discloses its own shape in D5's inline form, resolved against the configured default,
and a buyer evaluates it through this kit. It adds the operation that renders a
resolved policy back into that form; disclosure is not readable bounds, because buyers
still do not compare numbers themselves. VM listings only; registry filtering is
decided with the carrier.

## Inputs to other changes

To `negotiation-driven-capacity-resize`, for its own design:

- Every shape the storefront agrees to is admissible under the listing's policy in force
  when it agrees, whether the listing's own shape or a revised one; the policy is
  re-derived from the listing's source shape and the configured default.
- By default, a revised shape that states a dimension the listing's shape neither states
  nor constrains is refused: under shape pricing an unrated family contributes nothing,
  so accepting it would give the dimension away. Whether a revision may drop a stated
  dimension is likewise its policy. How omitted dimensions are negotiated is a
  replaceable policy a storefront selects at composition.
- A revised shape for a listing whose policy cannot be computed (D8) is refused for
  admissibility, distinctly from a shape outside the constraints, in case the round
  runs before reconciliation closes the listing.
- An admissibility refusal carries the kit's problems (`paths`, `code`) and may carry
  `admissible_values` for each refused path given the rest, so a buyer can counter.

To `publish-shape-bounds`: D13's representation and the render operation.

## Risks / Trade-offs

- **A caller reads constraints directly** → undoes D3. Closeout verifies that nothing
  outside the kit walks a constraint mapping, a `Declaration`, or a `ResolvedPolicy`,
  that every `listing_shapes` reader splits through the kit before using a shape, and
  that no unconditional `admissible_values` answer is cached as bounds.
- **Closing on an unusable constraint churns a listing** → accepted: it republishes as a
  successor once usable, and closing is how the site's administrator learns of it.
- **Changing the `listing_shapes` wire format** → an older storefront or provisioning
  service meets a mapping where it expects a scalar and treats the hint or write as
  unreadable; nothing ignores the constraints. Accepted under lockstep upgrade.
- **An override cannot tighten one hint listing's range without restating the pool's
  shapes** → accepted until an override can select the listings it applies to.
- **`admissible_values` is wider than its first caller needs** → accepted to support
  dimension counter-proposals without changing the interface later.

## Migration Plan

Additive for existing data: every shape stated today is valid shorthand, no listing
carries constraints until one is written, and with no configured default nothing is
constrained and publication is unchanged. The VM generator's output is unchanged where
no default applies. Sites and storefronts are operated by the same entities and upgraded
together; a constraint written before a storefront is upgraded makes its hint
unreadable to that storefront, which holds the pool. Rollback is a code revert after
removing constraint mappings from pool hints and stored overrides; a constraint left in
place makes the reverted storefront hold the pool, and the reverted provisioning service
refuse writes that keep it.

## Open Questions

- **Upgrade ordering when site and storefront operators differ.** A newer constraint key
  closes listings on storefronts whose kit predates it. Revisit when sites and
  storefronts are no longer operated and upgraded together, with operator guidance on
  upgrading storefronts before writing new keys.
- **A requirement that a dimension be stated.** It cannot be a constraint under D6's
  completion semantics; it would need its own check alongside `admissibility_problems`.
  Revisit when a seller needs one.
- **Constraints keyed by attribute value.** For a pool whose members carry different GPU
  models with different per-VM limits; stated shapes already name their model, so
  revisit only if a generated or pool-wide form needs it.
- **Site-enforced shape limits.** For a delivery limit within physical capacity that a
  storefront ignoring the hint would turn into a failed fulfillment.

## Findings outside this change

Each is checked at closeout against `openspec/changes/` for a change that owns it.

- `kit/resource-pools` duplicates the pricing rate-list structural check
  (`validate_pricing_rates`) rather than calling one owned by `kit/capability-pricing`.
- `docs/development/ROADMAP.md` Goal 2 says the seller's own feasibility check compares
  region and GPU model by equality and no quantitative dimension; the inventory guard
  also checks the published quantity against its source. Corrected at this change's
  roadmap currency step.
- **Storefront term tiers are resolved separately per term** (family rates, listing
  shapes, asking rates, and now constraints), yet follow one rule: mappings combine key
  by key, and a leaf the highest tier stating it replaces, never removed by omission. A
  shared precedence merge with per-leaf provenance, probably a small standard-library
  foundation module, belongs to a change of its own.
- A pool default outside a listing's constraints (an omitted dimension supplied above
  its maximum) is a site configuration fact under D1 and D6; publication could report
  it as a warning.
- A host's `gpu_count` duplicates the `gpu_count` of its capacity declaration.
- The pool's `pricing` hint could be stated inline on listing shapes, as constraints
  are.
- An override should select the listings it applies to with a query over the pool's
  listings — offering mode, attributes such as GPU model, or the listing shape —
  rather than by site, pool, and mode alone, or by an invented listing identifier. It
  would let an override adjust one listing's constraints per field.
- A family with one quantity could omit its field name in a shape.
- A site-visible report of why a storefront closed a pool's listings; the storefront can
  already call the site.
- The compute schema requires `gpu.count` and `gpu.model`, so a VM or bare-metal listing
  without GPUs cannot be stated.
- This change's `tasks.md` predates these decisions and is replanned after design
  review.
