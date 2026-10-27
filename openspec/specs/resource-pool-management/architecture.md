# Resource-Pool Management Architecture

The [normative contract](spec.md) defines pool administration. This document explains why pools own provisioning routing metadata but not scheduling or execution policy.

## Ownership boundary

A Resource Pool groups candidate Physical Resources and records the provider kind and provider-specific configuration needed after selection. It owns stable pool identity, enabled state, tags, configuration, and membership.

It does not choose a Settlement Resource and does not define the FulfillmentProvider contract. Keeping those responsibilities separate prevents administrative configuration from becoming an implicit scheduling algorithm and avoids a reverse dependency from the pool authority into fulfillment.

## Provider configuration

The generic pool package stores opaque provider configuration only after a provider-owned handler validates and normalizes it. This allows an adapter to enforce its own schema without teaching the pool authority about Ansible, Kubernetes, bare metal, or a future executor.

Resolved configuration is routing input. A fulfillment operation snapshots the accepted provider inputs at dispatch so later administrative edits do not silently rewrite an in-flight operation.

A pool's configuration may leave its playbook to the service. A VM pool's `playbook_path` is optional, and a bare-metal pool states no configuration at all. Each job's playbook is resolved when the job is prepared — the pool's own where it states one, otherwise the service's `vm_playbook_path` or `bare_metal_playbook_path` as configured then — and written into the job's stored parameters, so a later configuration change cannot rewrite an accepted operation's playbook on retry, as an edit to the pool cannot. A pool document can therefore name a VM pool without a deployment-specific path, which is what lets the packaged seed and portable documents declare one. A job stored with no playbook runs the executor's configured one.

The provider itself is fixed at creation. It is the routing context of every member and every record already resolved through the pool, so changing it in place would hand existing inventory to another executor without any of the checks that guard moving a resource. Replace, patch and document import therefore all refuse a differing provider before mutation, as they refuse a changed backing. The refusal is a validation error (HTTP 400) rather than a conflict, because no drain or wait could ever make it valid. Restating the pool's own provider on a patch is the same as omitting it and writes no configuration. Configuration stays editable within the provider through the handler's replacement, under its secret-retention rules.

The handler interface is validation, the two reads, and same-provider replacement. It has no deletion operation: pools are disabled rather than deleted, and configuration must stay resolvable for existing work, so a deletion hook would only ever serve the provider swap the pool refuses.

VM and bare metal register as `vm.ansible` and `bare_metal.ansible`, so neither domain's provider name is a bare mechanism name the other could be mistaken for. Upgrade rewrites the historical VM name in pools and fulfillment records, and nothing else.

## Membership and draining

Membership expresses which resources are candidates under a pool's routing context. Disabling a pool blocks new assignment but preserves membership and records needed by existing workloads. This is draining, not deletion.

Hard deletion is intentionally absent because an existing assignment, job, or lease must remain explainable even after operators stop selling through that pool.

Moving inventory to another provider is a second pool and an explicit reassignment of its members. The pool authority adds no guard of its own to that move, because each kind of member already has one at its own authority, and the two differ. A capacity resource cannot change pools while a held reservation is debited against it or assigns it for settlement; the site ledger enforces this, serialized through commit (see the site-capacity requirement "A capacity resource does not move pools under live obligations"). A host moves through the host authority's pool-change hooks, where the VM adapter refuses a relay-changing move while the host holds relay leases. A host move that keeps its relay may proceed while work exists, because it reassigns no capacity resource. A pool-level obligation guard would duplicate the site's rule across an authority boundary, and refusing disablement would contradict draining.

## Administrative reconciliation

Declarative YAML import is an operator reconciliation surface rather than a second persistence model. Strict validation rejects unknown structure. Dry-run computes the exact change without mutation. Apply is atomic, and canonical export makes equivalent state stable for review and automation. Omitted pools are disabled rather than erased.

Startup refuses stored state it cannot serve, because waiting does not repair it: a stored pool whose declarations are invalid, and a stored pool naming a provider no registered handler serves, each named with its pool and provider. Handlers are fixed by the build and every write refuses an unknown provider, so such a row comes only from outside the service's write paths, and no pool document can repair it; serving it would make every pool list, read, and export fail. Tolerating the row on reads with a problems field was rejected: it would add a pool wire field and an export entry no import accepts.

Validation runs in the order of what each check needs to judge the request. The typed pool models in `kit/resource-pools-contracts` check what the request establishes by itself: mode and backing declarations, and the structure of the hold, SLA, listing-shape, asking-rate and pricing hints. A typed caller and the server therefore refuse a malformed individual write before dispatch or database work, and the server answers HTTP 422. The service checks what needs composition or stored state: handler registration and provider-owned configuration, which need the composed registry the contracts package may not import, and then provider and backing immutability. Those last two are one pure comparison of a stored pool and the proposed values, returning field-specific problems. Individual writes raise its first problem, and documents report every problem prefixed with the entry's submitted index, so the rule has one implementation on every path. Documents carry raw YAML rather than models, so they reuse the same contracts-owned checks with their structured paths and codes. A document with request problems is not compared against stored state, and any problem leaves the whole document unapplied: no entry, no omitted-pool disablement, and, at startup, no new digest. A path is not reordered, and no lookup is added, only to report a different error first.

No pool is created implicitly, and no pool name is special: `default` is an ordinary pool, a document need not name it, and it may be disabled like any other. Migration creates no pool, because a migration's result depends only on code and stored data (see the deployment-state requirement "Service-owned migration history"). Startup imports contributed definitions, then the pool document, then seeds a fresh site, then checks stored declarations, then seeds host inventory, so a site's pools exist with their declared providers before any host or declaration can name them. A configured pool document that is missing or invalid fails startup; the seed never stands in for it.

A site that configures no pool document and stores no pool, enabled or disabled, is seeded from the pool document `pool_seed_path` names: by default one packaged with the provisioning service beside its settings, declaring `vm-default` and `bare-metal-default`, each delivering and advertising its own mode, backed, and with empty provider configuration. A site must start, and pass its smoke tests, without its operator writing a pool document. The seed's pools are named for their providers, so they commit a site to nothing and never collide with an operator's own, and they are ordinary pools: they sell nothing until an operator declares capacity into them, because no host write places a host or declares capacity. The seed goes through the same validation and import as a pool document, in the same transaction as the emptiness check, and records no digest, since it is not a document the site reconciles against. An operator replaces it by pointing `pool_seed_path` at another document, or disables it with an empty value. The seed is read only where it applies, so a dangling `pool_seed_path` never fails a serving site; where it applies, a missing or invalid seed fails startup. Making the packaged document the default pool document was rejected: every document-less site would then reconcile against it on upgrade, disabling its own pools, and every release editing it would revert pools created through the API. Seeding whenever a seed pool is missing was rejected for the same reason on a smaller scale: it would add the seed's pools to every existing document-less site.

One process initializes a database. The seed's emptiness check and its import share a transaction but are not serialized across processes, any more than the pool-document import or the host-inventory seed is. Two processes starting together on one fresh database can both find no pool; the second to write fails its start and, restarted, finds the pools and skips. No shipped deployment starts two processes against one database, so the assumption is stated rather than enforced.

## Advertisement, delivery, and backing

A pool makes three separate declarations about offering modes and admission.

`deliverable_modes` is an execution claim: the modes the pool's provider
configuration can deliver. Every execution layer rechecks it, and an initial set is
derived only from configuration that proves delivery. `advertisable_modes` is a
publication claim: the modes the pool's listings may name. They are separate
because a seller who trades by private arrangement can prove no delivery and must
still be able to list. Reading advertisement out of the deliverable set would give
that seller nothing, while treating the deliverable set as advisory for some
listings would let a pool proving no VM delivery advertise VMs.

`capacity_backing` says whether an admission authority stands behind the pool. A
backed pool may advertise only what it delivers, otherwise a buyer could reach
admission for a mode its provider will refuse. An unbacked pool must deliver
nothing. No layer reads backing at admission; the empty deliverable set is what
keeps an unbacked pool out of reservation, scheduling, and dispatch, through
rechecks those layers already perform. That keeps the new declaration from spreading
backing checks across the site and fulfillment authorities.

Backing is fixed at creation because every listing derived from a pool inherits
it, and changing it in place would reinterpret listings already published. Moving
supply between backed and unbacked is a second pool with its resources migrated
across.

What backing means lives in one delegate, `CapacityBacking` in
`kit/resource-pools-contracts`, beside the label it interprets. The declared label
selects it — `capacity_backing(label)` returns `BACKED` or `UNBACKED` and refuses a
label with no delegate — and the label stays what declarations, bindings, and the
projection carry, and what a published listing carries where its market's registry
schema publishes backing. Whether a market publishes backing at all is that schema's
decision, not the delegate's: the compute schema does, so a buyer can filter on it, and
the API-credit schema does not, since every credit listing is backed. Every decision that differs between backed
and unbacked supply is one of the delegate's operations: the declaration rules above,
admitting a capacity effect, placing a hold, judging supply against its declaration
and then, where availability bounds it, against availability, which labels
availability reconciliation may touch, which settlement clauses an unbacked
listing keeps, and which delivery terms a listing carries. Consumers ask it to act and never learn the category, so none
branches on the label, and a further category is a change to the delegate rather
than to its callers. A delegate exposing flags for callers to test would only move
those branches; one that performed effects would need clients and bindings its
contracts package may not import, so each operation takes the caller's work as an
argument and decides whether and how it runs.

Delivery terms are the fields a domain names as committing the marketplace to
delivering something — for bare metal a host's identity, its access methods, and a
view's availability. On a backed listing an admission authority stands behind them;
on an unbacked one nothing does, so a declared host or access method there would
advertise a machine and access the marketplace does not deliver. The delegate
decides them through two domain-neutral operations over the fields the domain
names: `carry_delivery_terms`, where the site builds a publication view, passes a
backed pool's terms through and carries none of an unbacked pool's, whatever the
declaration names; and `delivery_term_constraints`, where a model validates,
requires every term present on backed supply and every term absent on unbacked
supply. A term is present when it is neither absent nor null, and a string or
collection only when non-empty; a boolean is present as either value, because an
unavailable backed host's `available` is a legitimate `False`. The domain names
the fields and the delegate decides, so no domain branches on backing to build or
check a view (see the [storefront publication
architecture](../storefront-publication/architecture.md#bare-metal-listing-shapes)).

The delegate is a kit rather than core or the compute family because backing applies
to every market whose listings are admitted against capacity an authority holds — VM
and bare metal against physical capacity, API credits against quota — and to no
market without such an authority. It sits beside the label because both sides of the
provisioning boundary consult it: the site's declaration rules, and the storefronts'
bindings, reconciliation, negotiation, and settlement. Two questions are answered by
the registry without the caller naming a category: `legacy_producer_backing()`, what a
pool from a producer predating the declarations resolves to, and `admitted_backing()`,
the backing of a reservation a site admitted with no listing behind it.

Both declarations are required on every write rather than defaulted. A default
backing would assert whether anything stands behind a listing, and a default
advertisable set would widen or silently narrow what a pool may sell. Requiring
them also makes every pool carry them, which is what lets a consumer of the
resource-pool projection tell a producer predating the declarations (no pool
carries them) from a defective one (some pool lacks them). For the same reason a
consumer reads them only through the shared resolver, and advertisement membership
exists only on a resolved declaration: a raw read would turn an absent declaration
into an empty one and erase that distinction.

## Current limits

Pool administration does not establish pool priority, weighted scheduling, or fairness policy. Provider-specific operational health and execution success belong to provisioning adapters and lifecycle services, not pool metadata.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Site capacity](../site-capacity/spec.md)
