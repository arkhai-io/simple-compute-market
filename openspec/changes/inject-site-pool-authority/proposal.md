## Why

`docs/development/ARCHITECTURE.md`'s kit layers place `kit/site` and
`kit/resource-pools` side by side as authority capabilities that depend on
foundation capabilities only. The code does not match. `kit/site` declares
`arkhai-kit-resource-pools` as a dependency, and `market_site/ledger.py` imports
`ResourcePool`, `DEFAULT_POOL_ID`, `HostRequirement`, `pool_delivers_offering_mode`,
and `pool_needs_host`, using them for four jobs inside its own database session:

1. **Admission** reads the pool row to check that it is enabled and that it
   declares the requested offering mode.
2. **Registration** reads the pool row to refuse a capacity declaration naming an
   unknown pool.
3. **Host requirement** reads the pool's provider and applies the injected
   `HostRequirement`, so admission and registration can refuse a declaration that
   names no host where the provider needs one.
4. **Legacy fallback** substitutes `DEFAULT_POOL_ID` wherever a capacity row's
   nullable `pool_id` is empty.

Nothing checks the rule. `kit/site`'s import-boundary test forbids lifecycle,
executor, and domain imports but not the pool kit, so the edge has grown one read
at a time without any change deciding to accept it. The unknown-pool check was
added by `capacity-resource-administration`, which recorded the conflict rather
than widen its scope; `pool-declared-advertisement-and-backing` held it as an open
question and handed it here.

The coupling has a concrete cost beyond the diagram. The API-credits service
administers no pools, yet it creates the `resource_pools` table and seeds a
`default` row only because the site ledger it runs reads one, and that row now
has to be migrated and verified like an administered pool.

## What Changes

- `kit/site` defines a pool-facts port: a small protocol the ledger receives at
  construction, whose operations take the caller's session and return plain
  values — whether a pool exists, whether it delivers an offering mode, and
  whether it needs a host. The injected `HostRequirement` folds into the port.
- `kit/resource-pools` supplies the SQLAlchemy implementation. It satisfies the
  protocol structurally and imports nothing from `kit/site`.
- Composition roots wire the implementation into every ledger they construct:
  the provisioning service and the API-credits service.
- The capacity row's `pool_id` becomes non-null, with a migration backfilling the
  system `default` pool in every service that stores site capacity, so the ledger
  no longer needs `DEFAULT_POOL_ID` or any fallback.
- `kit/site`'s import-boundary test forbids `market_resource_pools`, the pool
  kit's forbids `market_site`, and `kit/site/pyproject.toml` drops the dependency.
  The boundary test is the acceptance criterion: the rule holds because a test
  fails when it does not.

## Capabilities

### Modified Capabilities

- `site-capacity`: admission and registration read pool facts through an injected
  authority rather than the pool kit's persistence model.
- `resource-pool-management`: supplies the pool-facts implementation and the
  session-scoped reads it needs.

### New Capabilities

None.

## Non-Goals

- No change to what admission, registration, or the host requirement decide. Every
  refusal stays identical; only where the facts come from changes.
- No new pool fact. In particular, backing is not read at admission; an unbacked
  pool stays out of admission through its empty deliverable set. A future change
  that must refuse on backing adds that read through this port.
- No change to `kit/fulfillment`, which may depend on both authorities by design.

## Impact

- Affected code: `kit/site` (ledger, boundary test, packaging),
  `kit/resource-pools` (the implementation and its boundary test), the two service
  containers that construct a ledger, the capacity-row migration in each service,
  and every test that constructs `CapacityLedgerService` — 26 files today.
- Affected packaging: `kit/site` loses an internal dependency, so every `reinit`
  and lock that installs it is rechecked with `make check-reinit`.
- Affected documentation: `docs/development/ARCHITECTURE.md`'s kit layers stop
  needing an exception once the code matches them.

## Dependencies and Related Changes

- No blocking dependency.
- Should land before any change adds a new pool read to the site ledger. The
  concrete trigger is `pool-declared-advertisement-and-backing`'s revisit
  condition: admission refusing an unbacked pool on its backing rather than its
  empty deliverable set would be a fifth read, and belongs behind this port.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the kit-layer exception recorded
      while this change is open is removed once the code satisfies the diagram.
- [x] Existing subsystem specification — `openspec/specs/site-capacity/spec.md`
      for the injected authority and the non-null pool identity;
      `openspec/specs/resource-pool-management/spec.md` for the implementation.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The site ledger obtains pool facts only through an injected, session-scoped
  authority — `openspec/specs/site-capacity/spec.md`.
- A capacity row always names its pool; nothing defaults it —
  `openspec/specs/site-capacity/spec.md`.
