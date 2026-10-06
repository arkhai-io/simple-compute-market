# Design

## Context

Verified against the tree on 2026-10-06.

- **Nothing bounds a requested shape.** `has_matching_inventory_guard`
  (`domains/vms/negotiation/src/arkhai_vms_negotiation/policies.py`) checks a listing
  against its own source: every published source-derived field still matches, the
  published quantity fits what the source declares, and, for a capacity-backed
  listing, the quantity is free at its site. It says nothing about a shape a buyer
  proposes. A pool's `listing_shapes` hint lists what the pool advertises; it does not
  bound what a buyer may ask for. Site admission bounds only physical capacity,
  offering mode, and the host requirement.
- **Pool policy travels as `policy_tags`.** `kit/resource-pools/hints.py` owns the
  domain-neutral keys, typed or raw readers, and write-time structural validators;
  `listing_shapes` (keyed by offering mode) and `pricing` (family-grouped) are the
  closest relatives. Tags reach the storefront verbatim through the resource-pool
  projection's `pool_metadata`. Unknown tags are opaque metadata a consumer ignores.
- **Storefront tiers are resolved per hint, not inherited.** Pricing resolves family
  rates through the site-scoped storefront pool override, the pool hint, and the
  storefront's configured default; listing shapes through override, hint, and the VM
  default generator (`arkhai_vms.shape_generation.gpu_count_shapes`). `policy_tags`
  itself carries no precedence.
- **The precedent for a commercial evaluation over shapes is `kit/capability-pricing`**:
  a foundation kit depending only on `kit/capability-shape`, an interface plus one
  implementation, selected by the domain at composition. Unreadable rates and asking
  rates hold the pool; malformed pricing hints are refused at pool write.
- **`kit/site` reading pool state is a recorded exception.** `ARCHITECTURE.md`'s kit
  layers say no new site read of pool state may be added while it stands.
- **Publication already judges stated shapes** (`market_storefront.services.shape_feasibility`)
  and reports problems per site; the VM override contribution
  (`vm_pool_override_contribution.py`) checks an override's stated shapes at write.
  Bare-metal publication derives one shape per Physical Resource and has its own
  pool-override terms (`arkhai_bare_metal_storefront.pool_overrides`).
- **Negotiation cannot yet carry a shape.** `negotiation-driven-capacity-resize` §2 adds
  it and fixes the seller's order: admissibility, authoritative feasibility
  (`negotiation-capacity-feasibility-probe`), commercial feasibility, pricing.
- **The claim is built from an allow-list.** `compute_capacity_claim_from_order` reads
  only the known identity and dimension keys of a settlement order's `listing_resource`.

## Goals / Non-Goals

**Goals:** one domain-neutral admissibility concept a seller's storefront evaluates; an
interface that survives a move from a static box to coupled declared constraints and
supports dimension counter-proposals; bounds declared through existing pool policy and
the storefront's own tiers; publication that never advertises a shape the seller would
not sell.

**Non-Goals:** occupancy-dependent bounds (that is availability, owned by
`negotiation-capacity-feasibility-probe` and site admission); pricing; categorical
constraints; site-enforced limits; disclosing bounds to buyers
(`publish-shape-bounds`); negotiation wiring (`negotiation-driven-capacity-resize`).

## Decisions

### D1. Admissibility is the storefront's own policy

Admissibility answers which capacity shapes a storefront will sell. It is final because
the storefront controls agreement: no other party can make it agree to a shape. It is
evaluated by the storefront, at publication and in negotiation. Site admission is
unchanged.

The authority test is what each party can see and control, and who prevails when they
disagree. The site never sees price, so any price it publishes is a hint. It does see
every claim dimension, so it prevails on physical capacity, offering mode, and the host
requirement, and the storefront cannot override those. A storefront can always refuse
more than the site would; neither can make the other accept.

A pool-declared bound is therefore a site-supplied default for the storefront's policy,
advisory to the site exactly as pool pricing is. Admissibility never overrides a
constraint the site enforces, and admitting a shape says nothing about whether the site
will serve it.

Rejected:

- **Site-enforced admission constraint.** Adds a new site read of pool state, puts
  seller commercial policy inside the admission authority, and still needs a storefront
  pre-check to avoid site round trips.
- **Both.** Two evaluators of one declaration, inheriting the first option's costs.
- **Not building it.** A seller could not exclude a shape it has capacity for.

A limit the site must enforce whichever storefront asks — a provider that cannot build a
VM over some size — is a site-admission constraint over claim dimensions, not
admissibility, and is outside this change.

### D2. A new foundation kit owns admissibility

`kit/capability-admissibility` (`market_capability_admissibility`) depends only on
`kit/capability-shape` and the standard library. It owns everything that reads a
declaration: parsing and validation, the resolution of tiers with each section's merge
rule, and evaluation over `family.field` paths (D3). `kit/resource-pools` keeps the tag
key and a raw reader whose value it passes unread to the kit's parser at pool write, as
`validate_listing_shapes` calls `shape_structure_problems`. The domain supplies its
`CapabilitySchema` at composition; the kit knows no family or field name. A coupled
form arrives as a new section inside the kit, with its own parsing, merge rule, and
evaluation, so no caller changes.

Rejected:

- **`kit/site`.** Admissibility is not site authority, and the read is forbidden.
- **`kit/resource-pools`.** An authority-layer kit holding storefront commercial policy;
  buyers and non-pool callers would install pool administration to evaluate it.
- **`kit/capability-shape`.** Its responsibility is capacity vocabulary — structure,
  flattening, digest — and pricing was kept out of it as commercial evaluation.
- **Extending `kit/capability-pricing`.** The two share a concept at the level of a
  one-line description and nothing else: they change for independent reasons
  (non-linear pricing and amount precision versus coupled constraints), share no code,
  and are reused apart — pool administration needs admissibility's structural check
  without pricing, and hold billing and buyer quoting need pricing without
  admissibility. A merged kit would need a rename and would hold two unrelated halves.
- **Domain only.** Gives up the domain-neutral concept; a second domain would copy it.

### D3. Whole shape in, problems out, never readable bounds

The kit's surface has two groups. Callers hold a `Declaration` and a `ResolvedPolicy` as
opaque values; only the kit reads their contents.

**Declaration handling:**

- **`parse_declaration(raw, schema=None)`** returns a `Declaration` or every problem
  found. Without a schema it checks structure only — what the domain-neutral pool-write
  surfaces can know. With the domain's schema it also checks that every bounded path is
  a quantity field the schema defines.
- **`resolve(declarations)`**, given declarations highest tier first, returns a
  `ResolvedPolicy` or every problem found. Each section owns its merge rule; `bounds`
  merges per leaf, a higher tier replacing and never removing (D9). An empty range is a
  problem. Which tiers apply, and in what order, is the caller's choice; what merging
  them means is the kit's.

**Evaluation on a `ResolvedPolicy`**, both taking shapes and neither exposing
unconditional bounds:

- **`admissibility_problems(shape)`** returns a tuple of problems, empty when
  admissible. A problem carries `paths` (a tuple, so a constraint relating several
  dimensions names all of them), a `code`, and a `message`.
- **`admissible_values(dimension, partial_shape)`** returns the values `v` for which the
  partial shape with the dimension set to `v` can still be completed to an admissible
  shape. Dimensions the partial shape does not state are free; any value it states for
  the dimension itself is ignored.

The second operation carries a guarantee a counter-proposal policy relies on: fixing
dimensions one at a time, in any order, each to a value from the current answer, never
leaves a later answer empty and always ends at an admissible shape. A policy can
therefore build a counter-shape in whatever priority it chooses without search and
without assuming the region is a box.

What protects callers from a later rewrite is that the whole shape goes in and no bounds
come out. A problem naming one path, or a range for one dimension ignoring the rest,
would encode the box in the return type; a static implementation that "ignores the
remainder" would encode it in the requirement. Neither is specified.

Rejected:

- **A readable `(min, max)` per dimension.** Every caller comparing locally encodes the
  box; replacing it means rewriting each caller.
- **A range for one dimension given every other dimension fixed.** Meaningless when the
  remainder is itself inadmissible, and ambiguous about dimensions not yet chosen.
- **Problems that carry a per-dimension range.** Reintroduces the per-path assumption a
  constraint over two dimensions cannot satisfy.
- **A nearest-admissible-shape operation.** Which dimension to give up is negotiation
  policy; it can be built on `admissible_values` in the policy layer.
- **A boolean predicate.** Publication and negotiation both need the reason.
- **Merging or path checks outside the kit.** A storefront merging tiers, or a domain
  walking a declaration's paths, is a reader of bounds; a merge written there would be
  box-shaped, since a later section such as `ratios` has no leaves to merge.
- **The kit enumerating paths for the domain to check.** Passing the schema in keeps
  every read inside the kit and needs no further domain code.

Both evaluation operations ship with the static implementation. `admissible_values` has a
production caller in the VM default generator (D10) and is the primitive a dimension
counter-proposal change will use.

### D4. Admissible values are an opaque set

`admissible_values` returns an `AdmissibleValues` that answers questions rather than
exposing its representation: `is_empty`, `contains(v)`, `at_most(v)` (the greatest
admissible value not above `v`), `at_least(v)`, `minimum`, and `maximum` (absent when
unbounded). The static implementation backs it with an interval. An answer is valid only
for the partial shape it was computed from; a caller that caches an unconditional answer
as "the bounds" reads bounds directly.

Rejected: an interval type, which cannot represent discrete steps or gaps a later
constraint produces, so the first such constraint would change the type under every
caller; and an interval with a step, which invites callers to do step arithmetic
themselves.

### D5. Bounds are declared as `shape_bounds`, keyed by offering mode, in named sections

```yaml
shape_bounds:
  vm:
    bounds:
      gpu:    { count: { min: 1, max: 8 } }
      memory: { gib:   { max: 512 } }
```

- **Family-grouped paths**, the vocabulary of shapes, `listing_shapes`, and `pricing`,
  so a listing shape and its bounds cannot name one dimension two ways; flat claim
  names, still under `settle-capacity-claim-vocabulary`'s review, are not used.
- **Keyed by offering mode**, as `listing_shapes` is, because one pool may deliver
  several modes with different limits.
- **Each mode holds named constraint sections.** This change defines one, `bounds`: a
  family-nested map of quantity fields to `{min, max}`. Either key may be omitted, not
  both; values are positive integers with `min ≤ max`. A field appears once.
- **Strict keys.** A leaf key other than `min` or `max`, or a section the reader does not
  define, makes the declaration unreadable. Later forms — `ratios` relating two
  dimensions by `family.field` path, compared by integer cross-multiplication, or a
  `required` section — are added as sections, and a reader that predates them fails
  closed rather than enforcing a weaker policy.
- **Quantity fields only.** Given the domain's schema, the kit rejects a bound on an
  attribute or on any field the schema does not define as a quantity.
- **The admissible region is the intersection of every section;** no section widens
  another.

Rejected:

- **A tag per form** (`shape_bounds` now, `shape_constraints` later). Unknown tags are
  opaque, so an older storefront would silently ignore a newer constraint and sell
  outside it.
- **A concept-named tag holding a list of typed constraints.** Fails closed equally, but
  makes the common case a list of one and permits two `bounds` entries.
- **Bounds as a list of path entries.** Permits duplicates and departs from the family
  nesting.
- **A minimum shape and a maximum shape.** Cannot reuse shape validation because a bound
  must not state required attributes, and invites flattening "the maximum" and
  comparing.
- **A `step` key now.** No seller needs discrete values yet; strict keys let it be added
  later safely.
- **Bounds keyed by attribute value** (per GPU model). A limit depending on another
  value is a constraint of its own kind and would be a section.

### D6. A dimension a shape omits is free

A shape is admissible when the dimensions it states, with the ones it leaves free, can be
completed to an admissible shape — the meaning `admissible_values` already has, so the
two operations never disagree. A shape that omits a dimension commits to nothing on it:
the claim does not reserve it and the pool's defaults or provisioning supply it, which is
the site's decision, not the storefront's. For `bounds`, an omitted field never violates.

Rejected: a `min` requiring the dimension to be stated (mixes a range with a requirement,
and adding a memory minimum would withhold every GPU-only listing); judging the omitted
dimension at the pool default (provider-specific, site-decided, and undefined without a
default).

### D7. An absent bound commits nothing

A pool, mode, or field with no declared bound broadcasts no commitment on it. The
storefront decides what applies, through its own tiers (D9); where no tier bounds a
field, admissibility does not constrain it, and site admission remains the backstop.
This is not a permissive default awaiting a fail-closed alternative; it is what absence
means, as an unrated family is in pricing.

### D8. When the storefront cannot compute its policy, it fails closed

The storefront's policy is defined as the merge of every tier (D9). When `resolve`
returns problems instead of a policy, the storefront cannot compute its own policy for
that pool and mode, and it fails closed:

- **An empty merged range.** The resolved policy would admit nothing on that dimension.
  The pool's listings close and the report names the conflicting tiers and values.
- **A tier the storefront cannot read or evaluate**: malformed, a path its schema does
  not define as a quantity, or a section or key newer than its kit — in the pool hint or
  a stored override alike. The pool's listings close and nothing is published from the
  pool until every tier is usable. Skipping the unusable tier is not available, because
  a higher tier may not remove a lower one (D9).
- **A malformed configured default prevents the storefront from starting**, the same
  rule applied to the storefront's own input.
- **A pool whose projection has not loaded keeps the existing hold.** Nothing new has
  been declared; the last resolved policy still applies.

The report names the tier, the path, and the problem. Closing also makes the
disagreement visible to both administrators, who reconcile it. Pricing holds where this
closes because a last-published price is still an offer the storefront itself made;
here the storefront cannot say what it would sell.

Rejected: holding listings open on last-known-good bounds (sells against a policy the
seller may have tightened); holding listings and refusing only revised shapes (sells
published shapes a new constraint may exclude); ignoring the unusable declaration (sells
beyond a stated policy).

### D9. Tiers merge per field; a higher tier replaces, never removes

`shape_bounds` resolves per offering mode from three tiers, highest first: the
site-scoped storefront pool override, the pool hint, and the storefront's configured
default. They merge per leaf (`family.field.min`, `family.field.max`): for each leaf the
highest tier stating it wins, and a tier that does not state a leaf leaves the lower
tier's value in place.

```text
hint:      gpu.count {min: 1, max: 8}     memory.gib {max: 512}
override:  gpu.count {max: 4}
default:   memory.gib {min: 16}
resolved:  gpu.count {min: 1, max: 4}     memory.gib {min: 16, max: 512}
```

A storefront may change a site's bound, including widening it — the hint is advisory and
site admission still bounds physical capacity — but may not remove one: omitting a stated
site preference is not available to a higher tier. A per-leaf merge can produce an empty
range: an override write is refused when it would empty a range against the current
hint, and an empty range found when a projection arrives is handled by D8.

The merge belongs to the kit's `resolve`, and each section owns its rule: `bounds`
merges per leaf, and a later section's rule is set inside the kit when that section is
defined. The storefront only chooses the tiers and their order. The configured
default's key is named in planning.

Rejected: hint only (leaves the storefront no way to state policy where the pool is
silent); whole-declaration replacement per tier (drops site bounds an override does not
restate); intersection across tiers (narrowing only, contradicting D1's advisory hint).

### D10. Publication never advertises an inadmissible shape

- **A stated listing shape** — from an override or the pool's `listing_shapes` — that is
  inadmissible under the resolved bounds is not published, an open listing for it
  closes, and it is reported with its source tier and problems.
- **An override write** is refused when `resolve`, given the override with the current
  hint and default, returns problems, or when the override's own `listing_shapes` would
  be inadmissible under the policy it produces; this sits beside the contribution's
  existing feasibility check.
- **A pool write is not refused** when its `listing_shapes` fall outside its own
  `shape_bounds`: a storefront tier may widen the bound, and the provisioning service
  cannot see those tiers.
- **The VM default generator generates only admissible shapes**, choosing GPU counts
  from `admissible_values` rather than generating and filtering. Generated shapes are
  nobody's statement, so none is reported.
- **Reports.** The per-site derivation report gains inadmissible listing shapes (tier,
  shape, problems) and unusable shape bounds (tier, path, problem, or the conflicting
  values of an empty range), served by system status beside `unreadable_asking_rates`
  and logged once per change.
- **Bounds that change after publication** advance the projection's revision;
  reconciliation then closes listings whose shapes became inadmissible. Every shape the
  storefront agrees to is admissible under the bounds in force when it agrees; enforcing
  that in negotiation is `negotiation-driven-capacity-resize`'s composition.

### D11. Permanent destinations are confirmed in planning and review

`site-capacity` is not a destination: nothing about the site changes. The proposal's
`Knowledge to promote` names a provisional destination for each decision; planning and
review confirm or move them. Two are fixed: every negotiation rule — the agreement
invariant, the omitted-dimension refusal, and refusing revised shapes for a pool whose
policy cannot be computed — belongs to `negotiation-driven-capacity-resize`, because
nothing here enforces them, and `docs/development/ARCHITECTURE.md` gains the foundation
kit and an authority-boundary row.

### D12. VM composes fully; bare metal enforces at publication

- **VM**: tiers, publication, generator, override write check, reports, and — through
  `negotiation-driven-capacity-resize` — negotiation.
- **Bare metal**: each Physical Resource's derived shape is judged against the resolved
  bounds for the `bare_metal` mode, through the same three tiers and its existing pool
  overrides; inadmissible shapes and unusable declarations are handled as in D8 and D10.
  Bare metal negotiates no shape, so there is no negotiation composition. This keeps D8
  and D9 uniform: every storefront that publishes capability shapes honours
  `shape_bounds` for its mode.
- **API credits** is not a listing-shape domain and does not read the tag.

The kit's neutrality is proven at the lowest level: an import-boundary test, and unit
tests against a synthetic schema with no compute vocabulary.

### D13. Buyer disclosure is a separate change

Hardware bounds are not commercially sensitive, unlike rates, and a buyer should be able
to discover them. Disclosure is owned by `publish-shape-bounds`, so this change closes
out without a registry prerequisite. Decided inputs carried there: the resolved
declaration is disclosed and evaluated through this kit; VM listings only; registry
filtering is decided with the carrier. Its open question is how to represent a base
offering, a range around each base value, and pairwise ratios concisely; neither a field
inside `listing_resource` nor a separate top-level `shape_bounds` beside it was found
satisfactory.

## Inputs to other changes

To `negotiation-driven-capacity-resize`, for its own design:

- Every shape the storefront agrees to is admissible under the bounds in force when it
  agrees, whether the listing's own shape or a revised one.
- By default, a revised shape that states a dimension the listing's shape omits is
  refused: under shape pricing an unrated family contributes nothing, so accepting it
  would give the dimension away. How omitted dimensions are negotiated is a replaceable
  policy a storefront selects at composition.
- A revised shape for a pool and mode whose policy cannot be computed (D8) is refused
  for admissibility, distinctly from a shape outside the bounds.
- An admissibility refusal carries the kit's problems (`paths`, `code`) and may carry
  `admissible_values` for each refused path given the rest, so a buyer can counter.

## Risks / Trade-offs

- **A caller reads the declaration directly** → undoes D3. Only the kit interprets a
  declaration; closeout verifies that nothing outside the kit walks a `shape_bounds`
  value or a `Declaration`'s or `ResolvedPolicy`'s contents, that the raw reader passes
  its value unread to `parse_declaration`, and that no unconditional `admissible_values`
  answer is cached as bounds.
- **Closing on an unusable declaration churns listings** → accepted: closed listings
  republish as successors once the declaration is usable. Honouring the site's stated
  commitment is the better failure.
- **A storefront that does not compose admissibility ignores the hint** → each
  shape-publishing storefront composes it (D12); a domain that negotiates shapes without
  it says "not checked" under `negotiation-driven-capacity-resize`'s contract.
- **`admissible_values` is wider than its first caller needs** → accepted to support
  dimension counter-proposals without changing the interface later.

## Migration Plan

Additive. No pool declares `shape_bounds` initially; with no tier stating a bound,
nothing is constrained and publication is unchanged. The VM generator's output is
unchanged where no bound applies. Rollback is a code revert; stored hints and overrides
carrying the key are then ignored as unknown metadata.

## Open Questions

- **Upgrade ordering when site and storefront operators differ.** A new section written
  to a pool closes that pool's listings on storefronts whose kit predates it. Today one
  business operates both. Revisit at the first major release, when operators are not all
  known, with operator guidance on upgrading storefronts before writing new sections.
- **A `required` section.** For a seller who needs every deal to state a dimension rather
  than leave it to the pool default.
- **Bounds keyed by attribute value.** For a pool whose members carry different GPU
  models with different per-VM limits.
- **Site-enforced shape limits.** For a delivery limit within physical capacity that a
  storefront ignoring the hint would turn into a failed fulfillment.

## Findings outside this change

- `kit/resource-pools` duplicates the pricing rate-list structural check
  (`validate_pricing_rates`) rather than calling one owned by `kit/capability-pricing`,
  unlike `listing_shapes`, which calls the shape kit's check.
- `docs/development/ROADMAP.md` Goal 2 says the seller's own feasibility check compares
  region and GPU model by equality and no quantitative dimension; the inventory guard
  also checks the published quantity against its source. Corrected at this change's
  roadmap currency step.
- **Storefront term tiers are resolved four times over.** Family rates
  (`pricing_resolution.resolve_family_rates`), listing shapes, asking rates
  (`resolve_vm_asking_rates`), and now shape bounds each resolve override, hint, and
  default separately, yet follow one rule: mappings combine key by key, and a scalar or
  list is a leaf the highest tier stating it replaces whole, never removed by omission.
  `market_config.config_loader._deep_merge` applies the same rule to configuration
  files. A shared precedence merge with per-leaf provenance could serve all of them; its
  home — likely a small standard-library foundation module rather than core, which
  carries pydantic and market contracts — and the migration of the three VM resolvers
  belong to a change of their own. Until then the mechanism lives inside this kit's
  `bounds` section. No change owns it.
- A pool default outside the resolved bounds (a dimension a shape omits being supplied
  above its maximum) is a site configuration fact under D1 and D6; publication could
  report it as a warning. No change owns it.
- This change's `tasks.md` predates these decisions and is replanned after design
  review.
