## Why

Once a buyer can request a capacity shape, a seller has to say which shapes it will
sell for a listing. Nothing expresses that today. `has_matching_inventory_guard` checks a
listing against its own source; a pool's `listing_shapes` hint states what a listing
offers, not what a buyer may ask for instead; site admission bounds only physical
capacity, offering mode, and the host requirement. No structure states that a listing
offered at one GPU will also be sold with up to four, or that memory a buyer asks for
stays at or under 512 GiB — and publication cannot keep an offer out on those grounds.

The concept is not domain-specific: a per-dimension admissible range is the same for VM
vCPUs, pod memory, and inference tokens, so it belongs in a foundation kit beside the
shape and pricing kits rather than being rebuilt per domain.

The interface matters more than the first implementation. A static minimum and maximum
per dimension is a box, but a seller's real policy can couple dimensions — at most
64 GiB of memory per GPU requested — and buyer and seller are expected to negotiate
dimensions with counter-proposals. An interface that returns unconditional bounds would make
either a rewrite of every caller; one that takes the whole shape and answers questions
about it makes them new implementations.

## What Changes

- A new foundation kit, `kit/capability-admissibility`, the only reader of a constraint:
  it splits a listing shape into its base shape and its constraints, parses the
  configured default, resolves labelled tiers into an opaque per-listing policy, and
  evaluates it with a whole-shape check returning structured problems and a query for
  the values one dimension may take given a partial shape, such that a counter-proposal
  can be built one dimension at a time without search. `min` and `max` are the only
  constraints. No operation gives a range for a dimension independent of the rest of
  the shape; the values one dimension may take are answered only for a given partial
  shape. A stated list is split as a whole, so a base shape stated twice with different
  constraints is found without a schema.
- Stated listing shapes — the pool's `listing_shapes` hint and a storefront override's
  `listing_shapes` — may give a quantity field `{offer, min, max}` in place of its
  scalar. A plain scalar is shorthand for an offer. An offer alone says nothing about
  negotiability. Unknown keys make the constraint unreadable, so later forms fail
  closed on older readers.
- A listing's constraints merge per field with the VM storefront's configured default,
  `[admissibility.defaults.vm]`, which adds values where the listing omits them and
  states no offer. An override that
  states shapes replaces the hint's list whole, as it does today.
- VM publication never advertises an inadmissible offer; a listing whose policy cannot
  be computed — unusable constraints, an empty range, or its base shape stated twice
  with different constraints — closes, alone, and is reported; a list with an unreadable
  base shape holds the pool, as today. The VM default generator generates only counts
  the configured default admits. Override writes and pool writes are checked, and both
  refuse a list that states one base shape with different constraints.

- Pilot merge reconciliation also corrects the provisioning integration harness
  to use independent database connections and makes relay-port allocation share
  fulfillment acceptance's transaction. A rejected preparation rolls back both
  its lease and its acceptance; validation acquires nothing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

Confirmed in planning (`tasks.md`, 7.10).

- `market-composition`: the admissibility kit's contract and the inline constraint form.
- `resource-pool-management`: listing-shape hint validation accepting constraints and
  refusing a base shape stated twice with different constraints.
- `storefront-publication`: listing shapes carrying constraints, per-listing resolution,
  publication and generator behavior, the override write check, and the reports.

- `fulfillment` and `physical-provisioning`: merge reconciliation fixes database
  isolation in the provisioning integration harness and makes relay allocation
  participate in fulfillment acceptance, so the port lease and prepared input
  commit or roll back together without nested write transactions.

## Non-Goals

- Occupancy-dependent bounds. A limit that depends on what is already rented is
  availability, owned by `negotiation-capacity-feasibility-probe` and site admission.
- Ratios, a requirement that a dimension be stated, and constraints keyed by attribute
  value. The form and interface admit coupled constraints; this change ships `min` and
  `max` only.
- Bare metal. A whole-machine listing negotiates no shape.
- A ceiling on what is provisioned per deal. Constraints govern the dimensions an agreed
  shape states; an omitted dimension is the site's.
- Site-enforced limits. Admissibility is the storefront's policy; site admission is
  unchanged.
- Selecting individual listings from an override.
- Pricing shapes (`capacity-shape-pricing`, archived) and categorical constraints.
- Negotiation wiring. `negotiation-driven-capacity-resize` composes admissibility first
  in the seller's round; this change records inputs to it.
- Disclosing constraints to buyers (`publish-shape-bounds`).

## Impact

- New distribution `kit/capability-admissibility` (`arkhai-kit-capability-admissibility`).
- `kit/resource-pools`: `listing_shapes` validation calls the kit's structural split on
  every pool-write surface.
- VM: `arkhai_vms` — the default generator takes the default-only policy, so the domain
  package depends on the kit; `arkhai_vms_listings` — stated shapes split through the
  kit, per-listing resolution, publication, identity over the base shape, and the
  derivation report; the VM storefront — the configured default, the override
  contribution's write check, and system status.
- Shape-admissibility behavior is unchanged in bare metal, `kit/pool-overrides`
  (an override's shapes are stored as today), site admission and the ledger,
  scheduling, fulfillment, pricing, the registry, and negotiation.
- Pilot merge corrections affect `kit/fulfillment`, `provisioning/compute`, both
  compute provisioning adapters, and the service integration fixtures. Bare
  metal accepts the shared session argument without acquiring any resource;
  its delivery semantics remain unchanged.
- Tests: kit unit tests against a synthetic schema and an import-boundary test; hint
  validation; per-listing resolution; VM publication and the generator; the override
  write check; one end-to-end run publishing from a pool whose stated shape carries
  constraints.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the foundation kit list; the
      test for whether a storefront holds or closes a listing it cannot fully derive,
      as a framework with brief examples; "Omission states no commitment"
      extended to an offer without a range; the VM listing shapes authority row;
      the durable fulfillment acceptance boundary for local resource claims.
- [x] Existing subsystem specification — provisional: `market-composition`,
      `resource-pool-management`, `storefront-publication`; the pilot merge
      corrections also affect `fulfillment` and `physical-provisioning`.
- [ ] New subsystem specification — none.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the inline constraint form and the
      configured default, `[admissibility.defaults.vm]`.

### Knowledge to promote

Confirmed in planning; `tasks.md` 7.10 names each file and heading.

- The admissibility contract: the kit is the only reader of a constraint; splitting,
  parsing, labelled resolution with per-form merge rules, and evaluation; whole shape
  in, structured problems out, never unconditional bounds; the base shape read before
  the constraints; the list-level split and conflicting duplicates;
  `admissible_values`, its invalid requests, and its one-dimension-at-a-time guarantee;
  the opaque value set; omitted dimensions are free; constraints intersect; unknown keys are unreadable; the inline
  form — `openspec/specs/market-composition/spec.md`.
- Why the interface is shaped for coupled declared constraints and counter-proposals,
  why occupancy is excluded, why constraints sit inline on the listing, and why a
  requirement that a dimension be stated is not a constraint —
  `openspec/specs/market-composition/architecture.md`.
- Listing-shape validation accepting constraints and refusing conflicting duplicates —
  `openspec/specs/resource-pool-management/spec.md`.
- Per-listing resolution with the configured default; the base shape read first, an
  unreadable base holding the pool; a listing whose policy cannot be computed, including
  a base shape stated twice with different constraints, closes alone; inadmissible
  offers are not published; the generator; the override check; identity over the base
  shape; the reports —
  `openspec/specs/storefront-publication/spec.md`.
- Admissibility is the storefront's policy and a site's constraint an advisory input;
  why constraints close where pricing holds —
  `openspec/specs/storefront-publication/architecture.md`.
- The foundation kit; the test for whether a storefront holds or closes a listing it
  cannot fully derive, as a framework with brief examples (pricing and an unreadable
  shape list hold, uncomputable admissibility closes), each term's own rule staying in
  `storefront-publication`; an offer without a range commits nothing about
  negotiability — `docs/development/ARCHITECTURE.md`.
- The inline form and the configured default — `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- The negotiation invariant and the omitted-dimension policy —
  `negotiation-driven-capacity-resize`'s own deltas; not promoted by this change.

- Pilot merge corrections, already promoted: local resource claims share the
  acceptance session and roll back with rejected preparation —
  `openspec/specs/fulfillment/spec.md`,
  `openspec/specs/fulfillment/architecture.md`, and
  `docs/development/ARCHITECTURE.md`; relay allocation joins that transaction
  and never reassigns an active lease after a stale scan —
  `openspec/specs/physical-provisioning/spec.md`. Section 6A in `tasks.md` records
  the completed corrections and remaining validation.

## Dependencies and Related Changes

- No prerequisites; closes out on its publication callers alone.
- Consumed by `negotiation-driven-capacity-resize`, whose seller round evaluates
  admissibility first; `design.md` records the inputs it takes.
- Complements `negotiation-capacity-feasibility-probe`: admissibility asks whether the
  seller would sell a shape, the probe whether the site can serve it now.
- `publish-shape-bounds` discloses each listing's resolved constraints to buyers in this
  change's inline form and depends on this change.
