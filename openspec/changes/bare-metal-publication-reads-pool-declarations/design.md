# Design — bare-metal publication reads pool declarations

## Context

Found while `unbacked-listing-publication` moved the site-generation declaration
reader out of the VM domain and into `kit/resource-pools`. Fixing it there would have
added a resource-pool projection read to a domain that change otherwise touched only
for backing disclosure and the durable seller close, late in a large change. It was
recorded and split out here instead.

Bare metal is Goal 7's primary target domain, and this change is the first on that
goal's critical path: `bare-metal-listing-shapes`, `unbacked-bare-metal-listings`, and
the bare-metal half of `publish-indicative-listing-rates` all need bare-metal
publication to read projected pool declarations through the same mechanisms as VM.

What bare-metal publication does today, from
`arkhai_bare_metal_storefront.publication_cli`:

- **Candidates come from the site ledger's capacity snapshot.** `_projections` calls
  the aggregate capacity client's `snapshot()`, keeps rows whose
  `attributes.bare_metal_publication.enabled` is set, and builds each resource's
  bare-metal view itself, taking `host_id`, `physical_host_id`, and `allocation_mode`
  from that publication attribute and recomputing whole-resource availability.
- **An unreachable site delists its listings.** The aggregate client omits a site
  whose snapshot fails. `_projections` seeds every trusted site with an empty list
  marked complete, under a hard-coded revision, and `stale_open_bare_metal_listing_ids`
  then closes every open listing at the missing site. The next successful run reopens
  them.
- **Registries are told first for new listings and closes.** A new listing is
  published to the registry and then written locally; a stale or diverged listing is
  closed at the registry and then locally. A registry publish that succeeds followed
  by a failed local write leaves a registry listing the storefront has no record of,
  which nothing will ever close. Only in-place refreshes write locally first.
- **Nothing records registry outcomes.** The storefront's per-registry `publications`
  records, which VM and API credits converge from, are never written.
- **Listings are tracked twice.** `derived_bare_metal_listings` keys each listing on
  site and Physical Resource; the common `StorefrontListingBinding` every bare-metal
  listing also carries keys on site, offering mode, domain binding, pool, and Physical
  Resource. A Physical Resource moved to another pool is found by the first key and
  refreshed in place — `pool_id` is not a published identity field — while its binding
  still records the old pool.
- **The storefront's health check cannot see a down site.** It calls the aggregate
  `snapshot()`, which swallows per-site failures, and reports `site_projection: ok`.

## Decisions

### Candidates come from the resource-pool projection, not the capacity snapshot

Bare-metal publication fetches each trusted site's resource-pool projection
(`resource_pool_projection()`) and derives one publication candidate per Physical
Resource carrying a `bare_metal.v2` publication view, from the view the site already
projects. The capacity-snapshot read and the storefront's own view construction are
removed.

This is how VM publication works, and it is forced by the declaration reader:
`read_site_declarations` resolves one site generation's pool list, so reading
declarations already means fetching the projection. Within one generation, a
resource's pool, that pool's declarations, and the resource's publication view come
from one document and cannot disagree — which dissolves the question this design
previously left open, whether to join a snapshot to a projection.

The site's own view is also the correct one. The provisioning service builds it from
the capacity declaration — `host_id` from the declaration, `physical_host_id` and
`allocation_mode` from the declaration's attributes the ledger's cross-mode rule
reads — so it cannot name a different machine than admission accounts for. The
storefront's copy takes those values from the publication configuration attribute
instead, and duplicates the provisioning service's whole-resource availability
check. The parser for the site's view, `trusted_bare_metal_projection`, already exists
and has no production caller.

**Availability is not lost.** The projection's inventory is built from the ledger's
resource list — the same rows `GET /api/v1/capacity/snapshot` filters to enabled
resources — so each fetched view's `available` flag reflects live ledger state at
fetch time. Bare metal fetches fresh on every run and caches nothing between runs.

**The capacity snapshot itself stays.** It is the site authority's live availability
view, not a legacy surface: VM publication, failure actions, the listing source check,
and the admin availability endpoint read it; API-credit listing, fulfillment, and
negotiation read it; and the storefront's placement ranking reads it per request.
`pools-9-retire-local-physical-authority` does not touch it. This change removes only
bare-metal publication's use of it, and the health check's (below).

### A site whose projection cannot be fetched holds its listings

A trusted site whose projection fetch fails in a run is unknown for that run, not
empty: its listings are neither closed nor refreshed, no candidate is derived from it,
and the run reports it. Every other site is reconciled as usual. This brings bare metal
under "A site whose projection is not held holds its listings", which applies to every
storefront deriving from site projections, and removes the delisting defect above.

Per-site fetches are made directly against each site's client, not through the
aggregate client, whose best-effort `snapshot()` cannot distinguish a failed site from
an empty one.

### Read the declarations through the kit reader, not a bare-metal copy

The joint per-generation rule, the older-producer reading, and enablement are not
specific to an offering mode; that is why the reader lives in the kit. Bare metal asks
`ResolvedPool.advertises("bare_metal")` and `.enabled`, and applies nothing of its own.
A pool that does not advertise `bare_metal`, or is disabled, yields no candidate; its
existing listings close as a withdrawn source.

### A pool read fails closed per pool, as VM's does

An unresolvable pool holds its listings rather than closing them, because an unknown
declaration is not a withdrawn one.

### An unbacked pool yields no bare-metal listing

Every bare-metal listing is published as `capacity_backing: backed`, and its binding
writers record `backed`. A pool declaring itself unbacked could only yield a listing
whose published backing contradicts its pool, so it yields none, with an operator
notice naming the pool. Unbacked bare metal is owned by `unbacked-bare-metal-listings`,
which removes this requirement once bare metal can publish a listing with no admission
authority behind it.

### Bare metal adopts the kit publication runtime

VM and API credits publish through `kit/capacity-publication`'s `PublicationRuntime`.
Bare metal adopts it rather than calling the core registry-publication helpers
directly, so the compute-family domains publish, reconcile, and converge through one
implementation. The direction is that both domains use the same kit mechanisms by the
time Goal 7 is complete, and `unbacked-bare-metal-listings` needs the runtime's
unbacked binding and backing-scoped reconciliation, which the core helpers do not
provide.

What adoption needs is mostly present. The bare-metal `SQLiteClient` extends the core
client, which already implements every repository method the runtime calls —
`update_listing`, `load_listing`, `load_publications`, `list_publication_divergence`,
`upsert_publication`. Every bare-metal listing already carries a common binding from
which the runtime's `binding_for_listing` hook can build a `CapacityBinding`, as VM's
does. Registry fan-out goes through the core `MultiRegistryClient` VM uses; the
bare-metal storefront's one configured registry is a fan-out of one.

The runtime persists a listing and its binding before telling any registry, closes and
reopens locally before telling any registry, and records every registry outcome. That
removes the registry-first ordering above, including the orphaned registry listing,
and is stated normatively in the convergence requirement this change modifies.

The cost is moving bare-metal publication onto the kit's candidate and binding types
and running the command as one asynchronous pass instead of repeated synchronous
calls, which this change accepts.

### Listings are tracked by the common binding, so a pool move is an identity change

Bare-metal publication looks up an existing listing by the common binding's derivation
key (`load_listing_binding_by_derivation`, as VM's publication loop does) and stops
reading and writing `derived_bare_metal_listings`. `count_open_bare_metal_resources`,
the one other reader, moves to the common bindings too.

VM made the same move when publication stopped using `derived_compute_listings`. One
key per listing removes the case where the two keys disagree. Because the common key
includes the pool, a Physical Resource moved to another pool derives a new listing
under the new pool's binding and the old listing closes as a withdrawn source — the
reading "the supply it draws from (site, and pool or Physical Resource)" in the
listing-identity requirement gives, and the one under which advertisement is
authorized by the pool the binding records.

The core `listing_id_for_derivation_key` is not used; it raises whenever reached (an
unowned item in the campaign index).

**Deferred.** The table itself is left in place and unread, because schema changes
are additive and a drop is a contract step. Dropping it has no owner yet.

### Availability closes stay distinguishable from source withdrawal

A bare-metal listing whose machine is leased closes, and reopens when the machine is
free. For a capacity-backed listing that is capacity-availability reconciliation, which
the specification permits for backed listings only. Today it is implemented as source
staleness: an unavailable resource yields no candidate and its listing looks stale.

Under the runtime the two stay separate: a withdrawn or disabled source and an
unavailable resource produce distinct plan entries. Behaviour for backed listings is
unchanged; the separation is what lets `unbacked-bare-metal-listings` apply
availability to backed listings only, as "Source publication and capacity availability
reconcile separately" requires.

### Registry convergence reuses the storefront's publication records

VM and API credits converge through `PublicationRuntime.converge`, which reads the
per-registry `publications` records and resends what each listing's local status
implies. Recording bare-metal registry outcomes in the same records lets bare metal use
the same divergence query and the same repair rule, on every run of the publication
command.

### The health check reads each site's projection

The storefront's readiness check fetches each trusted site's resource-pool projection
directly and reports each site's result, so a down site is visible rather than reported
as `ok` by the aggregate client's best-effort snapshot. It checks the surface
publication now depends on.

### "Publication candidate" gets one name

The term is used throughout `ARCHITECTURE.md` and the storefront-publication
specification without a definition, and `ARCHITECTURE.md` also used "candidate" for pool
members and scheduling. It is added to `ARCHITECTURE.md`'s "One name per concept":
one listing a publication pass could publish, derived from a source declaration before
anything is decided about it. The Resource Pools section's "physical settlement
candidates" is reworded to avoid the collision; a scheduling candidate — a resource
considered for placement — is a different concept and keeps its ordinary meaning.

## Open questions

- **Listings bound before the common key included the pool.** Every bare-metal listing
  carries a common binding, but not all under the same key. Listings created by the
  current publication path are bound under the common derivation key, which includes
  the pool. Listings that predate common bindings were moved under them by
  `_migrate_common_domain_bindings`, which recorded `pool_id` as null and kept the
  domain table's key — site and Physical Resource only. Bindings are immutable, so
  those rows cannot be re-keyed, and a lookup by the common key does not find them.
  Two ways to proceed:
  - **Fail forward once**, as VM's upgrade to listing shapes did: on the first run
    each such listing closes as a withdrawn source and its successor publishes under
    the common key, with a seller's close and pause carried to the successor so no
    seller decision is lost. After that, one key describes every listing.
  - **Fall back to the legacy key on a miss**, read-only: a legacy listing keeps its
    identity and is reconciled in place. It keeps no recorded pool, so a pool move
    cannot be detected for it, and the second key this change otherwise removes
    persists for as long as any such listing does.

  Task 1.1 is the decision gate.

## Migration

Listings bound under the common key keep their identities: the first run after upgrade
finds each and reconciles it in place. Listings bound before the key included the pool
follow the open question above.

Existing listings have no `publications` records. The first run records each registry
outcome it produces. A listing the run does not change produces no registry call and
gains no record, and the divergence query reads only recorded outcomes, so it is not
treated as diverged. The accepted consequence: a registry already out of step with a
listing at upgrade — a close that failed under the old ordering, say — stays out of step
until that listing next changes.

A listing whose pool no longer advertises `bare_metal`, or whose Physical Resource moved
pools, closes on the first run — the intended correction, not a regression.
