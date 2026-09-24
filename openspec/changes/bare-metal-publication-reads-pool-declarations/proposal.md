## Why

A Resource Pool declares which offering modes its listings may advertise, whether it
is capacity-backed, and whether it is enabled. VM publication reads all three from
each site's resource-pool projection through `market_resource_pools`'s site
declaration reader. Bare-metal publication reads none of them. Its candidates come
from the site's capacity snapshot, gated only by each resource's
`bare_metal_publication.enabled` attribute
(`arkhai_bare_metal_storefront.publication_cli._projections`).

So a Physical Resource in a pool that does not authorize `bare_metal`, or in a
disabled pool, can be listed. Site admission rechecks delivery at reservation, so
nothing is over-delivered, but buyers can discover a listing that can never settle.
The rule that a listing advertises only a mode its pool authorizes holds for VM and
not for bare metal.

Bare metal also misses the registry convergence VM and API credits have. Its operator
command updates its one registry through `SyncRegistryClient` after changing the
local listing, and keeps no per-registry publication records. A registry update that
fails after the local change is not resent by a rerun, because the local listing has
already moved, so the registry stays diverged from the storefront.

## What Changes

- Bare-metal publication loads each trusted site's resource-pool projection and
  resolves every candidate's pool through `read_site_declarations`, the reader VM
  uses, under the same joint per-generation rule.
- A candidate whose pool does not advertise `bare_metal`, or whose pool is disabled,
  yields no listing; one whose pool is unresolvable is held, neither published,
  closed, nor refreshed.
- Every bare-metal listing stays capacity-backed. A pool declaring itself unbacked
  yields no bare-metal listing, because bare metal publishes nothing an admission
  authority does not stand behind; the refusal is reported to the operator.
- Existing listings whose pool no longer authorizes them close through bare metal's
  source reconciliation as a withdrawn source does.
- Bare-metal publication records each registry outcome in the storefront's
  per-registry publication records and converges every registry on its listing's
  local status on each run, as the VM and API-credit storefronts do through
  `PublicationRuntime.converge`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the advertisement rule covers bare-metal listings as well
  as listings derived from the resource-pool projection, and registry convergence
  covers bare-metal publication.

## Non-Goals

- Unbacked bare-metal listings.
- Making bare-metal publication autonomous; it stays operator-invoked.
- Changing site admission or any delivery recheck.

## Impact

- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py`
  and the storefront's site clients: a resource-pool projection read per trusted site.
- `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py` and
  `publication.py`: candidate filtering and holds.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py`:
  registry outcomes recorded and a convergence step per run.
- `domains/bare_metal/storefront/pyproject.toml`: `arkhai-kit-resource-pools` becomes
  a dependency of the storefront, not of the domain package, which buyers and
  provisioning adapters install without the storefront extra.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The advertisement requirement in `openspec/specs/storefront-publication/spec.md`
  widens from listings derived from the resource-pool projection to every
  compute-family listing derived from a Resource Pool.
- The registry-convergence requirement names bare-metal publication among the
  passes that converge.

## Dependencies

Starts after `unbacked-listing-publication`, which moved the declaration reader into
`kit/resource-pools` and promotes the advertisement requirement this change widens.
