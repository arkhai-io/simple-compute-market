# Unify the VM and bare-metal storefronts

## Why

Goal 3 is one storefront serving several compute-family domains, so that one pool of
hardware is offered as several form factors at once, with the site arbitrating
exclusivity between them. Its foundation is built and released: a storefront freezes a
registry of contributions at startup, every listing and negotiation carries an
immutable binding to one of them, every later phase resolves its contract from that
binding, accepted work is routed to its recorded site, and one image carries both
compute contributions. What the goal names is not built.

- **No storefront process serves two domains.** The VM storefront resolves the `vm`
  registration and builds VM services only
  (`domains/vms/storefront/src/market_storefront/server.py`, `build_vm_storefront_app`).
  Its negotiation runtime refuses a record bound to any other registration
  (`negotiation_runtime.py`), its publication loop builds the VM source alone
  (`publication_wiring.py`), and its migration chain holds no bare-metal table
  (`utils/migrations.py`).
- **Bare metal is sold by a storefront of its own.** It has its own executable, image,
  chart and Compose stack, its own routes, runtime and migration chain
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`;
  `helm/charts/bare-metal-storefront`).
- **No deployment sells one site's hardware in both form factors.** A provisioning
  service trusts one storefront principal and calls back one storefront, and the
  umbrella chart refuses a release that puts both compute storefronts on one
  provisioning service (`docs/development/ARCHITECTURE.md`, "Production and staging").
  The site's cross-mode accounting, which refuses a whole machine while a VM slice
  holds it and the reverse, is therefore reached only by tests of the ledger.
- **A storefront can register a mode it does not serve.** The VM lane's seller and the
  umbrella chart's default values register `bare_metal` beside `vm`. The process
  validates and reports the second registration and serves nothing of it.

No other change makes one process serve both. `kit-owned-storefront-shell` extracts
what every storefront duplicates and merges none of them, and
`bare-metal-and-credits-domain-stacks` works on bare metal's own storefront.

## What Changes

- **One storefront process serves every registration it is configured with.** A
  storefront registering `vm` and `bare_metal` publishes, negotiates, settles,
  delivers, recovers and tears down deals of both, each record handled by the
  registration its binding names (design D1).
- **There is one compute storefront executable.** Which domains it serves is
  configuration, and a bare-metal-only deployment is that program with one
  registration. The dedicated bare-metal storefront, its commands, image and chart go
  (D10).
- **Bare metal's own routes, runtime and server are deleted.** Tasks 4a.3 to 4a.6 of
  `bare-metal-and-credits-domain-stacks`, which would have moved those routes onto
  shared routes and reduced the runtime and server to adapters, move to this change
  and are met by deleting them (D11).
- **One site's hardware is sold in both form factors by one storefront.** A machine
  declared at a site as VM slices and as a whole host is listed both ways, and the
  site refuses whichever claim conflicts with what is held (D1, D2).
- **A lane proves it on every pipeline run.** One storefront process publishes a VM
  listing and a bare-metal listing from one site's hardware, completes a deal of each,
  and the site refuses the cross-mode conflict. That scenario is this change's
  acceptance and Goal 3's (D2).
- **A deployment of marketplace 0.4.0 has a path** from the dedicated bare-metal
  chart, its two-release topology and its database (D7).
- **One storefront over several sites is not part of it** (D3).

How a 0.4.0 bare-metal deployment upgrades, how one process holds two registrations,
how publication, persistence, configuration and the charts are composed, which lanes
run what, and the order against Goal 4's remaining extractions are open in the
design's "Open Questions".

## Capabilities

### Modified Capabilities

- `market-composition`: one compute-family storefront program serves every
  registration its frozen registry holds, and no bare-metal storefront executable
  remains.
- `deployment-state`: the compute storefront's image, chart, configuration and
  migration chain for one or more registrations; the dedicated bare-metal seller role
  is removed.
- `storefront-publication`: publication for every registration a process serves.
- `test-compatibility`: the one-storefront scenario and the lanes.

`.openspec.yaml` sets `skip_specs` until the design session settles the open
questions; the design's Q10 names the requirements to be modified.

### New Capabilities

None.

## Non-Goals

- One storefront over several sites, and the live proof of it. The code handles
  several sites per storefront and integration tests prove the routing; no deployment
  or lane runs it, and it is planned as a roadmap goal of its own (D3).
- Several storefronts on one site. A provisioning service still trusts and calls back
  one storefront.
- Extracting the storefront route set, executable assembly, health and system service
  into kit. That is `kit-owned-storefront-shell`'s. Which of the two changes lands
  first is the design's Q1 (D4).
- API credits, which is not a compute-family domain and keeps its own storefront (D9).
- A third compute-family domain.
- An end-to-end stage that restarts a storefront or a site, or makes a site
  unavailable. Those behaviours are proven at integration level (D5).
- Evidence from a real host or a GPU (D6).

## Dependencies and Related Changes

- **Recorded as depending on `kit-owned-storefront-shell`**, gating implementation.
  That is the default order; the order against that change and the two extractions
  that follow it, `kit-owned-listing-and-fulfillment-lifecycles` and
  `kit-owned-storefront-auth-and-persistence`, is settled in this change's design
  session (D4, Q1).
- **Takes tasks 4a.3 to 4a.6 from `bare-metal-and-credits-domain-stacks`** (D11): the
  bare-metal negotiate and listing routes, the reduction of its runtime and server,
  and the proof that its negotiation stages pass through shared routes. That change
  keeps its API-credit recomposition, its stack work and its buyer verification, and
  this change does not depend on it. Its deferred deployment shape is settled here:
  one process (D1, D10).
- `align-package-paths-with-layers` moves the compute storefront's composition to the
  home decided for it.
- **Builds on**, all archived: `storefront-domain-parameterization` and
  `multi-domain-storefront-composition` (the frozen registry, the bindings and
  record-bound resolution), `pool-declared-offering-modes` (the offering mode on every
  claim and pool), `pools-7-storefront-fulfillment-cutover` (selected-site fulfillment),
  `bare-metal-mock-provisioned-deal` (bare metal on the kit negotiation runtime, its
  mock executor and its pipeline deal), `kit-owned-storefront-loop-lifecycle` (one loop
  controller per process), `share-site-projection-state` (one domain-neutral projection
  state per process), `unify-compute-delivery-path` (one delivery path for both
  domains) and `add-database-migration-commands` (the migration chains and their
  floor).

## Impact

The compute storefront's composition root; `kit/storefront` (what a composition is
given); `core/storefront` (publication source construction); the VM contribution
(`domains/vms/storefront`); `domains/bare_metal/storefront`, which keeps its
contribution and loses its routes, runtime, server and commands; both migration
chains; `helm/charts/storefront` and the umbrella chart;
`helm/charts/bare-metal-storefront` and the `bare-metal-storefront` image, which go;
the Compose stacks and lane overlays; the end-to-end harness; the seller command
line; `docs/operator-handbook.md`, `docs/release-handbook.md`,
`docs/seller-quickstart.md`, `docs/bare-metal-seller-quickstart.md`,
`docs/development/ARCHITECTURE.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md` and
`docs/development/TESTING.md`. Compute provisioning, the site authority and the
registry are not changed.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag (D7).

- **Behaviour.** A storefront configured with `vm` alone behaves as it does under
  0.4.0. A storefront configured with `vm` and `bare_metal` serves both, where a 0.4.0
  storefront so configured serves VM alone.
- **Deployment.** 0.4.0 ships `helm/charts/bare-metal-storefront`, the
  `bare-metal-storefront` image and commands, and the two-release topology in which
  the bare-metal storefront runs beside its own provisioning service. The chart, the
  image and the commands go (D10); two releases remain possible as two compute
  storefronts. What an operator of that topology does to upgrade, and whether one
  release keeps the old chart while they do, is the design's Q2.
- **Persistence.** A 0.4.0 VM storefront database and a 0.4.0 bare-metal storefront
  database each record their own migration chain. What chain the compute storefront
  declares, and what it does with either database, is the design's Q5. No deal a 0.4.0
  storefront accepted is reinterpreted under another registration: its binding is
  immutable.
- **Wire.** No route's path, model or authentication is settled to change. The routes
  only bare metal serves today, the buyer's fulfillment reads among them, are served
  by the compute storefront for bare-metal records.
- **Configuration.** `[[storefront_domains]]` keeps its four keys and its meaning. A
  key a 0.4.0 storefront accepted keeps its meaning or is refused by name with its
  replacement; which keys move is the design's Q6.
- **The site and the registry.** Unchanged. A 0.4.0 provisioning service serves the
  compute storefront as it serves a 0.4.0 one.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`: "Capacity publication and multi-domain
  storefront composition", "Local development" and "Production and staging".
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/market-composition/spec.md` and its companion;
  `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain
  storefront composition" and "Production and staging";
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition" and
  "Release topology".
- D2: `docs/development/ROADMAP.md`, Goal 3, whose "Done when" it is;
  `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`,
  "System Integration Tests (End-to-End)".
- D3: `docs/development/ROADMAP.md`, Goal 3; `docs/development/ARCHITECTURE.md`,
  "Site authority" and "Production and staging".
- D4: no permanent destination — it says where an order between two open changes is
  decided, which the change index records while both are open.
- D5: `openspec/specs/market-composition/testing.md`, "Multi-Domain Storefront
  Composition".
- D6: no permanent destination — the lane scenario's mock provisioning is stated where
  the scenario is described, under D2.
- D7: `docs/operator-handbook.md`, "Upgrading a deployment";
  `openspec/specs/deployment-state/spec.md`.
- D8: no permanent destination — `docs/development/ARCHITECTURE.md`, "One name per
  concept", already states it.
- D9: `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain
  storefront composition".
- D10: `openspec/specs/market-composition/spec.md` and its companion;
  `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`,
  "Local development" and "Production and staging";
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D11: `docs/development/ROADMAP.md`, Goals 3 and 4.
