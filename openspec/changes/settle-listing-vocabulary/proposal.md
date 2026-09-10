## Why

Four names refer to one concept, and one name refers to three concepts.

The concept a listing uses to say what is being sold is called `offering_mode` at
the storefront and on Resource Pool declarations, `executor_kind` on the capacity
claim wire, and `virtualization_type` in the published listing.
`structured-capacity-requirements` proposes a fourth, `offering_type`, having not
noticed the other three. The wire field's own description is *"Explicit offering
mode requested by the capacity reservation"*, and
`arkhai_vms/storefront_adapter.py` assigns `"virtualization_type":
candidate["offering_mode"]` — the names are not related concepts, they are the same
value.

Meanwhile `offer` means a negotiation message either party sends
(`message_type="offer"`), the seller's published listing shape (`offer_resource`),
and a second accepted spelling of that shape (`core/registry-client` reads
`d.get("offer") or d.get("offer_resource")`). Buyers make offers; only sellers make
listings.

And `executor` means the offering-mode axis (`executor_kind`, and
`ARCHITECTURE.md`'s "defaults an executor mode", "a default executor", "other
executor kinds"), while an in-flight change uses it for the machine ("Host is
executor identity only"). A third proposal would have made it the pool's delivery
handler.

This is the moment to settle it. The claim wire crosses the storefront-to-site
boundary between independently deployed services; today that relationship is
one-to-one and every party running a storefront runs its own site, so a rename
needs no compatibility window. The scoped one-storefront-to-many-sites work closes
that window, and an eventual many-to-many closes it permanently.

Sequencing matters too. `unbacked-listing-publication` and
`publish-indicative-listing-rates` both add fields to `offer_resource` and filters
on them. Renaming after they land means rewriting their deltas and their code
immediately; renaming first means they are written against the final names.

## What Changes

- **`listing_mode` → `listing_cardinality_mode`** on the projected pool hint, with
  its scope stated normatively: how many listing candidates a pool yields and how
  each is identified. A value describing what is offered, how a deal settles, or
  whether an admission authority backs the listing is out of scope.
- **`executor_kind` → `offering_mode`** on the capacity claim wire and through
  `kit/site`, `kit/fulfillment`, both provisioning adapters, and the storefront
  claim builders. One name for the value `pool_delivers_offering_mode` already
  compares against `deliverable_modes`.
- **`offer_resource` → `listing_resource`** marketplace-wide, and the `offer` alias
  for it removed from the registry client. `offer` is left to mean a negotiation
  message. This is a generic registry envelope field, so it moves in all three
  deployed filter specifications — compute, API credits, and introductions — each
  with its own version bump, not only in the compute schema.
- **`virtualization_type` → `offering_mode`** in the published listing shape, its
  filter, the `VirtualizationType` enum, and the buyer CLI flags. The published
  field is required to equal the recorded offering mode and is assigned from it;
  the current name also asserts a virtualization type for `bare_metal`, which is
  not one.
- **Retire `executor` as a synonym**, not as a word. `provisioning/compute`'s
  `ExecutorAdapter`, `ExecutorAdapterRegistry`, and `ExecutorActionEnvelope` are a
  real action-dispatch abstraction — they validate parameters, submit work, and
  validate results and credentials — and that abstraction keeps the name. What is
  retired is `executor` standing in for the machine, the offering mode, or the
  provider. The adapter's *selector* moves with everything else:
  `ExecutorAdapter.executor_kind` becomes `offering_mode`, so an executor adapter is
  selected by the offering mode it serves. This reverses
  `capacity-resource-administration`'s "Host is executor identity only" to
  connection identity, and `project-capacity-resources-without-hosts`' executor
  correlation language to host correlation.
- **`schema.id: vms.compute` → `compute.market`**, matching the
  `introductions.market` convention and stopping the compute-family schema from
  naming one domain when it carries bare metal and containers too.
- Bump the filter-spec `version` for a backwards-incompatible listing shape, and
  the schema `version` with it. Buyer clients declare schema compatibility, so they
  move in lockstep.
- No compatibility window and no aliases for any of the above, except the
  `listing_mode` ingestion alias, which is kept because that key is optional and
  its silent absence resolves to a structural default rather than an error.
- **Migrate the persisted state.** These names are not only on the wire.
  `CapacityReservation.executor_kind` is a real column, `scheduling_requirements` is
  a `Column(JSON)` whose stored value is compared structurally for settlement
  idempotency, and `offer_resource` is persisted as JSON in storefront listings and
  registry rows. Each gets an explicit strategy; see `design.md`'s migration matrix.
  The cutover uses the identity-contract pattern already documented in
  `DEPLOYMENT_AND_CONFIG.md`: quiesce authenticated mutations, migrate the
  identity-bearing state, verify every participant reports the pinned version, then
  resume.

## Capabilities

### Modified Capabilities

- `storefront-publication`: the cardinality hint is named for its scope; the
  published listing shape and its offering-mode field carry their settled names.
- `registry-discovery`: the schema identity, the listing shape key, and the
  offering-mode field and filter carry their settled names, across every deployed
  filter specification.
- `site-capacity`: the capacity claim's offering-mode field carries its settled name.
- `resource-pool-management`: the policy-metadata requirement names
  `listing_cardinality_mode`.
- `physical-provisioning`: release-status lookup is selected by `offering_mode`, and
  the executor-adapter abstraction is selected by it.
- `deployment-state`: the compute filter specification is selected by its new schema
  identity.

### New Capabilities

None. This change adds no capability; it renames vocabulary across existing
ones. It does change observable contract behaviour on purpose — see Non-Goals
and `design.md` — so "no behaviour change" is not its validation oracle.

## Non-Goals

- Do not rename `deliverable_modes` or `advertisable_modes`. Both already name sets
  of offering modes and are consistent once `executor_kind` moves.
- Do not rename `provider`. It stays the pool's delivery handler, distinct from the
  host it delivers on and from the offering mode it delivers.
- Do not rename `resource_kind` or `resource_type`. Those are the site-inventory
  discriminator and a different axis, which is what the offering-mode field exists
  to be separate from.
- Do not introduce `offering_type`. `structured-capacity-requirements` should drop
  it: the concept exists three times over and this change collapses it to one.
- Do not change business semantics. This change **does** change observable contract
  behaviour on purpose — retired names are rejected, schema identities and versions
  move, old clients stop being compatible, CLI flags change — so "no behaviour
  change" is not the validation oracle. See `design.md`.
- Do not add a compatibility window for the wire renames. See `design.md` for why
  the window is closing rather than open.

## Impact

- Affected code: `kit/site`, `kit/fulfillment`, both provisioning adapters, the VM
  and bare-metal storefronts and their listing models, `core/storefront`,
  `core/storefront-client`, `core/registry` and `core/registry-client`, the buyer
  CLIs, and the projection producer and consumers. 51 non-test files reference
  `offer_resource`; 16 reference `virtualization_type`; `executor_kind` appears 287
  times.
- Affected specification: `openspec/specs/storefront-publication/spec.md` and its
  architecture companion, `openspec/specs/registry-discovery/spec.md`,
  `openspec/specs/site-capacity/spec.md`.
- Affected registry deployment: `core/registry/filter-spec.yaml`'s schema identity,
  listing shape, and filters, with both versions bumped. The API-credits filter-spec
  keeps its own identity and does not publish an offering-mode field.
- Affected deployment: a storefront and its sites must deploy together for the claim
  wire, and buyer clients must move with the registries they query. Both are true of
  every known deployment today.
- Affected persisted state: one column rename, two JSON backfills, and three
  filter-specification version bumps.
- Affected in-flight changes: `capacity-resource-administration`,
  `project-capacity-resources-without-hosts`, `unbacked-listing-publication`,
  `publish-indicative-listing-rates`, `structured-capacity-requirements`,
  `bare-metal-buyer-domain`, `pools-7-storefront-fulfillment-cutover`,
  `pools-9-retire-local-physical-authority`, and
  `publish-multidimensional-listing-shape` reference at least one renamed name.
  Three of them carry it in **active spec deltas** —
  `multi-domain-storefront-composition` and both of `pools-8`'s — which is the path
  by which retired vocabulary would synchronize back into permanent specifications,
  so those are corrected rather than left to their owners.

## Dependencies and Related Changes

- No blocking dependency.
- **Prerequisite for `unbacked-listing-publication`** and therefore for the rest of
  Goal 7, which is a deliberate cost: Goal 7 waits on this so its own changes are
  written against settled names rather than renamed after landing.
- **Amends `structured-capacity-requirements`** to use `offering_mode` rather than
  proposing `offering_type`. That change has no spec deltas, so nothing of its
  vocabulary can reach a permanent specification — but two simultaneously active
  designs disagreeing about the canonical name for one concept is the condition this
  change exists to end. Whether the item survives at all is left to that change's
  owner; whether it may introduce a fourth name is not.
- Coordinate with `pool-declared-advertisement-and-backing`, which adds
  `advertisable_modes` and `capacity_backing` alongside the hint renamed here. No
  ordering dependency; adjacent lines.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the four occurrences using `executor` in
      the offering-mode sense, and any use of `offer_resource`.
- [x] Existing subsystem specification — `storefront-publication` (spec and
      architecture companion), `registry-discovery`, `site-capacity`,
      `resource-pool-management`, `physical-provisioning`, `deployment-state`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- One name for the offering mode across the claim wire, the pool declarations, the
  durable binding, and the published listing —
  `openspec/specs/storefront-publication/spec.md`.
- `offer` means a negotiation message; a seller's published shape is a listing —
  `openspec/specs/registry-discovery/spec.md`.
- The cardinality hint's normative scope —
  `openspec/specs/storefront-publication/spec.md`.
- `executor` names an action-dispatch abstraction and nothing else; the machine is a
  host, the handler is a provider, the mode is an offering mode —
  `docs/development/ARCHITECTURE.md`.
