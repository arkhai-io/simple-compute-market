## Why

`docs/development/ARCHITECTURE.md`'s kit areas place `kit/site` and
`kit/resource-pools` side by side as authority capabilities that depend on
foundation capabilities only. The code does not match. `kit/site` declares
`arkhai-kit-resource-pools` and `arkhai-kit-resource-pools-contracts`, and
`market_site/ledger.py` reads `ResourcePool` rows inside its own database session for
four facts:

1. **Existence**, at registration, refusing a declaration naming an unknown pool.
2. **Enabled and delivers the requested offering mode**, at probe, reserve, resize and
   the rebind recheck.
3. **The pool's provider**, which the ledger applies with its injected
   `HostRequirement` through `declaration_has_usable_host`.
4. **Whether the pool declares any deliverable mode**, in the offered read every
   projection is built from.

It also imports `DeliverableHosts`, `HostRequirement` and `declaration_has_usable_host`
from the pool authority. Nothing checks the rule: both kits have empty scope and the
edge forms no cycle, so `make check-architecture` cannot see it, and `kit/site` has no
boundary test of its own. The edge has grown one read at a time without any change
deciding to accept it, and `ARCHITECTURE.md` asks that no new site read of pool state be
added while it stands. The next one is planned: `renewable-compute-lease-deadlines`
reads the pool's effective delivery deadline at commit.

Beside it, two read-only modules stayed in the authority when its contracts package
was split out — `site_declarations.py` and `asking_rates.py` — so every reader of a
site's pool declarations installs the authority, SQLAlchemy and PyYAML for functions
that import neither. `docs/guidance/repository/package-layers.md` records both
divergences against this change.

## What Changes

- `kit/site` defines a session-scoped pool-facts port, `PoolFactsReader`, whose one
  operation returns a structural `PoolFacts` value — whether the pool exists, whether it
  is enabled, its deliverable offering modes, and whether its declarations need a host.
  The ledger requires it at construction and loses its `host_requirement` argument.
- `kit/resource-pools` implements the port with `ResourcePoolFacts`, which resolves the
  composition's `HostRequirement` into `needs_host` and imports nothing from `kit/site`.
- `kit/site` owns the `DeliverableHosts` protocol and the usable-host predicate, which
  takes the pool's need for a host as a boolean; `kit/fulfillment` and the compute relay
  report take them from `market_site`. `kit/resource-pools` keeps `HostRequirement` and
  `pool_needs_host`.
- Both composition roots — the provisioning service and the API-credit service — wire
  `ResourcePoolFacts` into their ledger.
- `site_declarations.py` and `asking_rates.py` move into `kit/resource-pools-contracts`;
  the VM, bare-metal and API-credit storefronts and `arkhai_vms_listings` import them
  from there and drop the authority from their runtime dependencies.
- `kit/site/pyproject.toml` drops both pool distributions. `kit/site`'s boundary test
  forbids both, and `kit/resource-pools`' forbids `market_site`.
- `ARCHITECTURE.md` stops describing the pool authority as compute-family knowledge: it
  is provider-neutral and stays a repository-wide kit.

## Capabilities

### Modified Capabilities

- `site-capacity`: the site authority reads pool facts through an injected,
  session-scoped port and imports nothing from the pool capability.
- `resource-pool-management`: the pool authority answers that port; the declaration
  and asking-rate readers live in the thin contracts distribution.

### New Capabilities

None.

## Non-Goals

- No change to what admission, registration, the host requirement, or the offered read
  decide. Every refusal and every projected `enabled` stays identical; only where the
  facts come from changes.
- No new pool fact. Backing is not read at admission; an unbacked pool stays out of
  admission through its empty deliverable set. The delivery deadline is
  `renewable-compute-lease-deadlines`' to add through this port.
- No schema change. `capacity_buckets.pool_id` stays nullable; a stored declaration with
  no pool already belongs to no pool, as `site-capacity` requires.
- No change to API credits' pool storage, seed, or projection.
- No change to what `kit/fulfillment` depends on: it may depend on both authorities by
  design.

## Impact

- Affected code: `kit/site` (the ledger, two new modules, its boundary test, its
  packaging, its tests), `kit/resource-pools` (the port's implementation, the narrowed
  host-requirement module, its boundary test, the two modules leaving it),
  `kit/resource-pools-contracts` (the two modules arriving), `kit/fulfillment`'s
  scheduler and scheduling persistence imports, `compute_provisioning`'s relay
  deliverability import, the provisioning service's and the API-credit service's
  composition roots, the four reader packages, and the 19 test files and one example
  that construct `CapacityLedgerService`.
- Affected packaging: `kit/site` loses two internal dependencies and four reader
  packages lose one, so every lock installing them is rechecked with
  `make check-packaging`. Each consumer of a moved import raises its lower bound to the
  first version exporting it (design D11).
- Wire, persistence and deployed compatibility: none. Deployment record read:
  `marketplace-v0.4.0`.

## Dependencies and Related Changes

- No blocking dependency.
- `renewable-compute-lease-deadlines` depends on this change for the port, and adds the
  delivery deadline to it as a `PoolFacts` member and a `StoredPoolFacts` field.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the kit-areas paragraph on the `kit/site`
      edge is removed, the pool authority is described as provider-neutral, the
      contracts paragraph names the two readers, and "Resource pools" says where the
      host requirement and the report live.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/` (spec,
      companion, `testing.md`) and `openspec/specs/resource-pool-management/` (spec and
      companion).
- [ ] New subsystem specification
- [ ] No permanent documentation change

Also `docs/guidance/repository/package-layers.md`, "Where the current tree diverges",
loses both pool divergences, and the two principles below are promoted to the
repository and engineering guidance.

### Knowledge to promote

- D1: the site's pool facts come through an injected port —
  `openspec/specs/site-capacity/spec.md` and its companion; and the principle that a
  kit-to-kit edge the kit-area order forbids is removed, by moving code or injecting a
  port, rather than sanctioned by amending the order —
  `docs/guidance/repository/package-layers.md`, "Where the current tree diverges".
- D2: the pool authority is provider-neutral and repository-wide —
  `docs/development/ARCHITECTURE.md`, "Kit areas", and the
  `resource-pool-management` companion, "Ownership boundary".
- D3: API credits composes the real reader with no host requirement — the
  `site-capacity` companion, "Declared capacity and connection identity".
- D4: the port's operation, its values, and the session it reads in —
  `openspec/specs/site-capacity/spec.md` and its companion; the implementation —
  `openspec/specs/resource-pool-management/spec.md`; and the principle that a port a
  lower component defines is satisfied structurally, the values it returns included,
  so the implementing component never imports the port's owner —
  `docs/guidance/engineering/dependencies.md`.
- D5: the site owns `DeliverableHosts` and the usable-host predicate; the pool authority
  keeps the provider mapping — the `site-capacity` companion and `testing.md`, and
  `docs/development/ARCHITECTURE.md`, "Resource pools".
- D6: the declaration and asking-rate readers are in the contracts distribution —
  `openspec/specs/resource-pool-management/spec.md`, its companion, and
  `docs/development/ARCHITECTURE.md`, "Kit areas".
- D7: no permanent destination — the nullable column and the poolless-row rule are
  already `site-capacity`'s; this change only declines a migration.
- D8: no permanent destination — `DEFAULT_POOL_ID` does not move.
- D9: the ledger requires its reader, and `kit/site`'s tests use their own double — the
  `site-capacity` `testing.md`.
- D10: the two boundary tests — the `site-capacity` companion and the
  `resource-pool-management` companion, beside each kit's dependency boundary.
- D11: no permanent destination — the cadence governs this change's implementation.
