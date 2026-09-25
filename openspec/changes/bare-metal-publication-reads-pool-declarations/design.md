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

- **Candidates come from the site's capacity projection.** `_projections` calls the
  aggregate capacity client's `snapshot()` — the site's capacity projection, served at
  `GET /api/v1/capacity/snapshot` — keeps rows whose
  `attributes.bare_metal_publication.enabled` is set, and builds each resource's
  bare-metal view itself, taking `host_id`, `physical_host_id`, and `allocation_mode`
  from that publication attribute and recomputing whole-resource availability.
- **An unreachable site delists its listings.** The aggregate client omits a site
  whose capacity projection fetch fails. `_projections` seeds every trusted site with an empty list
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

### Candidates come from the resource-pool projection, not the capacity projection

Bare-metal publication fetches each trusted site's resource-pool projection
(`resource_pool_projection()`) and derives one publication candidate per Physical
Resource carrying a `bare_metal.v2` publication view, from the view the site already
projects. The capacity-projection read and the storefront's own view construction are
removed.

This is how VM publication works, and it is forced by the declaration reader:
`read_site_declarations` resolves one site generation's pool list, so reading
declarations already means fetching the projection. Within one generation, a
resource's pool, that pool's declarations, and the resource's publication view come
from one document, and the parser enforces that they agree (below) — which dissolves
the question this design
previously left open, whether to join the capacity projection to the resource-pool
projection.

The site's own view is also the correct one. The provisioning service builds it from
the capacity declaration — `host_id` from the declaration, `physical_host_id` and
`allocation_mode` from the declaration's attributes the ledger's cross-mode rule
reads — so it cannot name a different machine than admission accounts for. The
storefront's copy takes those values from the publication configuration attribute
instead, and duplicates the provisioning service's whole-resource availability
check. The parser for the site's view, `trusted_bare_metal_projection`, already exists
and has no production caller.

**Availability is not lost.** The projection's inventory is built from the ledger's
resource list — the same rows the capacity projection filters to enabled resources —
so each fetched view's `available` flag reflects live ledger state at
fetch time. Bare metal fetches fresh on every run and caches nothing between runs.

**The capacity projection itself stays.** It is the site authority's live
availability view, not a legacy surface: VM publication, failure actions, the listing source check,
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
aggregate client, whose best-effort capacity projection cannot distinguish a failed site from
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

**Adoption follows VM's shape.** The domain contract keeps registering its publication
source, because "Domain publication capability" requires the core runner to invoke a
domain source through that contract. What changes is behind the source's callbacks, as
in VM's publication cycle: a new listing is written locally with its binding and then
published through the runtime; a refresh or reopen writes locally and then goes through
the runtime's `publish` or `reopen`; closes go through the runtime's `reconcile`; and
every run ends with `converge`. The command runs as one asynchronous pass, bridging the
synchronous core runner the way VM's cycle does, instead of repeated synchronous calls.

**The domain package loses its database access.** Candidate derivation from a
projection and the listing comparison are pure and stay in `arkhai_bare_metal`; every
database read and write moves into the storefront package, as VM keeps its cycle in its
storefront rather than its domain package. The domain package then no longer imports the
core storefront's SQLite helpers.

**A bare-metal binding's source is its Physical Resource.** The runtime's
`binding_for_listing` hook builds `CapacityBinding(site_id, "bare_metal",
physical_resource_id)` from the listing's durable binding, refusing one not recorded as
backed. VM's helper uses the pool where a listing has one, because a fungible VM listing
draws from its pool; a bare-metal listing offers one specific Physical Resource, which is
the source the kit's binding describes for that case. The pool remains part of the
derivation key through the common binding.

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

The table is dropped by a new storefront migration, with every function that reads or
writes it. Schema changes are additive by default so a deployed database can cross
releases; bare metal is not yet deployed as a domain, so there is no deployed database
for an expand/contract sequence to protect, and leaving an unread table would only
preserve the second key this decision removes. A drop migration rather than a rewritten
migration history keeps any existing development database consistent with a fresh
one.

### Every resource falls into exactly one classification

A bare-metal listing whose machine is leased closes, and reopens when the machine is
free. For a capacity-backed listing that is capacity-availability reconciliation, which
the specification permits for backed listings only. A disabled or removed declaration is
different: "Source publication and capacity availability reconcile separately" makes it
source withdrawal, for backed and unbacked listings alike. Today both are implemented as
source staleness — an unavailable resource yields no candidate and its listing looks
stale — and the site's view cannot tell them apart, because the provisioning service
builds the view's `available` as the declaration's `enabled` and whole-resource
availability together.

So publication does not read enablement from the view. The projected resource that
contains each view carries the declaration's `enabled` separately, and the parser keeps
it beside the view. `BareMetalResourceProjection` is unchanged: it is also the
provisioning service's model for the view it produces, and a new required field there
would break the producer. Changing the producer so the view's `available` means
availability alone was the alternative; it changes the site's published view to spare
the consumer reading a flag it already has.

Every bare-metal resource in a fetched site then falls into exactly one class, and the
reconciliation plan is built from those disjoint classes:

| Class | Condition | Effect |
|---|---|---|
| Candidate | pool admits `bare_metal`; resource enabled; view present and available | published, refreshed, or reopened |
| Unavailable | pool admits `bare_metal`; resource enabled; view present, not available | its listing closes as `unavailable` |
| Held | pool's declarations do not resolve | its listing is neither closed nor refreshed |
| Withdrawn | anything else: resource disabled or absent, view absent, pool not admitting `bare_metal` | its listing closes as `source_gone` |

Disjointness is not only semantic. The runtime refuses a close plan naming one listing
twice, and without it an unavailable resource would qualify both as a missing candidate
and as unavailable. Behaviour for backed listings is otherwise unchanged; the separation
is what lets `unbacked-bare-metal-listings` apply availability to backed listings only.

### The containing pool is authoritative for a resource's pool

Within the resource-pool projection, a site's pools are entries of `resource_pools`,
each carrying its declarations and its resources, and a resource's bare-metal view
repeats the pool's identifier so the view is self-contained. Pool membership now decides
whether a resource may be published, so the two copies must not be allowed to disagree.

The parser takes the pool from the entry that contains the resource, read from that
entry's `pool_id`. A view carrying a
pool identifier must name that same pool exactly; otherwise the parser rejects the
site's whole generation, as it already does when a view names a different Physical
Resource than its container. For publication a rejected generation is an unknown site:
its listings are held and the run reports it. Today the parser prefers the view's copy,
which would let a malformed projection place a resource under a pool that does not
advertise `bare_metal` while its view names one that does.

### The site's projections name the pool `pool_id`

The pool's identifier is `pool_id` everywhere in this system except the site's two
projections, whose pool entries (resource-pool projection) and bucket rows
(capacity-bucket projection) call it `resource_pool_id`. That is two names for one
concept, against "One name per concept". This change renames the wire field to `pool_id`
in both projections, and every reader with it.

**One step, no transition.** The site emits only `pool_id`, and every reader reads only
`pool_id`. `openspec/specs/deployment-state/architecture.md`'s compatibility posture asks a
non-additive change for an explicit plan naming the period in which old and new readers
and writers coexist. This is that plan, and it deliberately has no expand phase.

- **The coexistence period** is a rollout: from the first site or storefront upgraded to the
  last. One operator deploys a storefront together with every site it talks to, so the
  period ends when that operator's rollout ends. The rollout itself is not atomic, because
  the provisioning service and each storefront are separate deployments.
- **What happens during it:** a storefront and a site on different versions do not share a
  pool field, so the storefront reads a loaded projection with no named pools. Its
  publication treats that site's pools as withdrawn and closes their listings; once both
  sides match, reconciliation reopens them under their original identities. A seller's close
  is untouched, and a pool-override write against a mismatched site is refused as naming no
  projected pool. The result is registry churn and a brief buyer-visible delisting, which is
  accepted. An operator who wants to avoid it can pause the VM storefront's lifecycle loops
  (`POST /api/v1/admin/lifecycle/pause`) and hold bare-metal publication for the rollout.
- **Rejected: emitting both spellings and reading either.** It removes the churn, but it adds
  a fallback to every reader and a later change to remove it, to shorten a window the
  maintainer accepts.

**Revisit trigger:** the first site operated independently of the storefronts that consume
it — the direction the multi-site roadmap goal takes. From then on the coexistence period
has no end any one operator controls, and a change to the projections' wire format needs
an expand phase.

### Registry convergence reuses the storefront's publication records

VM and API credits converge through `PublicationRuntime.converge`, which reads the
per-registry `publications` records and resends what each listing's local status
implies. Recording bare-metal registry outcomes in the same records lets bare metal use
the same divergence query and the same repair rule, on every run of the publication
command.

### The health check reports each site's projection, as VM's does

The permanent requirement "Per-site projection load-state visibility" makes each site's
projection state visible per site and forbids one site's failure from presenting as broad
storefront degradation while other sites are healthy. VM's health follows it: per-site state
appears only in `site_projections`, and nothing about a site's projection enters the gated
`checks`. Bare metal does the same.

- The readiness check fetches each trusted site's `resource_pool_projection_version()`
  through that site's own client — the version endpoint rather than the full projection,
  because `/health` is also the image's health check, probed every fifteen seconds, and the
  version endpoint returns exactly the revision and digest the status reports.
- `BareMetalHealthResponse` gains `site_projections`, keyed by site and then by projection
  family, using core's `ProjectionFamilyStatus` under the family name VM uses,
  `resource_pool`. A site that answers is `loaded`, with its revision, digest, and fetch
  time; one that does not is `unavailable`, with its error. Bare metal keeps no projection
  cache, so the other states VM reports do not arise.
- `checks` loses its `site_projection` entry. `checks["fulfillment"]`, which today mirrors
  the aggregate site read, reports only whether a fulfillment client is composed. A down
  site is visible in `site_projections` and changes no gated check.

Rejected: a summary check that is `degraded` when some sites are down. It would present one
site's failure as storefront-wide degradation, which the permanent requirement forbids and
VM's own test asserts against.

### "Publication candidate" gets one name

The term is used throughout `ARCHITECTURE.md` and the storefront-publication
specification without a definition, and `ARCHITECTURE.md` also used "candidate" for pool
members and scheduling. It is added to `ARCHITECTURE.md`'s "One name per concept":
one listing a publication pass could publish, derived from a source declaration before
anything is decided about it. The Resource Pools section's "physical settlement
candidates" is reworded to avoid the collision; a scheduling candidate — a resource
considered for placement — is a different concept and keeps its ordinary meaning.

### No deployed bare-metal database needs an upgrade path

Bare metal is not yet deployed as a domain, so this change carries no data migration
and no compatibility path for earlier bare-metal storefront state. This resolves the
question of listings bound before the common derivation key included the pool: the
historical-binding migration recorded such listings with a null pool under the domain
table's key, but no deployed database holds one.

A development database that does hold one converges without special handling. Such a
listing's key matches no candidate, so it closes as a withdrawn source and its
Physical Resource's candidate publishes under the common key — a fail-forward that
carries no seller close or pause across. The domain's existing remedy for storefront
state it no longer supports, resetting the storefront database as
`docs/bare-metal-seller-quickstart.md` describes, remains available. Neither a
fallback to the legacy key nor a carry-over of seller state is built for a population
that exists only in development.

**Revisit trigger:** bare metal's first deployment. From then on, bare-metal storefront
schema changes are additive and a table drop is a contract step.

## Open questions

None.

## Migration

No deployed bare-metal storefront database exists, so none is migrated. A new
storefront migration drops `derived_bare_metal_listings`.

In a development database, listings bound under the common key keep their identities
and are reconciled in place on the first run; listings bound before the key included
the pool fail forward as described above. Existing listings have no `publications`
records. The first run records each registry outcome it produces; a listing the run
does not change gains no record, and the divergence query reads only recorded outcomes,
so it is not treated as diverged. The accepted consequence: a registry already out of
step with a listing stays out of step until that listing next changes.
