# Design — project capacity declarations that name no host

## Vocabulary used here

- **Capacity declaration** — the site-ledger record declaring a Physical
  Resource's shape, quantity, pool, attributes, `enabled`, and optionally the
  host it is delivered through. The ledger stores it as a `CapacityBucket`; the
  registration API and definition documents call its identity `resource_id`.
- **Physical Resource** — the supply a declaration describes, identified in
  projections by `physical_resource_id` (the declaration's `resource_id`).
  Scheduling selects one; an explicit placement constraint names one.
- **Host** — a registered connection record (`Host` row): address, port, user,
  key, pool membership, `enabled`. A declaration *names* a host through its
  `host_id` field; a named host may or may not be *registered*.
- **Provider** — the fulfillment implementation a pool names
  (`ansible`, `bare_metal.ansible`). A provider **needs a host** when its
  delivery connects to one. Both current providers do.
- **Backing** — a pool-level declaration of whether the pool can be admitted
  against (`pool-declared-advertisement-and-backing`). Unbacked pools hold
  declarations that name no host and are never admitted, scheduled, or
  dispatched.

The change directory keeps its original name. "Capacity resources" there means
capacity declarations.

## Context

What the code does today, which differs in places from this change's first
draft.

**The projection.**
`provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`
keys declarations on their own `host_id` (`:38-66`), then iterates `Host` rows
(`:67-73`). It drops, silently:

- a declaration naming no host;
- a declaration naming an unregistered host.

It raises `ValueError`, failing the whole site generation, for a declaration
with an enabled bare-metal publication and no host (`:46-58`).

From the host row `_project_host` (`:76-122`) reads:

| Field | Consumer |
|---|---|
| `attributes.host_id` | None |
| `attributes.public_host`, falling back to `ssh_host` | None |
| `pool_id` fallback to `host.pool_id` | Dead: a declaration's pool is mandatory |
| `enabled = host.enabled AND declaration.enabled` | Storefront listing reconciliation |
| `host.enabled` inside the bare-metal view's `available` | The view's only consumer, `trusted_bare_metal_projection`, has no production caller |

The VM reconciler reads only `physical_resource_id`, `capacity`, `available`,
and `attributes.gpu_model` (`domains/vms/listings/reconciler.py:461-497`). The
capacity-bucket projection and the snapshot already enumerate declarations
directly (`kit/site/src/market_site/projections.py:141-164`,
`kit/site/src/market_site/ledger.py:953-967`).

**Enablement.** Three flags exist and only two are enforced:

| Flag | Enforced by |
|---|---|
| `ResourcePool.enabled` | Scheduling (`list_enabled_pools`) |
| Declaration `enabled` (`CapacityBucket.enabled`) | Admission (`ledger.py:2163`), scheduling candidates (`ledger.py:1304-1312`) |
| `Host.enabled` | Host list queries only (`host_service.py:87-101`); job execution ignores it (`host_service.py:109-115`) |

Bare metal refuses a disabled host only at access-job validation
(`bare_metal_operations_service.py:180-192`); VM refuses it nowhere.

**Admission and scheduling.** Neither consults hosts.

- `reserve` matches any enabled declaration, host or not, which is correct for
  API credits, whose declarations never name a host.
- `iter_scheduling_candidates_in_session` filters on `enabled` and
  `resource_type` only, so `PhysicalSettlementScheduler` can select a Physical
  Resource whose declaration names no host. It then rebinds capacity, advances
  the cursor, and commits the assignment.
- The providers refuse a missing host only at prepare time (VM
  `ansible_fulfillment_provider.py:167-173`, bare metal
  `bare_metal_fulfillment_provider.py:133-180`), after the assignment is
  durable. An equivalent retry returns that same assignment.

**Dispatch.** `vm_provisioning_adapter/services/job_service.py:486-512` renders a
one-host inventory from the registered host record. When there is none, it
falls back to the configured static file (`settings.resolved_inventory_path`)
and still runs the playbook with `--limit <host_id>`.

The tenant address (`ansible_service.py:585-590`) is resolved in this order:

1. the record's `public_host`;
2. the static file's `public_host`;
3. the static file's `ansible_host`.

It never uses the record's `ssh_host`. On deployments without a static file,
the documented fallback in `docs/seller-quickstart.md` therefore yields no
address.

Production composition always wires `HostService`
(`vm_provisioning_adapter/runtime.py:139-148`,
`compute_provisioning_service/container.py:285-299`), so each "no host
service" branch is unreachable in production.

**Bare metal end to end.**

1. The storefront publishes from the snapshot, not the view
   (`arkhai_bare_metal_storefront/publication_cli.py:93-127`). It takes `host_id`
   and `physical_host_id` from inside the `bare_metal_publication` attribute
   (`:119-120`), so an operator duplicates them there.
2. Fulfillment checks that copy against the accepted terms
   (`fulfillment_service.py:190-217`).
3. The provider then checks the materialization against the declaration's own
   `host_id` (`bare_metal_fulfillment_provider.py:133-180`).

The two copies must agree or the deal fails after acceptance.

## Goals / Non-Goals

**Goals.**
- Every capacity declaration reaches storefronts through the resource-pool
  projection.
- Host connection identity is joined only where it is consumed: at dispatch.
- No admission, placement, or dispatch path can proceed toward a host that a
  provider needs and the declaration does not name, or that is not registered.

**Non-Goals.**
- No change to declaration administration.
- No commercial interpretation of declarations that name no host.
- No change to disabled-host semantics.
- No hostless provider.

## Decisions

### D1. The resource-pool projection is built from declarations alone

Every declaration projects, whether or not it names a host and whether or not
that host is registered. No host record is read. Identity, pool, type, capacity,
reported availability, attributes (except domain view configuration published
as a view), and `enabled` all come from the declaration.

**Alternatives.**
- *A — invert the loop and correlate hosts in.* Keep host-correlated entries
  byte-identical; omit host fields on uncorrelated ones. Rejected. It would
  preserve fields with no consumer, a management-address leak, and an
  `enabled` value that disagrees with admission. It would also leave two entry
  shapes that every consumer must tell apart.
- *Union a host loop with a second loop for the rest.* Rejected in this change's
  first draft for producing two structurally identical producers. B has one
  producer and no correlation.

**Consequences.**
- The change is not additive. Every generic entry loses `attributes.host_id`
  and `attributes.public_host`, and the projection revision advances once.
- An entry whose host is disabled but whose declaration is enabled now projects
  enabled. That matches what admission does, so the projection stops claiming
  something the site does not enforce. Whether disabling a host should stop new
  admission is `pools-6-fair-scheduling-policy`'s decision; see D8.
- The earlier "omit host-correlated fields rather than emptying them" decision
  is superseded. No generic entry carries host fields, so there is no
  omit-versus-empty distinction to preserve.
- The projection's duplicate-host guard is removed rather than kept. The
  projection no longer keys on hosts. At most one declaration may name a host,
  enforced at registration (`ledger.py:805-815`) and by the ledger's unique
  index. That is the rule's owner.

The one intentional host exposure is a domain publication view for a domain that
sells a specific host (D4). Pinning a specific Physical Resource for placement
uses `physical_resource_id`, which the projection keeps, not a host.

### D2. The host is joined at dispatch, and dispatch fails closed

Invariant:

> The inventory an execution path hands to Ansible is rendered from the
> registered host record named by the selected settlement resource. A host name
> with no registered record fails closed before any playbook runs. A static
> inventory file is a seed input, never an execution source.

The alternative that exists today is the static-file fallback, not rendering
from capacity. It is removed in this change because without that the invariant
this change states is false: a declaration naming an unregistered host would
dispatch against whatever the static file says.

Scope of the removal:
- the job path's fallback;
- the tenant-address lookups that read the static file;
- the optional-host-service branches in the VM job service and in bare-metal
  host validation;
- any static-file reader left without a caller, including the legacy
  `ProvisioningService` if planning confirms it has no production caller.

`inventory_path` remains as the startup seed input
(`app_runtime.py:122-135`).

### D3. The tenant address falls back to the record's connection address

*Amended by A2: the fallback reaches VM connection details; bare-metal access
coordinates come from the access playbook.*

The tenant-facing address is the host record's `public_host`, else its
`ssh_host`, never a static file. `public_host` should be set wherever the
provisioner and tenants reach the host on different networks. Falling back to
`ssh_host` is the reasonable default, and it is what the quickstart already
promises. Both operator quickstarts state it so the fallback is not a surprise.

### D4. The bare-metal publication view is built from its declaration

The `bare_metal.v2` view's identity, pool, capacity, and availability all come
from the declaration. Its `host_id` is the declaration's `host_id`.
Availability is the declaration's `enabled` and whole-resource availability,
with no `Host.enabled` term.

A declaration with an enabled publication that names no host projects without
the view. It does not fail the generation: one declaration must not make every
storefront's projection of the site unavailable, and a view without a host is
not a sellable specific-host listing.

A registered host record is not required. The view is a publication artifact,
and registration is dispatch's check (D2).

**Alternatives.**
- *Raise for every enabled publication without a host.* Rejected: one bad
  declaration takes the whole site's projection offline.
- *Require a registered host.* Rejected: it reintroduces host correlation into
  the projection.

### D5. Providers declare whether delivery needs a host; admission and scheduling recheck it

*Mechanism amended by A1.*

- **Declaration.** Each registered fulfillment provider declares whether its
  delivery needs a host. Provisioning composition already registers providers
  and pool-config handlers by identity and requires the two key sets to match
  (`compute_provisioning_service/composition.py:75-110`, `:184-207`). It
  collects those declarations into a plain map from provider identity to the
  requirement.
- **Admission.** The map is injected into the site ledger. `kit/site` already
  reads `ResourcePool`, so this adds no upward dependency. A declaration naming
  no host, in a pool whose provider needs one, is an ineligible admission
  candidate.
- **Scheduling.** The same map is injected into the scheduler, which treats
  such a Physical Resource as an ineligible candidate. Exclusion happens before
  policy selection, capacity rebind, or cursor write, on both the automatic and
  the explicit-constraint paths.
- **Existing assignments** are not rechecked. The assignment froze the host at
  scheduling, and dispatching to it honours the agreement. Dispatch is the
  final check (D2).
- **Unknown provider.** In a composition that supplies a map, a provider
  identity absent from it needs a host (fail closed).
- **No map.** A composition that supplies no map enforces no host requirement.
  That keeps API-credit admission, which never names hosts and never schedules,
  unchanged.

Why admission and not only scheduling: D1 makes a declaration naming no host
visible to storefronts. In a backed pool whose provider needs a host, it would
otherwise be listed, admitted, and refused only at placement, after acceptance.
Refusing at admission puts it in the ordinary capacity-refusal class, where any
other unservable claim already fails. The listing can still be published,
because the projection deliberately carries no host presence. That residual is
accepted.

Unbacked pools never reach admission (`unbacked-listing-publication` refuses
them at the capacity type boundary), so this needs no backing awareness and has
no ordering dependency on `pool-declared-advertisement-and-backing`.

This is the same layer-by-layer recheck pool offering modes already follow.
It is repository-wide, so `ARCHITECTURE.md` states it.

**Alternatives.**
- *Require a host universally in the scheduler.* Rejected: it would encode an
  assumption about every provider into a provider-neutral kit.
- *Refuse such declarations at registration.* Rejected: it would refuse the
  unbacked contact-exchange declarations this campaign needs, unless
  registration learned backing.
- *A registration-time warning.* Declined; the reservation-time refusal is
  sufficient.

No provider whose delivery needs no host exists or is planned in this campaign.
The seam has production consumers without one: both current providers declare
a need, and admission and scheduling enforce it for backed pools.

### D6. Naming a host is optional for a declaration

The permanent requirement that a declaration "MUST name the host its capacity is
delivered through as a `host_id` field" is about *where* the host is named. It
is restated so that a declaration delivered through no host names none, while
one delivered through a host still names it in that field and uniquely.

### D7. Operator and buyer visibility

The question was whether a declaration naming no host should appear in
operator-facing listings as well as the projection. It is resolved with no new
filtering.

- The provisioning API already lists every declaration
  (`GET /api/v1/capacity/resources`), and the host listing stays machines-only.
- The projection carries every declaration (D1). The campaign's contact-exchange
  listings need that.
- Buyers separate listings by **backing**, a listing property, through the
  exact registry filter `unbacked-listing-publication` adds. Host presence is
  private and never reaches a listing, so it is not something anyone filters
  on.

### D8. Out of this change's scope

- **Disabled hosts.** No new admission or placement against a disabled host,
  while dispatch honours existing assignments and teardown works. Both the
  admission half (`kit/site`) and the placement half (`kit/fulfillment`) go to
  `pools-6-fair-scheduling-policy`, recorded there.
- **The bare-metal storefront's duplicated host identity** goes to
  `pools-8-capacity-projection-and-listing-hints`, recorded there.

### D9. This change takes no position on why a declaration names no host

The declaration may belong to an unbacked seller, to inventory staged before its
connection exists, or to a host that has been deregistered. The projection
reports what was declared. Admission, scheduling, and dispatch decide what may
execute.

## Risks / Trade-offs

- **[A consumer relied on projected host fields]** → None found by the consumer
  trace. Planning re-traces every reader of `site_resource_pools`, e2e helpers
  included, before the fields are removed.
- **[Disabled hosts start appearing enabled in listings]** → True where the
  declaration is enabled. Admission already admits against them, so the listing
  becomes truthful rather than newly wrong. `pools-6-fair-scheduling-policy` owns
  making a disabled host stop new admission.
- **[A listing is published that reservation refuses]** → Accepted. It fails in
  the ordinary capacity-refusal class, and only for an operator
  misconfiguration: a backed, host-requiring pool whose declaration names no
  host.
- **[Static-inventory removal breaks a deployment that relied on it]** → Every
  production composition wires the host registry, and the static file seeds it
  at startup. Planning confirms no compose, Helm, or e2e path executes against a
  host that exists only in the static file.
- **[The host-requirement map drifts from registered providers]** → The map is
  collected from the same bundle registry whose key sets composition already
  requires to match; an absent identity fails closed.

## Coordination

- **`contain-embedded-host-key-material`** edits `write_inventory` and
  `render_inventory_ini` in the files this change edits for inventory resolution
  and tenant address. The functions differ. Whichever lands second rebases.
- **`unbacked-listing-publication`**'s design cites this change for fail-closed
  placement and dispatch. Its wording is aligned with D2 and D5 in this change's
  design update.

## Migration Plan

1. Land the provider declaration and host-requirement map, then the admission
   and scheduling rechecks. This closes the stranded-assignment defect
   independently of projection visibility.
2. Land dispatch fail-closed and static-inventory removal, with the tenant
   address fallback.
3. Switch the projection to declarations alone. The projection revision and
   digest advance once.
4. Update permanent specifications, `ARCHITECTURE.md`, and the quickstarts.

There is no schema change and no data migration. Rollback is a code rollback.
Declarations are unchanged by every step.

## Planning amendments (2026-09-22)

Findings from the planning-time checks the decisions above deferred. Each one
amends a decision; none reopens one.

### A1. How providers declare the host requirement (amends D5)

Provisioning composition cannot hand the site ledger a map derived from composed
adapters. The container builds the ledger before the site authority, the site
authority before the VM and bare-metal runtimes, and those runtimes before the
bundles composition assembles (`compute_provisioning_service/container.py:225-330`).
Deriving the map from composed adapters would be a construction cycle.

The declaration is therefore static data that can be read without constructing a
provider:

- **On the provider class.** Each concrete provider declares a class-level
  `needs_host`. `FulfillmentProvider` requires it, so a provider cannot be
  registered without stating it.
- **In the adapter package.** Each package exports its providers' declarations
  keyed by provider identity, derived from those class attributes.
- **In the container.** The container merges the package exports once. It passes
  the result to `CapacityLedgerService` and to `PhysicalSettlementScheduler`, and
  also to composition as the expected requirement.
- **In composition.** Composition refuses to start if the expected requirement
  does not name exactly the registered provider identities, or if any registered
  provider instance declares otherwise. A package export that drifts from its
  providers therefore fails at startup, not at reservation.

The fail-closed predicate has one implementation, in `kit/resource-pools` beside
`pool_delivers_offering_mode`: given a pool's provider identity and a supplied
requirement, does the pool need a host? Both `kit/site` and `kit/fulfillment`
already import that package, so neither imports a provider or the other.

### A2. The bare-metal access address is not covered by the fallback (amends D3)

The tenant-address fallback reaches VM connection details: the job path passes
the record's address into result parsing (`job_service.py:548-550`).

Bare-metal access coordinates come instead from the `host` the access playbook
reports (`bare_metal_fulfillment_provider.py:432-452`). The shipped access
playbook (`domains/vms/provisioning/iac/ansible/playbooks/bare-metal/node-access.yaml`)
is a 21-line stub that reports none. The execution inventory does hand the
playbook `public_host` as a host variable, as it does for VM.

So the bare-metal quickstart documents only what is true: the mounted inventory
is a seed input, and `public_host` is supplied to the access playbook. It does
not promise a fallback the stub cannot deliver. Completing the access playbook is
outside this change and has no owner; the closeout records it in the campaign
index's unowned-work table.

### A3. The static-inventory removal is contained

- **Registry always wired.** Every production composition wires the host
  registry (`vm_provisioning_adapter/runtime.py:139-148`, `container.py:285-299`),
  so each optional-host-service branch is dead in production.
- **Dead legacy service.** `ProvisioningService`
  (`vm_provisioning_adapter/services/provisioning_service.py`) has no production
  caller; only its own unit test constructs it. It is deleted.
- **Unused readers.** Once the job path and the tenant address read the registry,
  these static-file readers have no caller:
  - `parse_inventory`, `get_inventory`, `lookup_host_ip`, `lookup_public_host`,
    and the static `check_connectivity` in `ansible_service.py`, plus their mock
    mirrors;
  - the `InventoryHost` and `InventoryResponse` models.

  The connectivity route already renders from the registry through
  `host_operations_service`.
- **Readiness is unaffected.** Its no-registry branch reports an unavailable
  database inventory; it never reads the static file.
- **The seed input remains.** It is `inventory_ini` or `inventory_path`, read
  only when the host table is empty (`app_runtime.py:95-150`).

### A4. An operator-visible consequence of D2

Startup seeding is skipped once any host is registered. Today, a host added only
to the static file on a running deployment still dispatches, through the
fallback. After D2 it is refused until imported (`POST /api/v1/hosts/import` or
host registration).

That is the intended fail-closed behaviour, but it changes how an operator adds a
host. `DEPLOYMENT_AND_CONFIG.md` and both quickstarts say so.

## Review amendments (2026-09-22)

From code review of Sections 1–5. Each amends a decision above; none reopens
one.

### A5. An assignment recorded with no host is refused, not returned (amends D5)

D5 said an existing assignment's host "was fixed when it was placed". That is
true only for assignments placed after this change. Before it, the scheduler
could place a reservation on a declaration naming no host, and an equivalent
retry returned that assignment indefinitely.

Such a row can only be `assigned`. The provider refuses a missing host in
`prepare_create`, inside the acceptance transaction, so acceptance rolls back
and nothing is ever dispatched.

The existing-assignment path now refuses it: `NoEligibleSettlementResourceError`,
the same 422 a fresh placement gets. The row stays `assigned` until its
reservation is released or expires. The ledger's abandonment hook then moves it
to `abandoned`, the lifecycle every unaccepted assignment already follows.

**Alternatives.**
- *Re-place the reservation in the same transaction.* Rejected: an assignment
  row is keyed by its reservation and `abandoned` is terminal, so re-placing
  would rewrite a scheduled resource that is meant to be immutable.
- *An upgrade migration abandoning such rows.* Rejected: it would change durable
  state at startup, and the reservation would still hold capacity until its own
  end.

Only operators who declared capacity without a host in an Ansible pool, with a
deal placed on it, can have such rows.

### A6. Providers are refused at registration, not only at composition (amends A1)

`ProviderRegistry` refuses a provider that does not declare `needs_host`, so
registration itself holds the invariant for every caller that builds a
registry. Composition's exact-set comparison against the early requirement map
remains; it guards a different thing, drift between that map and the providers
actually registered.

The implementation first enforced this only at composition, because many tests
registered bare `MagicMock` providers. That weakened a production invariant for
test convenience. Test doubles now declare their host need as real providers
do: a `MagicMock` subclass with a class-level `needs_host` where a mock is
wanted. Designing for testability means conforming fakes, not a weaker
contract.

The declaration is inherited. `FulfillmentProvider` supplies no default, but a
subclass of a provider that declares one inherits it; a test subclass of a real
provider is the ordinary case.

### A7. The shared predicate uses pool-level vocabulary (amends A1)

`kit/resource-pools` is an authority capability below `kit/fulfillment`, and
fulfillment owns execution contracts. The predicate stays in
`kit/resource-pools`: `kit/site` cannot import fulfillment, and no foundation
package owns pool semantics. Its documentation now states the rule at pool
level, as whether a declaration in a pool must name a host given the pool's
provider identity, which resource-pools already owns as a pool field. It no
longer describes fulfillment execution.

A requirement value that is not a `bool` is refused rather than coerced,
matching `provider_needs_host`.

### A8. A library's database-backed tests are integration tests

`TESTING.md` defines a unit test as one class with mocked collaborators, and an
integration test as the real app with a real database and the DI container.
Kit libraries test their persistence contracts against real embedded SQLite,
and fit neither definition: the database is real, but there is no app. They
have lived in `tests/unit`, including the concurrency tests `ARCHITECTURE.md`
requires to use independent sessions against one real database.

For a library package, integration means its public service API against a
real embedded database, with no app. Such tests live in `tests/integration`,
and the package's test target runs both directories. `TESTING.md` states this
at promotion. Existing files migrate when next touched; this change moves only
its own two.

**Alternatives.**
- *Keep them in `unit/` under a stated exception.* Rejected: "unit" would mean
  two things.
- *Move every such file now,* 13 files across four packages. Rejected: outside
  this change's boundary.

### Follow-up: one registration source per adapter package

Adding a provider today touches its bundle and also the container's
`_merge_host_requirements(...)` call. The container names each adapter package
twice: once for its runtime builder, once for its host requirement.

A per-package descriptor could carry both, and composition could derive the
early requirement map and the provider registrations from it: provider
identity, `needs_host`, and the runtime and bundle builders. That restructures
container composition, so it is out of scope here. Drift between the two is
already refused at startup. It has no owning change.

## Open questions

None. The operator-visibility question is resolved by D7.
