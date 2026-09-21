# Design

## Context

See `proposal.md`'s "Why" for motivation. This section records what was verified
directly against the code during the investigation (2026-08-06), because most of it
is not stated in any existing specification and the conclusions below depend on it.
It was re-verified on 2026-09-21; the drift found then is recorded in "What changed
since the investigation" below, and the tables in this section describe the code as
of that date.

### What the provisioning service seeds today

| Concern | Seeding path | Runtime API | Idempotence |
|---|---|---|---|
| Hosts | `app_runtime.seed_inventory_if_empty` from `inventory_ini` or `resolved_inventory_path` | `POST /api/v1/hosts` and siblings, `POST /api/v1/hosts/import` | Skipped entirely when the table is non-empty; `/hosts/import` always upserts and leaves hosts the file does not name untouched |
| Resource pools | `app_runtime.import_pool_definitions_if_configured` from `resolved_pool_definitions_path` | `POST`/`PUT`/`PATCH /api/v1/pools` | Digest-gated: reconciled when the document differs from the last one recorded (see the 2026-09-09 note below; this table originally read "every startup") |
| Sellable capacity | **none** | `PUT /api/v1/capacity/resources/{resource_id}` only | n/a |

The registered startup steps are `apply-ansible-config`,
`initialise-container-resources`, `resolve-request-path-services`,
`import-relay-definitions`, `import-pool-definitions`, `seed-inventory`,
`create-job-queue`. Nothing creates capacity resources and nothing derives them from
hosts. The service does not apply migrations in-process: the Helm init container,
`compute-provisioning-migrate`, or `make migrate` applies them, and
`initialise-container-resources` only checks the schema version.

The two seeding paths differ deliberately and the difference is instructive. Host
seeding is skip-if-non-empty so operator edits made through the API survive a pod
restart. Pool import reconciles a declared document — originally on every startup,
now gated on the document's digest for the same reason host seeding is
skip-if-non-empty: reapplying unchanged state reverts administration performed since.
Capacity definitions are a declared inventory in the same sense pool definitions are,
so this change follows the pool idiom, not the host one — see "Decisions".

### What a host-only deployment can and cannot do today

`capacity_inventory._project_host` supplies a fallback. With no matching capacity
resource it projects `resource_id` from `host.name`, `pool_id` from `host.pool_id`,
`resource_type` as `"compute.gpu"`, and `capacity` as `{"gpu_count": host.gpu_count}`.
It omits the `available` key entirely, which the VM reconciler reads under its
"ignorance is not zero" rule as unknown-therefore-fully-available, corrected
authoritatively at reserve time.

The fallback feeds only the resource-pool projection, which listing derivation reads.
Admission does not read it: `probe` and `reserve` match `CapacityBucket` rows, and
only `register_resource` creates those. A host-only deployment therefore publishes
listings it cannot sell against, and the refusal surfaces downstream as
`no_matching_inventory`. The e2e capacity helpers
(`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`) document this and
register a declaration for every executor for exactly that reason. The earlier
version of this section said a host-seeded deployment "publishes and sells"; it
publishes only.

This is why the gap has been invisible: the fallback silently substitutes host GPU
count for a capacity declaration in the one place a reader looks — the published
listing — and GPU count is the only dimension anything publishes today.

### Why the fallback cannot reach the other dimensions

`Host` carries `name`, `kvm_host`, `public_host`, `ssh_user`, `ssh_key_type`,
`ssh_key_value`, `gpu_count`, `gpu_model`, `enabled`, `pool_id`, and timestamps.
There is no vCPU, RAM, or disk column, and the INI parser reads only `gpus=`,
`gpu_model=`, `public_host=`, and `ansible_ssh_private_key_file=` from
`[kvm_hosts]`/`[bare_metal_nodes]` entries.

The retiring `resources.csv` carried four dimensions — `gpu_count`, `vcpu_count`,
`ram_gb`, `disk_gb` — the same set `resource_capacity_validator` enforces against
host totals and `host_capacity_remaining` sums. So the storefront's local table has
been the only operator-facing expression of multi-dimensional capacity in the
system.

### What already supports the dimensions below the operator surface

`kit/site`'s ledger accepts and matches a `capacity` dimension map; the
site-capacity specification's "Multidimensional capacity accounting" and "Committed
dimensions remain authoritative through scheduling" requirements are already
normative; `PhysicalSettlementScheduler` fit-checks every requested dimension; the
Ansible playbooks create VMs with variable shapes. The missing piece is genuinely
only the declaration surface.

### What changed since the investigation (verified 2026-09-21)

- **Startup order.** Relay import now runs before pool import, and host seeding runs
  after both. Capacity import slots after `import-pool-definitions`; see
  "Startup import follows the pool-definitions idiom".
- **Migrations are out of process.** The compute-domain migration in "Legacy host
  capacity is derived at seed time and once at upgrade" runs in the init container
  or migrate command, never at service startup.
- **The mirror dimension is used far more widely than `register_resource`.**
  `PRIMARY_DIMENSION` appears in legacy claim translation (`_requested_dimensions`),
  the capacity and reservation read fallbacks (`_resource_capacity`,
  `_reservation_dimensions`), the reserve and resize mirrors, `_held_units`,
  `_resource_payload` (`value`, `available_units`), and `_match_payload`
  (`allocated_units`, `available_units`, and their `*_gpu_count` aliases). Several
  of those are module-level helpers that `kit/fulfillment` and storefronts call
  directly (`dict_resource_satisfies_claim`, `resource_feasibility_view`), so the
  name has to reach them as a parameter rather than from instance state alone.
- **Registration cannot join the importer's transaction as written.**
  `DefinitionDocumentImporter` applies a document and records its digest in one
  transaction it owns; `register_resource` opens its own session and commits. The
  ledger already has the pattern needed (`assign_settlement_resource_in_session`).
- **Deployment conventions moved.** Helm derives `relay_definitions_path` from the
  presence of `definitions.relays` rather than accepting a path, and deliberately
  does not wire `pool_definitions_path` at all. Compose wires no definition
  document. See "Deployment wiring follows the relay idiom".
- **The projection's host-correlation rule is wider than a name match.**
  `load_capacity_resource_inventory` maps a declaration to a host by its
  `resource_id`, its `vm_host` attribute, or an enabled bare-metal publication's
  `machine_id`, and refuses outright when two declarations map to one host. The e2e
  helpers rely on the `vm_host` form: their declaration's `resource_id` is the
  commercial id the listing advertises, not the host alias.
- **No payload this change touches is a versioned envelope.** The capacity
  registration body, `/api/v1/capacity/*` payloads, and projection rows carry no
  `kind`/`schema_version` and are not `VersionedContractModel`s; the
  `bare_metal.v1` publication view's shape is unchanged. Wire changes are therefore
  versioned by distribution version only — see "Wire and distribution versioning".

## Goals / Non-Goals

**Goals:**

- One authoritative home for sellable capacity inside the provisioning service.
- An operator path for declaring it that matches an idiom already proven in the same
  file.
- A migration that costs existing INI-seeded deployments nothing at upgrade.
- Leave admission, matching, and scheduling *policy* untouched. Derived declarations
  are ordinary declarations and are admitted like any other — see "Derived
  declarations are admissible" for why that is a consequence rather than a policy
  change.

**Non-Goals:**

- Designing the negotiation or pricing surface over the new dimensions.
- Choosing final requirement/claim vocabulary; `structured-capacity-requirements`
  owns that and this change uses the dimension names `arkhai_vms` already defines.
- Deciding how the storefront presents multidimensional listings.
- Delivering the product requirement to sell an individual physical resource end to
  end. Derivation makes an INI-seeded host reservable through the provisioning
  service, but storefront wiring for per-resource sale is not this change's
  acceptance boundary.

## Decisions

### Capacity resources are the single home for capacity; hosts are connection identity

Two options were considered.

**Rejected — extend `Host` with vCPU/RAM/disk columns.** Fewest moving parts: INI
seeding would then cover every dimension and `_project_host`'s fallback would work
unchanged. Rejected because `Host` is connection identity — SSH user, key material,
Ansible alias, addressing — and folding sellable capacity into it conflates two
concerns the system already separates elsewhere: the bare-metal publication view is
built from a capacity resource's attributes, not from host columns, and
`load_capacity_resource_inventory`'s own docstring already states that "capacity
resources are authoritative for availability and Physical Resource identity" while
"host rows supply only host inventory needed to correlate the configured machine
alias." The code has the boundary; only the data has drifted across it. An Ansible
INI is also a poor carrier for capacity declarations, since it exists to describe how
to reach a machine.

**Accepted — capacity resources own every dimension, hosts own connection identity.**
This is the boundary the docstrings already claim, made true.

A third shape — GPU stays on `Host`, other dimensions move to capacity resources —
was rejected outright. It would leave one service with two partial capacity
authorities, reproducing inside provisioning exactly the duplication that
consolidating physical authority out of the storefront exists to remove.

### GPU capacity migrates rather than staying as a fallback tier

Keeping `Host.gpu_count` as a fallback for hosts without capacity resources is
tempting because it preserves every current deployment for free. It is rejected for
the same reason as the third shape above: a fallback tier *is* a second authority,
consulted whenever the first is absent, and "absent" is not distinguishable from
"declared as zero" at the projection layer. The whole class of bug this change fixes
(see the divergence below) comes from two sources of the same fact.

Instead, a migration derives a capacity resource from every `Host` row carrying GPU
data, so the first authority is populated before the fallback is removed.

### Freeze-then-redirect, no `DROP`

`Host.gpu_count`/`gpu_model` stop being read for capacity but stay in the schema,
matching the POOLS campaign's additive-only convention and `pools-9`'s own
freeze-then-redirect shape. A `DROP` belongs in a later follow-up once a deployment
cycle confirms the derivation was never rolled back.

The consequence for operators is the same as `pools-9`'s and must be documented the
same way: rolling back past this change is a code rollback, not a configuration
change, because the code that read host capacity is gone rather than gated.

The derived capacity rows are additive, so a rolled-back reader ignores them
harmlessly — the rollback risk is one-directional and small.

### Startup import follows the pool-definitions idiom, not the host idiom

`capacity_definitions_path` resolves exactly as `pool_definitions_path` does
(`config.py`'s `resolved_*_path` property, empty string meaning unset), reconciliation
goes through the same `DefinitionDocumentImporter` gated on the document digest, and
a configured path that does not exist raises rather than silently skipping — all
matching `import_pool_definitions_if_configured` as it now behaves. Choosing the host
idiom (skip-if-non-empty) instead would make an operator's *edited* capacity file
silently inert after the first boot, which is what the pool idiom exists to avoid;
the digest gate avoids that without reapplying an unchanged document, which is the
opposite failure. See "The import contract changed underneath this change" below for
why an earlier version of this section said "every startup".

Ordering within `startup_steps()` matters: capacity import must run after
`import-pool-definitions`, because a capacity resource names a `pool_id` and the
pool must exist first. It also runs after `seed-inventory`, so a first boot from an
INI and a capacity document derives nothing for a host the document declares — see
"Legacy host capacity is derived at seed time and once at upgrade". The resulting
order is relays → pools → hosts → capacity → job queue.

**REST import and entries a document omits follow the host convention (decided
2026-09-21).** Site administrators control inventory through mounted documents,
values files, and the REST API, and a restart must not clobber API administration.
So:

| Trigger | Reconciles when | Records the digest |
|---|---|---|
| Service start with `capacity_definitions_path` set | the mounted document's digest differs from the one last recorded | yes, in the apply's transaction |
| `POST /api/v1/capacity/definitions/import` | always — the operator has asked | no |

The REST import mirrors `POST /api/v1/hosts/import`: it upserts every declaration
the document names and leaves every declaration it does not name untouched, and it
does not record a digest, exactly as `POST /api/v1/pools/import` does not. A
startup import likewise retains unnamed declarations; unlike pools it disables
nothing. A document therefore adds and updates declarations and never removes one.
Disabling is an explicit act through the document (`enabled: false`) or the API.

Retention rather than the pool rule is also the safe choice here: an unnamed
declaration may be a derived one, an API-registered one, or one backing a live
reservation, and none of those is what an operator editing an unrelated entry
means to switch off.

**Where the code lives.** `kit/site` owns the document shape, its validation, and
the in-session reconciliation, the same way `kit/resource-pools` owns
`import_pools_in_session`; the ledger gains a `register_resource_in_session`
variant that neither commits nor opens a session, which both the reconciliation and
the public `register_resource` use. The provisioning service owns the startup step,
the `DefinitionDocumentImporter` applier, and the REST endpoint. The endpoint lives
in provisioning rather than on the `kit/site` router so the API-credits authority,
which mounts the same router, does not acquire a document-import surface it has no
deployment story for. It uses the same authentication and role as
`POST /api/v1/hosts/import`, because it is the same kind of act: an operator
submitting inventory.

A declaration naming a pool that does not exist fails the whole import, naming the
pool, with nothing applied and no digest recorded — the same posture relay import
takes for a secret key the profile does not carry. The first-boot consequence under
Helm is resolved by wiring pool documents alongside capacity documents; see
"Deployment wiring follows the relay idiom".

### Projected attributes must not contradict projected capacity

`_project_host` builds `capacity` from the capacity resource when one is present but
builds `attributes` from the host unconditionally:

```text
gpu_count  = int(host.gpu_count or 0)
capacity   = dict(resource.get("capacity") or {"gpu_count": gpu_count})
attributes = {"vm_host": …, "public_host": …, "gpu_count": gpu_count}
             plus attributes["gpu_model"] = host.gpu_model when set
```

So a capacity resource declaring four GPUs on a host recorded with eight projects
`capacity={"gpu_count": 4}` and `attributes={"gpu_count": 8}` in the same row.

Nothing consumes the attribute for admission today, so this is not currently
producing incorrect allocations. It is still a real divergence a storefront can read,
and it is a direct symptom of the two-authority problem: the function reaches for the
host because the host was, historically, where capacity lived. Consolidating capacity
is the moment to fix it rather than preserve it, and the fix is what makes
`attributes` derivable from one source.

`gpu_model` has the same shape and the same fix. It is categorical rather than
quantitative — matched by equality, per its own column comment — which is why it
belongs in `attributes` rather than `capacity`, and why it must move to the capacity
resource's attributes rather than being dropped.

What the projected `attributes` map contains after the cutover is decided under
"Projected attributes are the declaration's, plus host connection fields".

### The INI keeps its GPU variables as derivation input, not as capacity

**Amended 2026-09-21.** The trigger for derivation described in the second paragraph
below — a startup step that derives for every host lacking a declaration — is
superseded by "Legacy host capacity is derived at seed time and once at upgrade".
The rest of this section stands.

`gpus=` and `gpu_model=` continue to be parsed, and continue to write
`Host.gpu_count`/`gpu_model`, which remain as frozen columns. What changes is that
those columns no longer reach the projection. For a fresh INI-seeded deployment with
no capacity definitions file, this would mean hosts with no sellable capacity — a
regression for exactly the deployment shape the compose and Helm defaults use.

The derivation is therefore not migration-only: the same host-to-capacity-resource
derivation runs as a startup step for any host that has GPU data and no capacity
resource, so INI-only deployments keep working. This is a compatibility bridge with a
deliberate end: it is what allows the later `DROP` follow-up to also remove the INI's
GPU variables, at which point the INI describes only how to reach a machine.

Recording this explicitly because it is the part of the design most likely to be
misread as "the fallback survives after all." It does not — the projection reads one
authority. What survives is a *populating* step that writes the authority from a
legacy input, which is observably different: an operator who declares capacity for a
host wins outright, and no read path consults the host.

### Legacy host capacity is derived at seed time and once at upgrade (decided 2026-09-21)

Derivation runs in exactly two places:

1. **Where INI host data is applied** — `HostService.seed_from_ini`, which serves
   both the startup `seed-inventory` step and `POST /api/v1/hosts/import`. The
   derivation runs in the same transaction as the host upsert, through an injected
   derivation port the provisioning container supplies, so a crash cannot leave a
   seeded host without its declaration while the skip-if-non-empty startup seed then
   refuses to retry it.
2. **One ordered compute-domain migration** for hosts already present at upgrade.

It does not run on every startup, and it does not run for `POST`/`PUT
/api/v1/hosts`.

A recurring startup scan was the earlier plan. It is rejected because it makes what
is sellable depend on when the process last restarted: a host added through the API
would gain a declaration at some later restart rather than when it was added, which
is the "process start is a submission" failure the definition-document importer
exists to prevent, arriving by a second route. Deriving where the legacy input
enters keeps derivation an effect of submitting inventory.

The host CRUD API does not derive because it is administration of connection
identity. An operator creating a host through the API declares its capacity through
the capacity API; the e2e helpers already work this way, and a host they register
with `gpu_count=4` beside a one-unit declaration is exactly the case derivation must
not touch.

A single derivation unit serves both callers: a pure planning function takes host
rows and existing declarations and returns the declarations to create; the writer
is the ledger's `register_resource_in_session`. The migration calls the same unit
inside its own transaction rather than reimplementing it in SQL. That deviates from
the migration module's raw-SQL habit deliberately — two derivations that can drift
are the failure task 2.1 names — and is safe because the migration is recorded once
and never re-runs against a later schema.

### A host counts as declared by the projection's own correlation rule (decided 2026-09-21; superseded 2026-09-21)

**Superseded 2026-09-21** by "A declaration names its host through `host_id`"
below. The analysis that follows describes the code before `unify-host-identity`
and the hazard any rule must avoid; it is retained as rationale, not as the rule.

"Derive only for hosts with no existing declaration" needs a precise meaning of
*existing declaration for this host*, because declarations and hosts are linked by
more than a shared name. The projection correlates a declaration to a host when any
of these equals the host's name:

- the declaration's `resource_id`;
- its `vm_host` attribute;
- the `machine_id` of its enabled `bare_metal_publication` attribute.

It then refuses outright — `ValueError`, and the projection fails for the whole
site — when two declarations correlate to one host, because that would sell the
same hardware twice.

So derivation must use the same rule. The concrete hazard is the shape the e2e
helpers use: a declaration whose `resource_id` is the listing's commercial id, with
`vm_host` naming the host. A derivation that checked only `resource_id == host.name`
would see no declaration, create a second one, and break the site's projection.
Sharing one correlation function between the projection and the derivation makes
the two unable to disagree.

A derived declaration is:

| Field | Value |
|---|---|
| `resource_id` | the host's `host_id` |
| `host_id` | the host's `host_id` (amended 2026-09-21; previously a `vm_host` attribute) |
| `pool_id` | the host's `pool_id` |
| `resource_type` | `compute.gpu` |
| `capacity` | `{"gpu_count": host.gpu_count}` |
| `attributes` | `gpu_model` when the host records one; otherwise empty |
| `enabled` | the host's `enabled` |

Only a host with `gpu_count > 0` is derived. A zero-GPU host has no legacy capacity
to preserve, and a zero declaration would publish a resource with nothing to sell.
Once any declaration correlates to a host, later INI values for that host have no
effect on capacity; the operator documentation says so.

### A declaration names its host through `host_id` (decided 2026-09-21)

The repository owner asked why the declaration–host relationship has to be inferred.
It does not: the link was an explicit reference spelled three ways inside a free-form
attribute map. `unify-host-identity` gives the declaration a first-class `host_id`
and renames every host-identity spelling to it, as a compliance fix against
`ARCHITECTURE.md`'s "One name per concept". This change consumes it:

- projection correlation is `declaration.host_id == host.host_id`, and the refusal of
  two declarations per host is a uniqueness check on that field;
- a host counts as declared when some declaration has its `host_id`;
- a derived declaration sets `host_id` to the host's, and carries no `vm_host`
  attribute.

The multi-key rule and the `resource_id == host.name` match — the one genuinely
fallback-shaped part — are gone. This change depends on `unify-host-identity`
landing first.

### Derived declarations are admissible (decided 2026-09-21)

Before this change an INI-seeded host published but could not be reserved, because
no `CapacityBucket` existed for admission to match. A derived declaration is a
`CapacityBucket`, so after derivation such a host is reservable wherever its pool
declares the requested offering mode. This changes what an INI-seeded deployment can
do without changing any admission, matching, or scheduling rule, and it is the
outcome the product wants: selling an individual physical resource is an existing
requirement that the provisioning service supports and the storefront has not wired
end to end. Completing that storefront path is not this change's scope.

### A host with no declaration is not projected (decided 2026-09-21)

Removing the fallback forces a choice for a host with no correlated declaration —
a zero-GPU INI host, or an API-registered host whose operator has not declared
capacity yet. Projecting it with an empty `capacity` map would publish a resource
that reads as authoritatively empty; projecting it with capacity omitted would
publish one the reconciler reads as unknown-therefore-available. Both invent a claim
nobody declared.

So the projection omits it. The resource-pool projection reports declared capacity;
a machine with none declared has nothing to report. This is also the shape
`project-capacity-resources-without-hosts` completes by iterating declarations
rather than hosts, so the follow-up inherits no row it must stop producing.

### The primary-dimension fallback writes a GPU name into every domain (added 2026-08-06)

`kit/site/ledger.py` declares `PRIMARY_DIMENSION = "gpu_count"` as a module constant,
and `register_resource` writes `new_dimensions[PRIMARY_DIMENSION] = int(total_units)`
whenever a caller supplies no explicit capacity map. `_resource_capacity` falls back the
same way when reading a row whose `capacity` was never populated.

The irony is instructive: the comment immediately above the constant explains that
domain-specific claim aliases "are supplied by the composition root ... so this module
carries no VM-specific knowledge." That is true of `unit_claim_keys`, which the
API-credits composition root correctly overrides to `("units",)`. It is false of the
constant on the next line. Half the genericization was done and the comment claims all
of it, which is how this survived.

The fix belongs to this change because the write is in `register_resource`. What it
should become depends on a question this change does **not** answer: whether the scalar
`CapacityBucket.total_units` / `CapacityReservation.units` mirror survives at all. That
scalar is what forces a primary dimension to exist — it predates multidimensional
capacity and is maintained as a mirror of one named dimension. Retiring it removes the
need for a primary dimension entirely; keeping it means the name must be supplied by the
composition root like `unit_claim_keys` already is.

This change takes the smaller of the two: make the name composition-supplied, and stop
writing it when the caller declared capacity explicitly.

**Scope and compositions (decided 2026-09-21).** "Composition-supplied" means every
use listed under "What changed since the investigation" reads the supplied name: the
ledger takes it as a constructor argument and passes it to the module-level helpers
that `kit/fulfillment` and storefronts call. The VM composition supplies
`gpu_count`, so nothing changes there. The API-credit composition supplies `units`,
matching its `unit_claim_keys` of `("units",)`, so its claims, declarations, and
`available_units` all speak one name. API credits is not a launched domain, so its
existing rows receive no migration and no compatibility reader: an API-credits
database written under `gpu_count` is recreated rather than converted. The compute
domain does migrate — `capacity_buckets.total_units` becomes nullable there (see
Section 4b of `tasks.md`). Retiring the scalar is a schema
change touching every legacy single-quantity caller, and is recorded below as deferred
rather than folded in. **Planned 2026-09-09 as Section 4b** — this decision previously
had no implementation task while task 1.4 said to add nothing to
`ResourceRegisterRequest`, so an implementer would have had to invent the semantics
while coding. The domain-neutral declaration contract this change states cannot hold
without it.

### The import contract changed underneath this change (added 2026-09-09)

This change was written when the pool-definitions import applied its document on every
startup, and it mirrored that reasoning explicitly: idempotence was said to make an
every-startup import safe. `DEPLOYMENT_AND_CONFIG.md` has since established the
opposite — "a process start is not a submission", and import "is idempotent with
respect to the document, not the database", because "re-running it against state
something else changed reverts that change". `DefinitionDocumentImporter` implements
the digest gate, and `import_pool_definitions_if_configured` is now a one-line
delegation to it.

So the instruction to mirror the pool import exactly is still correct; what it means
has changed. Capacity definitions follow the digest gate.

This matters more here than it would for pools, because this change also promotes
`PUT /api/v1/capacity/resources/{resource_id}` to an operator administration surface.
An unchanged mounted document reapplied on an unrelated restart would silently revert
capacity an operator had administered through that API — exactly the failure the
digest gate was introduced to prevent, arriving through a second reconciliation path in
the same service.

### Reassignment rewrites authority under live reservations (added 2026-09-09)

`register_resource` writes `bucket.pool_id = effective_pool_id` on update, and
`backing_pool_id_in_session` resolves a reservation's pool by reading the resource's
*current* `pool_id` — its docstring says "return the current reservation debit pool".
So moving a resource between pools changes which authority an already-existing
reservation resolves to, without the reservation changing.

That was latent while nothing made cross-pool movement a supported workflow. Two
changes now do: `pools-9-retire-local-physical-authority` makes "create a second pool
and migrate members across" the answer to a pool's provider being fixed at creation,
and `unbacked-listing-publication` makes the same move the answer to a pool's backing
being fixed. Both would exercise it.

A drain invariant is the smaller fix: a resource may not move while it holds a live
obligation resolved through its pool. The alternative — recording pool provenance on
the reservation itself — introduces a second source of truth for a reservation's pool
and is a much larger change for the same guarantee.

**What "live obligation" means inside `kit/site` (decided 2026-09-21).** A
reservation in `HELD_RESERVATION_STATES` whose debit is against the resource, or
whose `settlement_resource_id` names it. A running workload always has such a
reservation — `provisioning`, `leased`, `releasing`, `release_failed`, and
`unmanaged` are all held — so the rule is enforceable without `kit/site` consulting
fulfillment state, which its dependency layer forbids.

**`pool_id` is required on the wire (decided 2026-09-21).** The registration `PUT`
replaces the whole declaration, so an omitted `pool_id` used to write `NULL` —
silently moving a resource to the default pool, which is a reassignment the drain
rule would then have to guess at. `ResourceRegisterRequest.pool_id` becomes a
required field, rejected by Pydantic validation when missing, and the ledger's
`register_resource` takes it as a required argument. Existing rows with a `NULL`
`pool_id` are treated as the default pool: the compute-domain migration backfills
them to `DEFAULT_POOL_ID`, matching how every existing reader already resolves
`NULL` (`resource.pool_id or DEFAULT_POOL_ID`).

Backed-to-unbacked is where this matters most, because an unbacked pool must never
participate in reservation behaviour and reassignment would hand it a live one.
Unbacked-to-backed is safe by construction, since an unbacked resource holds no
reservations, but the invariant is stated generically rather than scoped to backing:
the same hazard exists for a backed-to-backed host migration.

### Wire and distribution versioning (decided 2026-09-21)

Three wire changes: `ResourceRegisterRequest.total_units` becomes optional,
`ResourceRegisterRequest.pool_id` becomes required, and the resource-pool
projection's `attributes` stop carrying `gpu_count` (and change source per the
attribute resolution in "Open Questions"). None of these payloads is a versioned
envelope — no `kind`/`schema_version`, and none is a compute-provisioning
`VersionedContractModel` — so there is no envelope version to raise. Compatibility
is expressed through distribution versions: `arkhai-kit-site` and
`arkhai-kit-site-client` take a minor bump (both are pre-1.0), the provisioning
service and the API-credits service and storefront bump, and every consumer's lower
bound moves to the new `kit/site` and `kit/site-client` versions. The client's
`ResourceRegistration` model moves with the server model, as its own docstring
requires.

### Deployment wiring follows the relay idiom (decided 2026-09-21)

`DEPLOYMENT_AND_CONFIG.md` fixes four conventions this wiring must follow:

1. **Configuration travels in mounted files.** A pod sets only `ACTIVE_PROFILES` and
   `CONFIG_DIRECTORY`; nothing here becomes a pod `env` entry.
2. **A definition document is mounted configuration, not a Secret.** It names things
   and carries no credential. A capacity document carries dimensions, attributes, and
   pool ids — nothing secret — so it renders into the chart's existing ConfigMap.
3. **The path is derived from the document's presence, never configured beside
   it.** Helm sets `relay_definitions_path` only when `definitions.relays` is
   non-empty, because two independent settings can disagree silently: the document
   renders and mounts while the service skips an unset path.
4. **Wiring must not change what an existing deployment means.** That is why Helm
   does not wire `pool_definitions_path`: doing so would subject every deployment's
   pools to declarative reconciliation.

So the provisioning chart gains `definitions.capacity`, empty by default. The value
is copied verbatim into the ConfigMap as `capacity-definitions.yaml` and read by the
startup import on initialization — applied when its digest differs from the last one
applied, so a pod restart with an unchanged value is a no-op:

- when non-empty, `configmap.yaml` renders it as `capacity-definitions.yaml` and sets
  `capacity_definitions_path: /app/config/capacity-definitions.yaml` in the rendered
  config, and `deployment.yaml` mounts that key by `subPath`, each guarded by the same
  condition the relay entries use;
- `values.schema.json` forbids `config.capacity_definitions_path`, so the only way to
  enable the import is to supply the document the path points at;
- the empty default renders nothing and sets no path, so an existing deployment's
  meaning is unchanged — convention 4 is satisfied by default rather than by
  omission, which is why capacity can be wired where pools were not.

`settings.toml` gains `capacity_definitions_path = ""` with a comment stating the
digest-gated behaviour. Its adjacent `pool_definitions_path` and `inventory_ini`
comments currently describe every-startup upserts the code no longer performs; they
are corrected in the same edit, since a reader comparing the three would otherwise
conclude capacity is the odd one out.

**Pools are wired the same way (decided 2026-09-21).** A capacity document may name
non-default pools, and Helm did not wire pool documents, so on a fresh install such a
pool would not exist at first boot: the capacity import fails, startup fails, and the
operator cannot reach the API to create the pool. The chart therefore also gains
`definitions.pools`, empty by default, rendered as `pool-definitions.yaml`, mounted by
`subPath`, and setting `pool_definitions_path` only when non-empty, with
`config.pool_definitions_path` forbidden in the schema. The reason pools were left
unwired — that wiring would newly subject every deployment's pools to declarative
reconciliation — does not apply to an empty-by-default value: nothing is reconciled
until an operator supplies a document, and an operator who does is asking for exactly
the pool rule (unnamed pools are disabled). The values file's comment explaining the
old absence is replaced. The startup order already runs pools before capacity, so a
first boot from both documents resolves. The rejected alternatives were documenting
that a Helm capacity document may name only pre-existing pools, and demoting an
unknown pool to a startup warning; the second breaks the fail-startup posture relay
import already takes.

Compose wires no capacity or pool document. Compose's only user is the e2e suite,
and that use is temporary until a Tekton pipeline replaces the current GitHub
Actions; the scenarios declare capacity through the REST API by design
(`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`). The mounted-document
path is covered by integration tests of the importer and by Helm render tests, and
gains deployed coverage when the pipeline runs against the chart.

There is no CLI deliverable. Site administrators configure through values files,
configuration files, and the REST API; the operator documentation names the
endpoints and shows a document.

### Projected attributes are the declaration's, plus host connection fields (decided 2026-09-21)

Every declaration attribute is copied into the resource-pool projection except
`bare_metal_publication`, which is already published as the `bare_metal.v1` view.
The host's connection fields `public_host` (and `host_id` itself, as correlation) are
written last so a declaration cannot override them. `attributes.gpu_count` is
removed; the quantity lives in `capacity`.

The inventory the owner reviewed (searched 2026-09-21), with the post-`unify-host-identity`
names:

| Key | Written by | Read by | Under this decision |
|---|---|---|---|
| `host_id` | declaration field, not an attribute | `executor_ref`; providers; correlation | from the host, via correlation |
| `public_host` | never on a declaration | tenant connection info | from the host, written last |
| `gpu_model` | e2e, derivation | claims (equality); reconciler | from the declaration |
| `region` | e2e | claims (equality) | from the declaration |
| `physical_host_id` | declarations (top level after `unify-host-identity`) | ledger cross-mode accounting | from the declaration |
| `allocation_mode` | declarations (top level after `unify-host-identity`) | ledger cross-mode accounting | from the declaration |
| `bare_metal_publication` | bare-metal declarations | bare-metal provider; `bare_metal.v1` view | excluded — published as the view |
| `sla` | none found on a declaration | storefront-local rows only | from the declaration if present |
| `gpu_count` | none as an attribute | storefront-local readers only | removed |

Everything a declaration carries in `attributes` is therefore public to storefronts;
the operator documentation says so. Every key except the host link already reached
storefronts through the capacity-bucket projection's `grouping_attributes`, so an
allowlist here would protect nothing and would need editing whenever a domain added a
match field.

**Why `gpu_model` does not sit beside `gpu_count` in `capacity`.** The owner found the
split odd; it is deliberate at the ledger and deliberately *not* the authoring shape.
`capacity` is arithmetic: the ledger parses every value as a non-negative decimal and
subtracts held quantities per key to compute availability, so a categorical value
cannot live there. `attributes` are matched by equality. The two describe the same
GPUs, and `structured-capacity-requirements` already owns the grouping the owner
expects: a family-grouped authoring shape (`gpu: {count, model}`) that one shared
utility flattens into `dimensions["gpu_count"]` and `attributes["gpu_model"]`, for
claims and declarations alike. That change explicitly asks work landing earlier to use
the flattened form rather than a one-off nested shape, so the capacity-definitions
document here uses the flat form and gains the grouped form when that utility lands.

## Risks / Trade-offs

- **[Derivation produces capacity resources an operator did not intend]** → Derive
  only for hosts with GPU data and no correlated declaration under the projection's
  own rule, never overwrite an existing one, and report the derived set at INFO the
  way both existing seeding steps already report theirs.
- **[A derived declaration makes an INI host reservable]** → Intended; see "Derived
  declarations are admissible". The pool's offering-mode declaration still gates
  admission, so a pool declaring no mode sells nothing.
- **[Bare-metal publication view breaks across the derivation]** → The view is built
  from `resource.attributes[bare_metal_publication]` and `capacity`; a derived
  resource has no `bare_metal_publication` attribute, so it projects no view — the
  same as today for a host without one. Cover it with a focused test rather than
  assuming, since the view's `_whole_resource_available` check reads `capacity` and
  `available` together and the derivation changes where `capacity` comes from.
- **[Two seeding idioms in one file invite confusion]** → Document the reason for the
  difference at the new step: hosts seed only into an empty registry, while
  definition documents reconcile when their digest changes. "Why does this one run
  when the other skips" is exactly the question a reader will have.
- **[`available` key semantics change for derived rows]** → `_project_host` omits
  `available` only when `capacity_resource is None`. After derivation, hosts that
  previously projected no `available` will project one. The reconciler treats a
  present-but-empty `available` differently from an absent one ("ignorance is not
  zero" versus a loaded authoritative answer), so this needs explicit test coverage
  on the storefront side, not just the provisioning side. This is the highest-risk
  item in the change. After the 2026-09-21 decisions every projected row carries
  `available`, because every projected row now has a declaration; the absent-key
  case survives only in the reconciler's handling of older producers.
- **[Operators upgrade with a capacity file that disagrees with their hosts]** →
  Declared capacity wins; the derivation never overwrites. Worth an explicit
  operator-facing note, since the intuition may run the other way.

## Migration Plan

Amended 2026-09-21: derivation no longer runs as a startup scan, and the compute
migration also relaxes `total_units` and backfills `pool_id`.

1. Make the mirror dimension composition-supplied, `total_units` optional, and
   `pool_id` required at the ledger and on the wire. Compute migration: make
   `capacity_buckets.total_units` nullable and backfill `NULL` `pool_id` to the
   default pool. API-credits databases are recreated.
2. Add the pool reassignment drain rule.
3. Add the capacity-definitions document, the in-session reconciliation, the startup
   step, and the REST import — inert until an operator supplies a document or calls
   the endpoint.
4. Add the host-to-declaration derivation, wire it into `seed_from_ini`, and run it
   once as an ordered compute migration for hosts already present.
5. Redirect `_project_host` to read capacity and attributes from the declaration
   only, removing the host fallback and fixing the divergence together.
6. Deployment wiring and operator documentation.

Rollback within the freeze window is a code rollback. Derived rows remain and are
read by the restored reader as ordinary declarations; a nullable `total_units` is
read by the restored reader through its existing `or 0` handling, which is the one
place a rolled-back reader sees a value it did not write. Rolling back past the
migration is not supported, per `deployment-state`'s forward-recovery posture.

## Open Questions

### Open

- **Should the scalar `total_units` / `units` mirror be retired entirely?** It predates
  multidimensional capacity and is the only reason a mirror dimension must exist.
  Deferrable: making the dimension name composition-supplied removes the cross-domain
  defect without the schema change, and retiring the scalar touches every legacy
  single-quantity caller.
- **"Ledger" is a misnomer for `CapacityLedgerService` and `kit/site/ledger.py`**
  (repository owner, 2026-08-06). A ledger is append-only; this is mutable reservation
  state with an adjacent `CapacityEvent` table that genuinely is append-only. Recorded
  here because this change touches the module heavily. Not renamed: it is pure churn
  across kit, provisioning, specs, and tests with no capability behind it, and it should
  ride with a change that has reason to touch those call sites anyway.
- **Does the capacity definitions document need a canonical export**, the way
  `ResourcePoolService.export_pools_yaml` supports round-tripping pool state? Useful
  for operators who declare through the API and want a file, but not required by
  anything in this change's scope, and deferrable without affecting the specs, the
  approach, or the task breakdown.
- **Should derivation be permanently retained or removed with the later `DROP`?** The
  design assumes removal alongside the INI's GPU variables, but the deprecation
  window's length is a deployment-policy question this repository has deliberately
  declined to fix in advance elsewhere (see `pools-9`'s note on having no fleet-wide
  deployment signal). Decide when the `DROP` follow-up is opened.
