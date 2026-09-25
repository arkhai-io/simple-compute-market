## Why

A Resource Pool declares which offering modes its listings may advertise, whether it
is capacity-backed, and whether it is enabled. VM publication reads all three from
each site's resource-pool projection through `market_resource_pools`'s site
declaration reader. Bare-metal publication reads none of them. Its candidates come
from the site ledger's capacity snapshot, gated only by each resource's
`bare_metal_publication.enabled` attribute
(`arkhai_bare_metal_storefront.publication_cli._projections`).

So a Physical Resource in a pool that does not authorize `bare_metal`, or in a
disabled pool, can be listed. Site admission rechecks delivery at reservation, so
nothing is over-delivered, but buyers can discover a listing that can never settle.
The rule that a listing advertises only a mode its pool authorizes holds for VM and
not for bare metal; the permanent requirement states that exemption explicitly.

Bare-metal publication also diverges from VM in ways that lose or misstate state:

- **An unreachable site delists its listings.** The aggregate capacity client omits a
  site whose snapshot fails, the command treats the site as present and empty, and
  every open listing there closes. The next successful run reopens them.
- **Registries are told first.** A new listing is published to the registry and then
  written locally, and closes go to the registry before the local listing. A registry
  publish followed by a failed local write leaves a registry listing the storefront has
  no record of, which nothing will ever close. Only in-place refreshes write locally
  first.
- **Nothing converges.** No per-registry outcome is recorded, so a registry that
  misses an update is never repaired.
- **The command builds its own view of each machine** from a publication configuration
  attribute, rather than using the view the site projects from the capacity declaration
  — the one admission accounts against.
- **Each listing is tracked under two keys** that disagree when a Physical Resource
  moves to another pool.

Bare metal is Goal 7's primary target domain, and every later bare-metal change on
that goal's path needs its publication to read projected pool declarations through
the same mechanisms as VM.

## What Changes

- Derive bare-metal publication candidates from each trusted site's resource-pool
  projection and its `bare_metal.v2` publication views, as VM derives from the same
  projection. Stop reading the capacity snapshot for publication.
- Resolve every candidate's pool through `read_site_declarations`, under the same joint
  per-generation rule VM uses. A pool that does not advertise `bare_metal`, or is
  disabled, yields no listing and its existing listings close as a withdrawn source; an
  unresolvable pool holds its listings.
- Keep every bare-metal listing capacity-backed. A pool declaring itself unbacked yields
  no bare-metal listing, and the refusal is reported to the operator.
- Hold a site whose projection cannot be fetched: its listings are neither closed nor
  refreshed, and the run reports it.
- Publish, reconcile, and converge through `kit/capacity-publication`'s
  `PublicationRuntime`, recording each registry outcome in the storefront's per-registry
  publication records. Every listing is persisted locally, with its binding, before any
  registry is told, and every run converges each registry on its listings' local status.
- Track listings by the common binding's derivation key and stop using
  `derived_bare_metal_listings` for publication, so a Physical Resource moved to another
  pool is an identity change.
- Keep availability-driven closes distinct from source withdrawal.
- Check each site's projection in the storefront's health check.
- Define "publication candidate" in `ARCHITECTURE.md`'s "One name per concept".

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: the advertisement requirement covers bare-metal listings,
  with its exemption removed; an unbacked pool yields no bare-metal listing; a held
  site holds bare-metal listings; registry convergence covers bare-metal publication,
  and every publishing domain records a new listing locally before telling a registry.

## Non-Goals

- Unbacked bare-metal listings, owned by `unbacked-bare-metal-listings`, which removes
  this change's refusal of unbacked pools.
- A capability shape per bare-metal listing, owned by `bare-metal-listing-shapes`.
- Making bare-metal publication autonomous; it stays operator-invoked.
- Changing site admission or any delivery recheck.
- Removing or changing the site's capacity snapshot, which remains the site's live
  availability view for VM, API credits, and placement ranking.
- Dropping `derived_bare_metal_listings`; it is left in place and unread.

## Impact

- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`: the publication
  command, runtime health check, SQLite client status count, and a
  `arkhai-kit-resource-pools` and `arkhai-kit-capacity-publication` dependency of the
  storefront rather than of the domain package, which buyers and provisioning adapters
  install without the storefront extra.
- `domains/bare_metal/src/arkhai_bare_metal/`: candidate derivation from the projection
  view, and retirement of the storefront-side view construction and domain-table
  tracking.
- `openspec/specs/storefront-publication/spec.md` and `docs/development/ARCHITECTURE.md`.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "publication candidate" in "One name per
      concept", added during design because it defines a term already in use; and the
      capacity-publication section's description of bare-metal publication, re-confirmed
      at implementation.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A listing advertises only a mode its pool authorizes, for bare metal as for VM —
  `openspec/specs/storefront-publication/spec.md`.
- An unbacked pool yields no bare-metal listing —
  `openspec/specs/storefront-publication/spec.md`.
- A held site holds bare-metal listings —
  `openspec/specs/storefront-publication/spec.md`.
- Registry convergence covers bare-metal publication, and a new listing is recorded
  locally before any registry is told — `openspec/specs/storefront-publication/spec.md`.
- Why bare metal derives from the projection rather than the capacity snapshot, and why
  its listings are tracked by the common binding —
  `openspec/specs/storefront-publication/architecture.md`.

## Dependencies

Starts after `unbacked-listing-publication`, which moved the declaration reader into
`kit/resource-pools` and promotes the advertisement requirement this change widens.

Blocks `bare-metal-listing-shapes`, `unbacked-bare-metal-listings`, and the bare-metal
half of `publish-indicative-listing-rates`, all of which need bare-metal publication to
read projected pool declarations and policy tags. Bare metal is Goal 7's primary target
domain, so this change is on that goal's critical path.
