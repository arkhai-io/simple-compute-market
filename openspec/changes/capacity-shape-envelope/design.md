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
- **A stated list is deduplicated by digest, keeping the first entry**
  (`_deduplicated` in `arkhai_vms_listings.listing_shapes`); the digest is the shape
  kit's `shape_digest` over the canonical form and needs no schema. An unreadable entry
  makes the whole list unreadable and holds the pool; reconciliation closes any open
  listing a pass does not derive again unless the pool is held.
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

### D3. Whole shape in, problems out, never unconditional bounds

Callers hold a `Declaration` and a `ResolvedPolicy` as opaque values; only the kit reads
their contents. No operation gives a caller a policy-level range for a dimension
independent of the rest of a shape; the values one dimension may take are answered only
for a particular partial shape (D4).

**Declaration handling.** Each takes a `tier` label that every problem it returns, and
every problem resolution later returns about it, carries:

- **`split_listing_shape(raw, *, tier, schema=None)`** returns the base shape — every
  field's committed value, with constrained fields reduced to their `offer` and
  constraint-only fields omitted — and either the shape's `Declaration` or its
  constraint problems. A base shape that is not structurally a shape is returned as
  the shape kit's problems, with no declaration. Without a schema it checks structure
  only, which is what the domain-neutral pool-write surfaces can know; with the
  domain's schema it also checks that every constrained path is a quantity the schema
  defines. The base shape is read first: a constraint error that leaves the base shape
  unreadable under the schema — a constraint-only mapping on a required field, such as
  `gpu.model: {max: 4}` or `gpu.count: {min: 2}` under the compute schema — is reported
  as a base-shape problem, with no declaration. Only a constraint error on a readable
  base shape is a constraint problem.
- **`split_listing_shapes(raw_list, *, tier, schema=None)`** splits a stated list,
  entry by entry as `split_listing_shape` does, and also reports each base shape that two
  entries state with different constraints, naming each conflicting entry. Entries with
  identical base shapes and identical constraints collapse to one. The base identity is
  the shape kit's `shape_digest`, which needs no schema, so the domain-neutral pool-write
  surfaces detect a conflict as the domain does. Every reader of a stated list calls this
  operation; none compares two entries itself.
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

What protects callers from a later rewrite is that the whole shape goes in and no unconditional
bounds come out. A problem naming one path, or a range for one dimension ignoring the rest,
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
`None` when unbounded. On an empty set `is_empty` is true, `contains(v)` is false, and
every value-returning accessor (`at_most`, `at_least`, `minimum`, `maximum`) returns
`None`, so a caller checks `is_empty` first. These are bounds conditional on one partial
shape, which D3 permits; an unconditional range per dimension is what it forbids. The static implementation backs it with an interval. An answer is
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

A listing's policy is the merge of its tiers (D9). The stated list is read base shape
first (D3). When any entry's base shape cannot be read — including because a
constraint-only mapping removed a required field — the list is unreadable and the
existing rule applies: no new listing from the pool, its existing listings held, each
problem reported. When every base shape can be read but a listing's policy cannot be
computed, the storefront fails closed for that listing alone:

- **Its constraints cannot be read** — a constraint on an attribute or an undefined
  field that leaves the base shape readable, or a key newer than the storefront's kit —
  in the pool hint or a stored override.
- **Its merged range is empty** — for example, the listing states `max: 4` and the
  configured default `min: 8`.
- **Its base shape is stated twice with different constraints** — for example,
  `gpu.count {offer: 1, max: 4}` and `gpu.count {offer: 1, max: 8}` for the same model.
  Identical entries collapse and are not a conflict.

That listing is not published and an open listing for it closes; the pool's other
listings are unaffected. The report names the tier, the path, and the problem, each
tier's conflicting value, or each conflicting entry. A malformed configured default
prevents the storefront from starting, the same rule applied to its own input.

Whether to hold or close follows one test. A hold keeps the last-published offer
standing while a declaration cannot be read, and is right when that offer is still one
the storefront made: an unreadable price holds because the last price was the
storefront's own offer, and an unreadable shape list holds because an unreadable
declaration is not a withdrawn one. A close is right when every declaration can be read
but the storefront can no longer say what its own policy would sell: keeping the listing
open would advertise what that policy may exclude, and the site cannot be refused a
projection, so closing is the signal that reaches the site's administrator, who then
reconciles with the storefront's administrator.

Rejected: holding listings and refusing revised shapes when the policy cannot be computed
(ignores the storefront's policy while the listing stays open); closing every listing of
the pool (punishes listings whose policy is computable); ignoring the unusable
constraint (sells beyond a stated policy); reading each entry on its own so that an
unreadable base shape closes only its entry (reverses the existing hold for every
malformed shape, constrained or not); closing an entry only when its unreadable base is
caused by a constraint (every edge, such as `{offer: 0}`, becomes a classification an
implementer guesses); for duplicates, keeping the first entry (order-dependent and
silent), intersecting their constraints (silently combines two statements of which the
author meant one), and treating the list as unreadable (holds a readable list, and
blocks every listing of the pool for one duplicate).

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

**The configured default is `[admissibility.defaults.vm]`** in the VM storefront's
settings, keyed by offering mode as `listing_shapes` is, in the listing shape's family
nesting and field syntax without `offer`:

```toml
[admissibility.defaults.vm.gpu]
count = { min = 1, max = 16 }

[admissibility.defaults.vm.memory]
gib = { max = 512 }
```

`settings.toml` ships none, because a higher configuration layer cannot remove a table a
lower one set. Absent and an empty table both mean no default: nothing is constrained
and the generator generates what it does today. A malformed table — an unknown key,
`min` above `max`, an `offer`, a constraint on an attribute or an undefined field —
stops startup, as an unreadable `[pricing.defaults]` family rate does. Startup parses it
once, with `parse_declaration(tier="configured_default", schema=VM)`, and the same
`Declaration` reaches the publication loop, the default generator's composition, and the
VM override contribution.

Rejected for the carrier: `[admissibility.defaults]` without a mode key, as
`[pricing.defaults]` is (D9 defines a default per mode, and a later mode would move the
keys); `[listing_shapes.defaults.vm]` (names it by where it applies and suggests it
supplies shapes, which the generator does).

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
- **Listings derived from local tables** (`capacity.use_site_projection_for_listings =
  false`) take the same default-only policy: their GPU-only counts are chosen from
  `admissible_values` exactly as the generator chooses them. Local tables hold no hint
  and no override applies there, so the configured default is the only tier, but it is
  the storefront operator's own policy and governs everything the storefront publishes;
  leaving the path unconstrained would make "publication never advertises an
  inadmissible offer" carry an exception until local derivation is retired. Rejected:
  leaving local-table derivation unconstrained and documenting the limitation.
- **An override write is refused** when one of its shapes' base shapes or constraints
  cannot be read with the domain's schema, two of its shapes state one base shape with
  different constraints, or a shape resolves to an empty range against the configured
  default or leaves its offer inadmissible. The check needs no site call: an override's
  shapes never merge with the live hint. It is the VM contribution's vocabulary check.
- **A pool write is refused** when a stated shape's constraints are structurally
  invalid, or when two stated shapes for one mode state one base shape with different
  constraints; whether a constrained path is a quantity is the domain's to judge. A
  list that contradicts itself is a fault in the site's own document whichever
  storefront reads it, and detecting it needs no domain vocabulary. It is not a
  judgement against any storefront's configured default. Identical entries are accepted,
  as today.
- **A listing's identity is its base shape.** The derivation digest is taken over the
  base shape, so changing a range does not change which listing it is; reconciliation
  re-evaluates the listing and closes it if its offer becomes inadmissible.
- **Asking rates match the base shape**, as they match a shape today.
- **Reports.** The per-site derivation report gains inadmissible listing shapes (tier,
  shape, problems) and unusable constraints (tier, path, problem, each tier's
  conflicting value, or each conflicting entry for a base shape stated twice), served by system status beside `unreadable_asking_rates` and
  logged once per change.
- **Every shape the storefront agrees to is admissible** under the policy in force when
  it agrees; enforcing that in negotiation is `negotiation-driven-capacity-resize`'s
  composition.

### D11. Permanent destinations are confirmed in planning and review

`site-capacity` is not a destination: nothing about the site changes. The proposal's
`Knowledge to promote` names a provisional destination for each decision; planning and
review confirm or move them. Fixed: every negotiation rule belongs to
`negotiation-driven-capacity-resize`, because nothing here enforces them;
`docs/development/ARCHITECTURE.md` gains the foundation kit, the test for whether a
storefront holds or closes a listing it cannot fully derive (D8), stated as a framework
with brief examples — pricing and an unreadable shape list hold, uncomputable
admissibility closes — while each term's own rule stays normative in
`storefront-publication`, and, in "Omission states no commitment", that an offer
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
  re-derived by splitting the listing's source shape list through
  `split_listing_shapes`, finding its entry by base shape, and resolving it with the
  configured default, so a base shape stated twice with different constraints is
  refused as it is at publication.
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

## Pilot merge reconciliation (2026-10-08)

This pilot owns the provisioning corrections exposed while merging development
into its implementation branch. The workflow change owns the implementation
process; these runtime corrections and their validation belong to this change.
They preserve the shape-admissibility design and do not extend it to bare metal
or alter site admission.

Provisioning integration validation exposed the fixture's shared
in-memory SQLite connection: request and background-job sessions can interleave
transactions, so closing one session may erase another session's reservation or
job state. The integration fixture must use the production file-backed engine
factory with a fresh temporary database per test. Independent connections follow
the existing deterministic database-concurrency architecture; weakening replay
verification or serializing unrelated application work would hide the fixture
error. A controlled overlapping-session regression proves the lost-reservation
failure without sleeps or repeated races.

The file-backed fixture also exposes a production relay-allocation deadlock:
fulfillment acceptance owns SQLite's writer slot while VM preparation allocates
through another session. The two relay acceptance/retry integration tests wait
out the busy timeout and return `provider_config_invalid`. The permanent provider
contract described pure preparation, while the implementation permitted allocation.
The owner accepted passing the acceptance session explicitly through provider and
plan preparation so the port lease and prepared operation commit or
roll back together. Preparation may acquire local database resources only through
that session; validation still acquires nothing, and external provider I/O stays
after commit. VM preparation refuses relay allocation without the caller's
session. The standalone allocator retains its self-committing entry point for
callers that own no outer transaction; acceptance uses `allocate_in_session`,
whose uniqueness retries use savepoints without rolling back acceptance.
The provider contract may name SQLAlchemy's session, already a fulfillment-kit
dependency; its module import-boundary check is updated for this explicit port.
Standalone SQLite allocation starts its outer write transaction before the
savepoint scan. A stale free-port observation must hit the uniqueness constraint
and retry rather than reassign an active lease; only released rows are reusable.

A separate allocation phase was rejected because it adds lifecycle/recovery
state for partial acceptance. Weakening the fixture would conceal the defect.
Integration coverage must prove successful acceptance, equivalent retry, and
rollback after a port has been allocated but later preparation rejects the
request. Permanent destinations are the provider contract and acceptance model
in `openspec/specs/fulfillment/spec.md` and
`openspec/specs/fulfillment/architecture.md`, the relay lease rule in
`openspec/specs/physical-provisioning/spec.md`, and the repository acceptance
boundary in `docs/development/ARCHITECTURE.md`.

The promotion record and local validation evidence are in `tasks.md`, Section 6A.
These corrections do not complete the remaining shape-admissibility sections or
the pilot's end-to-end and closeout gates. Roadmap and campaign status remain
unchanged.

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
- The pool's `pricing` hint carries no offering-mode key, while `listing_shapes` and
  `asking_rates` do, so a pool offering VM and bare metal gives both storefronts the
  same family rates although bare metal sells at a premium over a VM on the same
  hardware. A storefront override is per mode and can correct it; the site's own
  advisory price cannot differ by mode. `[pricing.defaults]` has the same gap if one
  storefront ever serves two modes.
- A site-visible report of why a storefront closed a pool's listings; the storefront can
  already call the site.
- The compute schema requires `gpu.count` and `gpu.model`, so a VM or bare-metal listing
  without GPUs cannot be stated.
- `domains/apicredits/tests/conftest_wheels.py` lists by hand the internal projects whose
  wheels its install tests build, so every new internal edge beneath the API-credits
  service breaks it until someone adds the project, as the admissibility kit did. The
  closure is already in each role's lock, and `scripts/uv_project.py` can map
  distribution names to project directories, so the list could be derived;
  `check-uv-setup` covers reinit targets and image installs but not test fixtures.
