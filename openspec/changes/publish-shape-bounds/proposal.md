# Publish a listing's shape constraints

## Why

A compute seller decides, per listing, which shapes it would agree to sell. A stated
listing shape may bound each quantity inline, as `{offer, min, max}`; the VM
storefront's configured default fills the bounds a listing leaves unstated; and the
storefront evaluates the resolved policy for every shape a buyer requests, before
pricing it
(`domains/vms/storefront/src/market_storefront/services/negotiation_shapes.py`,
`check_requested_shape`). A listing publishes none of it. Derivation flattens each
listing's offer into `listing_resource` and keeps the resolved policy only to decide
whether the listing may be published
(`domains/vms/listings/src/arkhai_vms_listings/reconciler.py`, `_admissible_shapes` and
`_shape_listing_resource`), and the configuration reference says a range is "never
published" (`openspec/specs/storefront-publication/configuration.md`).

So a buyer reads part of what a seller would sell and learns the rest by being refused:

- **It reads the offer, which is also the most it may ask for.** The seller refuses any
  quantity above the advertised one as `shape_exceeds_advertised`, and the VM buyer
  refuses it first (`domains/vms/buyer/src/arkhai_vms_buyer/opening_shape.py`,
  `shape_excess`). It reads whether any other shape is negotiable at all, from the
  presence of `pricing.rate_structure`, and the GPU model and region it must match.
- **It cannot read the least a seller would sell of each quantity.** A buyer who wants
  two GPUs queries `gpu_count>=2`, finds a listing of eight that its seller sells in
  fours or more, opens a negotiation, and is told
  `shape_inadmissible: ('gpu.count: 2 is below the minimum 4',)`.
- **It will not be able to read how far above the offer a seller would go.**
  `negotiation-capacity-feasibility-probe` lets a shape larger than the advertised one
  be negotiated. A seller's stated maximum then decides what may be asked, and it is in
  no listing.

The form a seller writes a range in is one a buyer could read, and the kit that
evaluates it is a foundation kit a VM buyer already installs with the VM domain
package. What is missing is the way out: a resolved policy is an opaque value no
operation renders
(`kit/capability-admissibility/src/market_capability_admissibility/__init__.py`,
`ResolvedPolicy`), nothing records it with the listing, and no buyer code reads one.

Nothing in a range is more sensitive than what a listing already publishes: the rates a
seller prices shapes from travel in `pricing.rate_structure`.

## What Changes

- **A compute listing publishes its resolved shape constraints as a listing-level
  term**, beside `pricing`, supplied by its domain and carried by core publication and
  the registry without either naming a constraint (design D1).
- **The term is the compute family's, and VM is its only producer.** A listing that
  negotiates no shape publishes none: a bare-metal listing, and a flat-priced VM listing
  (D2).
- **The admissibility kit renders a resolved policy**, and stays the only code that
  reads or writes a constraint. A buyer evaluates a published term through the kit and
  compares no number itself (D3).
- **The registry filters nothing on the term.** A buyer narrows the listings a registry
  query returns locally, through the kit. The compute filter specification only
  declares the term (D4).
- **The published copy is advisory.** The seller judges every requested shape against
  the policy in force and pins nothing to what it published; a buyer does not verify
  the term (D5, D6).
- **A bound the seller's policy does not state is not published**, and a listing whose
  policy constrains nothing publishes no term (D7).

What the term claims while a seller refuses asks its policy admits, what the term holds,
what a buyer command does with it, how the schema declares it, where the storefront
keeps it, whether a refusal carries the kit's problems as data, and the term's name are
open in the design's "Open Questions". The first is tied to
`negotiation-capacity-feasibility-probe`'s Q1 and is settled with it.

## Capabilities

### Modified Capabilities

- `storefront-publication`: the term a compute listing publishes, its refresh in place
  when only a range changes, and which listings publish none.
- `market-composition`: the admissibility kit's render operation, in "Capability shape
  admissibility is owned by one kit".
- `registry-discovery`: the compute schema's declaration of the term. No filter is
  added.
- `buyer-orchestration`: a compute buyer's local evaluation of a listing's term, if the
  design gives it a requirement (design Q3).

`.openspec.yaml` sets `skip_specs` until the design session settles the open questions;
the design's Q8 names the requirements to be modified and the ones to be added.

### New Capabilities

None.

## Non-Goals

- A registry filter over a constraint. The change index records it as unowned in Goal
  2's campaign, with what would bring it back (D4).
- An automated counter-shape policy. No buyer or seller builds a counter-shape today;
  the kit's values query is the primitive a later change uses.
- Constraints for a bare-metal listing, and admissibility composed in bare-metal
  publication (D2).
- The form a buyer states a shape in when it opens a negotiation.
  `unify-negotiation-shape-forms` owns it.
- Which shapes are admissible, how tiers resolve, and how publication enforces a
  policy. They are used as they stand.
- Whether the site would admit a shape, and what a buyer may ask above the advertised
  one. `negotiation-capacity-feasibility-probe` owns both.
- Respelling the compute family's flat dimension names, which stand
  (`openspec/specs/market-composition/architecture.md`, "The compute family
  vocabulary").
- API credits, whose listings are not listing shapes.

## Dependencies and Related Changes

- Nothing gates this change (D8).
- `negotiation-capacity-feasibility-probe` lifts the advertised-shape cap, and its Q1
  decides what a buyer may ask above the offer where a seller stated no maximum. This
  change's Q1 takes its answer. The two also meet in the VM buyer's check before it
  opens a negotiation (`domains/vms/buyer/src/arkhai_vms_buyer/opening_shape.py`).
  Neither waits for the other; whichever lands second reverifies against the other.
- `filter-listings-by-capacity-bounds` and `settle-capacity-claim-vocabulary` edit the
  compute filter specification, as this change does when it declares the term.
  Whichever lands later reverifies against the others. What a listing that states no
  bound answers a filter is settled once, in `filter-listings-by-capacity-bounds`, and
  is applied here by convention if a constraint filter is ever added (D4).
- `unify-negotiation-shape-forms` owns the form of a buyer's opening shape. A buyer
  command that reads this change's term and sends a counter-shape is what makes that
  question real; neither change waits for the other.
- **Builds on**, all archived: `capacity-shape-envelope` (admissibility, the inline
  form and the kit), `store-registry-listings-as-published` (a registry keeps every
  admitted term with the seller's signed publication),
  `negotiation-driven-capacity-resize` (a round's shape, the evaluation order, the cap
  and published rates), and `gpu-optional-compute-shapes` (a shape that states no GPU).

## Impact

`kit/capability-admissibility` (the render operation, a minor version),
`domains/vms/listings` (derivation keeps each listing's policy; the term is a term of
sale in listing comparison), the VM storefront's publication candidate and, if the
design stores the term, core storefront's listing record and its migration chain,
`core/registry` (the compute filter specification's listing schema), the VM buyer's
check before opening and its listing display, `domains/compute` if the family's reader
lives there (design Q3), `openspec/specs/storefront-publication/configuration.md`,
`docs/operator-handbook.md` and `docs/buyer-quickstart.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **The registry.** A 0.4.0 registry admits the term as a top-level property its schema
  does not name, stores the complete publication and serves it unchanged with the
  seller's signed publication. It refuses a range placed on a typed quantity of
  `listing_resource` and anything added inside `pricing`, which is why the term is in
  neither (D1). Declaring the term changes the specification's ETag, which a 0.4.0
  buyer refetches; no value type or missing-value rule is added, so its compiler reads
  the specification as before.
- **Buyers.** A 0.4.0 VM buyer drops a top-level term it does not know and negotiates
  as it does today: it applies the advertised cap itself and learns a minimum from a
  refusal. A released buyer is owed nothing by a later storefront
  (`docs/guidance/repository/package-versions.md`, "Compatibility is owed to what a
  release has shipped"), and here it loses nothing.
- **Storefronts.** A 0.4.0 storefront publishes no such term, and the schema keeps the
  term optional, so a later registry admits its listings. It reads no other seller's
  listing. Pool hints and overrides are unchanged: 0.4.0 already reads inline
  constraints in them.
- **The site.** Nothing changes.
- **Wire.** One optional listing term. No negotiation message changes.
- **Persistence.** If the design stores the term, it is one additive, nullable column
  on the listing record, by a migration appended to the storefront chain that holds it.
  Migrations fail forward, so rolling back to 0.4.0 is restoring the backup taken
  before the upgrade (`docs/guidance/engineering/migrations.md`, "Migrations fail
  forward"). A listing a 0.4.0 storefront wrote publishes its term at its next
  derivation, with no backfill.
- **Configuration.** No setting is added, and nothing is shipped disabled.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "Discovery and negotiation".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/storefront-publication/spec.md` and its companion's "Shape
  constraints"; `openspec/specs/registry-discovery/architecture.md`, "Retained
  publication documents".
- D2: `openspec/specs/storefront-publication/spec.md` and its companion's "Bare-metal
  listing shapes" and "Shape constraints", where the difference is stated.
- D3: `openspec/specs/market-composition/spec.md` and its companion's "Capability shape
  admissibility".
- D4: `openspec/specs/registry-discovery/spec.md` and its companion;
  `docs/buyer-quickstart.md`.
- D5: `openspec/specs/storefront-publication/spec.md`;
  `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order".
- D6: `openspec/specs/registry-discovery/architecture.md`, "Seller publication
  evidence".
- D7: `openspec/specs/storefront-publication/spec.md`;
  `openspec/specs/storefront-publication/configuration.md`, whose sentence that a range
  is never published is restated.
- D8: `docs/development/ROADMAP.md`, Goal 2, whose open-gap row leaves the table and is
  absorbed into the goal's current state when this change closes out.
