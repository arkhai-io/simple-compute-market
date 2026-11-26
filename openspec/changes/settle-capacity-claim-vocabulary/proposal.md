# Settle capacity claim vocabulary

## Why

A compute shape need not state GPUs, and a seller can declare, publish and sell one that
states none. The word that would say what class of compute a deal is in does not move
with it. Every VM declaration is typed `compute.gpu` and every VM claim names
`compute.gpu`, whatever the shape
(`domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`), and
every VM reservation is scheduled under a default of `compute.gpu` that the provisioning
service configures
(`provisioning/compute/service/src/compute_provisioning_service/container.py`). The site
keeps a scheduling cursor for each kind and has one kind
(`kit/fulfillment/src/market_fulfillment/db.py`).

Three parties meet the consequence:

- **A buyer cannot ask for supply without GPUs.** The type is not published, and no
  registry query selects listings that state no GPU: a filter decides a missing value
  before an `exists` test runs
  (`core/registry/src/core_registry/api/filter_eval.py`). A buyer asks for vCPUs and
  memory and is answered with GPU listings as well.
- **An operator declares a machine with no GPU as `compute.gpu`.** One who writes
  `compute.cpu` gets a member no VM claim matches, reported as an infeasible listing
  shape with no mention of the type.
- **A bare-metal operator writes a second string, `compute.bare-metal`.** It restates the
  offering mode, the bare-metal claim does not name it, and only the storefront's
  scheduling request depends on it
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/delivery_ports.py`). A
  machine declared under any other type is admitted and then fails at scheduling.

The single type is deliberate: matched against the declaration, a second type would stop
a GPU host's spare vCPUs and memory selling as CPU-only VMs, since a host carries one
declaration (`openspec/specs/storefront-publication/architecture.md`, "Listing shapes
and the storefront's authority"). The category therefore has to be stated somewhere
other than the machine.

## What Changes

- **The resource type becomes the category of compute a seller sells**, such as
  `compute.gpu` or `compute.cpu`, in both compute domains (design D1, D3).
- **A Resource Pool states the categories it sells**, in its policy tags beside the modes
  it delivers. A claim carries the category of what is bought, the site admits it where
  the pool states that category and records it on the reservation, and scheduling reads
  it from the reservation, not from a default (D4).
- **A listing publishes its category and the compute registry filters by it**, so a buyer
  can search for supply without GPUs (D3).
- **A pool that states no category behaves as it does under `marketplace-v0.4.0`**, and
  its listings publish none. No capacity declaration is rewritten (D4).
- **Bare metal follows the same rule as VM.** What becomes of the string
  `compute.bare-metal` is open in the design (Q5).
- **The flat dimension names stand** (D2).

Which categories exist, which one a listing takes when its pool states several, what a
declaration's `resource_type` then does, the published field's name, the filter's
missing-value rule, and compatibility for a storefront and a site at different releases
are open in the design's "Open Questions".

## Capabilities

### Modified Capabilities

- `resource-pool-management`: a pool's stated categories and the pool fact the site
  reads.
- `site-capacity`: what a claim's resource type is matched against, the category a
  reservation records, and the projection's statement that every VM declaration and
  claim names `compute.gpu`.
- `fulfillment`: where scheduling reads a reservation's kind, and which declarations are
  its candidates.
- `storefront-publication`: the category a VM or bare-metal listing publishes, and its
  place in a listing's identity.
- `registry-discovery`: the published field and its filter.
- `compute-provisioning-contract`: only if the scheduling request or response changes.

`.openspec.yaml` sets `skip_specs` until the design session settles the open questions;
the design's Q10 names the requirements to be modified.

### New Capabilities

None.

## Non-Goals

- The fairness policy that chooses among a category's candidates. The cursor stays one
  row per kind and round-robin; `pools-6-fair-scheduling-policy` owns the policy.
- One declaration sold in two offering modes. A host carries one declaration and a pool
  one provider, and neither changes (D5).
- One name for `resource_type` and `resource_kind`. The site and the claim say type,
  fulfillment and the provisioning contract say kind, and both stay (Q10).
- The `resource_type` of a VM listing resource payload, which says whether the payload is
  compute or a token.
- Respelling the flat dimension names (D2).
- Renaming the storefronts' whole-claim key `required_attributes` (D1).
- The form a buyer states a shape in when opening a negotiation. A buyer opens with a
  flat, partial mapping and a later round carries a whole family-grouped shape;
  `unify-negotiation-shape-forms` owns it.
- Publishing no null for an absent capacity attribute, which VM publication already does.
- A third category. The design asks what one would be (Q9).

## Dependencies and Related Changes

- Nothing gates this change.
- `pools-6-fair-scheduling-policy` reads the scheduling cursor's key, which holds the
  category after this change. Neither waits for the other.
- `publish-shape-bounds` and `filter-listings-by-capacity-bounds` edit the compute filter
  specification. `filter-listings-by-capacity-bounds` meets the question of what a
  listing that states nothing answers, and the two changes take one answer (design Q6);
  `publish-shape-bounds` declares a listing term there and adds no filter. Whichever
  lands later reverifies against the others.
- `negotiation-capacity-feasibility-probe` builds and probes the claim this change adds a
  category to. Whichever lands second reverifies against the other.
- `kit-owned-storefront-auth-and-persistence` is noted in the change index as the place
  the `required_attributes` key is renamed, if it is.
- **Builds on**, all archived: `gpu-optional-compute-shapes` (shapes without GPUs, and
  the one resource type for every VM shape), `inject-site-pool-authority` (the pool facts
  the site reads through a port), `pool-declared-offering-modes` (the precedent for a
  pool statement the site enforces through fulfillment), and
  `store-registry-listings-as-published` (the registry keeps a listing as published, and
  VM publication omits an absent capacity attribute instead of publishing a null).

## Impact

`kit/resource-pools-contracts` and `kit/resource-pools` (the tag and the pool fact),
`kit/site` (admission, the reservation, the recorded request), `kit/fulfillment` (the
scheduling requirement and candidates), the compute provisioning service's composition
and migration chain and the API-credit service's chain, both compute storefronts (the
claim, publication, and bare metal's scheduling request), `domains/vms/listings` and
`domains/bare_metal` (the published field), `core/registry` (the compute filter
specification), `docs/operator-handbook.md`, both seller quickstarts,
`docs/buyer-quickstart.md` and `docs/development/ARCHITECTURE.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **Behaviour.** A pool that states no category admits, schedules and publishes as it
  does under 0.4.0. A reservation recorded by a 0.4.0 site is scheduled under the
  default, as today.
- **Operators' documents.** Capacity declarations are operators' documents, imported
  again at every start when mounted, so no migration retypes them and none is asked to
  change. A released declaration typed `compute.gpu` or `compute.bare-metal` keeps
  working as written.
- **The site and its storefronts.** A provisioning service and the storefronts that call
  it are upgraded and rolled back together (`compute-provisioning-contract`'s "Explicit
  contract incompatibility"). A 0.4.0 site accepts and projects the pool tag as one it
  does not know. What a storefront and a site at different releases do once a pool
  states a category, and whether the contract takes a new major, are the design's Q8.
- **The registry and buyers.** A 0.4.0 registry stores a listing's category as a
  property it does not name and filters on nothing. A filter added with known value
  types changes only the specification's ETag for a 0.4.0 buyer.
- **Persistence.** The reservation's category is an additive, nullable column, by a
  migration appended to each chain that holds the ledger. No record a 0.4.0 service
  wrote is rewritten.
- **Configuration.** One optional pool policy tag. No setting is added.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "One name per concept" and "Site authority".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/site-capacity/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "One name per concept".
- D2: `openspec/specs/market-composition/architecture.md`, "The compute family
  vocabulary", which states it already.
- D3: `openspec/specs/storefront-publication/spec.md` and
  `openspec/specs/registry-discovery/spec.md`; `docs/buyer-quickstart.md`.
- D4: `openspec/specs/resource-pool-management/spec.md`;
  `openspec/specs/site-capacity/spec.md` and its companion;
  `openspec/specs/fulfillment/spec.md`; `docs/operator-handbook.md`, "Pool definitions";
  `openspec/specs/storefront-publication/architecture.md`, "Listing shapes and the
  storefront's authority".
- D5: `docs/development/ROADMAP.md`, Goal 2, whose open-gap rows leave the table and are
  absorbed into the goal's current state when this change closes out.
