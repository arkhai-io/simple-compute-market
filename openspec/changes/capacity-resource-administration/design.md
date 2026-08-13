# Design

## Context

See `proposal.md`'s "Why" for motivation. This section records what was verified
directly against the code during the investigation (2026-08-06), because most of it
is not stated in any existing specification and the conclusions below depend on it.
Re-verify anything load-bearing before implementing; the codebase will have moved on.

### What the provisioning service seeds today

| Concern | Seeding path | Runtime API | Idempotence |
|---|---|---|---|
| Hosts | `app_runtime.seed_inventory_if_empty` from `inventory_ini` or `resolved_inventory_path` | `POST /api/v1/hosts` and siblings, `POST /api/v1/hosts/import` | Skipped entirely when the table is non-empty; `/hosts/import` always upserts |
| Resource pools | `app_runtime.import_pool_definitions_if_configured` from `resolved_pool_definitions_path` | `POST`/`PUT`/`PATCH /api/v1/pools` | Diff-based, runs at **every** startup |
| Sellable capacity | **none** | `PUT /api/v1/capacity/resources/{resource_id}` only | n/a |

The registered startup steps are `apply-ansible-config`,
`initialise-container-resources`, `resolve-request-path-services`, `seed-inventory`,
`import-pool-definitions`, `create-job-queue`. Nothing creates capacity resources and
nothing derives them from hosts.

The two seeding paths differ deliberately and the difference is instructive. Host
seeding is skip-if-non-empty so operator edits made through the API survive a pod
restart. Pool import is unconditional-but-idempotent, and its in-code comment states
why: because `import_pools` is diff-based, re-running it every startup is the correct
behavior rather than a re-seeding hazard. Capacity definitions are a declared
inventory in the same sense pool definitions are, so this change follows the pool
idiom, not the host one — see "Decisions".

### Why a host-only deployment still works today

`capacity_inventory._project_host` supplies a fallback. With no matching capacity
resource it projects `resource_id` from `host.name`, `pool_id` from `host.pool_id`,
`resource_type` as `"compute.gpu"`, and `capacity` as `{"gpu_count": host.gpu_count}`.
It omits the `available` key entirely, which the VM reconciler reads under its
"ignorance is not zero" rule as unknown-therefore-fully-available, corrected
authoritatively at reserve time.

This is why the gap has been invisible: the fallback silently substitutes host GPU
count for a capacity declaration, and GPU count is the only dimension anything
publishes today.

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

## Goals / Non-Goals

**Goals:**

- One authoritative home for sellable capacity inside the provisioning service.
- An operator path for declaring it that matches an idiom already proven in the same
  file.
- A migration that costs existing INI-seeded deployments nothing at upgrade.
- Leave admission, matching, and scheduling untouched.

**Non-Goals:**

- Designing the negotiation or pricing surface over the new dimensions.
- Choosing final requirement/claim vocabulary; `structured-capacity-requirements`
  owns that and this change uses the dimension names `arkhai_vms` already defines.
- Deciding how the storefront presents multidimensional listings.

## Decisions

### Capacity resources are the single home for capacity; hosts are executor identity

Two options were considered.

**Rejected — extend `Host` with vCPU/RAM/disk columns.** Fewest moving parts: INI
seeding would then cover every dimension and `_project_host`'s fallback would work
unchanged. Rejected because `Host` is executor identity — SSH user, key material,
Ansible alias, addressing — and folding sellable capacity into it conflates two
concerns the system already separates elsewhere: the bare-metal publication view is
built from a capacity resource's attributes, not from host columns, and
`load_capacity_resource_inventory`'s own docstring already states that "capacity
resources are authoritative for availability and Physical Resource identity" while
"host rows supply only executor inventory needed to correlate the configured machine
alias." The code has the boundary; only the data has drifted across it. An Ansible
INI is also a poor carrier for capacity declarations, since it exists to describe how
to reach a machine.

**Accepted — capacity resources own every dimension, hosts own executor identity.**
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
(`config.py`'s `resolved_*_path` property, empty string meaning unset), the import is
diff-based and idempotent, it runs on every startup, and it raises on a configured
path that does not exist rather than silently skipping — all matching
`import_pool_definitions_if_configured`. Choosing the host idiom (skip-if-non-empty)
instead would make an operator's declared capacity file silently inert after the
first boot, which is the failure mode the pool import's own comment was written to
avoid.

Ordering within `startup_steps()` matters: capacity import must run after
`import-pool-definitions`, because a capacity resource names a `pool_id` and the
pool must exist first.

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

### The INI keeps its GPU variables as derivation input, not as capacity

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
writing it when the caller declared capacity explicitly. Retiring the scalar is a schema
change touching every legacy single-quantity caller, and is recorded below as deferred
rather than folded in.

### Pool membership is executor-derived, and one-per-executor is enforced on write (added 2026-08-11)

Two related defects surfaced while tracing an e2e capacity failure, and both belong here
because this change already rewrites `register_resource` and `capacity_inventory.py`.

**One declaration per executor is enforced in a read path.**
`load_capacity_resource_inventory` raises `ValueError` when two capacity resources
correlate to the same host identity. The invariant is right — `site-capacity`'s internal
accounting states one current bucket per host for the VM domain, and a second
declaration on one machine sells the same hardware twice — but a read path is the wrong
place to hold it. One bad write makes `GET /site-resource-pools` return 500 for every
reader at that site, for every pool, indefinitely, and a storefront cannot distinguish
that from the site being unreachable. Rejection moves to registration. The read-path
check degrades to a logged warning that omits the ambiguous correlation, so a row that
predates the write-time guard cannot take a whole site's projection down; an
under-reported row is recoverable, a poisoned projection is not.

**Pool membership has two independently writable homes.** `Host.pool_id` is `NOT NULL`
and defaults to the system pool; `CapacityBucket.pool_id` is nullable and set only when a
caller supplies it. `_project_host` reconciles them for the resource-pool projection with
`resource.get("pool_id") or host.pool_id`, while admission reads
`resource_feasibility_view(pool_id=resource.pool_id)`, which falls back to
`pool_id or resource_id`. One declaration can therefore have three pool identities at
once — the host's pool in the projection, its own id at admission, and whatever an
operator wrote into `attributes["pool_id"]`, which nothing reads at all.

Accepted: a declaration correlated to an executor inherits that executor's pool, and a
declaration naming a different pool is refused rather than silently overridden. Adding
the executor to a pool becomes the single act that establishes membership. A declaration
with no executor — a logical quota, for instance — keeps whatever pool it declared, so
non-physical domains are untouched.

`attributes["pool_id"]` is rejected outright rather than hoisted into the field. Hoisting
would leave two spellings working forever and preserve exactly the ambiguity above; the
error tells the operator which field to use. Rejecting it also makes
`resource_feasibility_view`'s overwrite unreachable-by-conflict, so the
`pool_id or resource_id` fallback stays as it is — it remains load-bearing for the
structural listing-mode default, where a declaration with no pool is its own
single-member pool.

`kit/site` must not learn what a host is. The executor correlation is injected at
composition, matching the two providers `make_capacity_router` already accepts, and the
attribute naming the executor is composed in the way `unit_claim_keys` already is —
`ledger.py` reads `attributes["vm_host"]` directly in two places today, which is a
pre-existing domain leak this section removes rather than adds a third instance to.

Rejected — resolve membership only through the executor and drop
`CapacityBucket.pool_id`. Logical resources have no executor and would lose pool identity
entirely, and `capacity_bucket_projection` needs a grouping key.

Rejected — require `pool_id` on every declaration. The API-credits composition registers
a quota with no pool, so requiring it breaks a non-physical domain to tidy a physical one.

## Risks / Trade-offs

- **[Derivation produces capacity resources an operator did not intend]** → Derive
  only for hosts with GPU data and no existing capacity resource, never overwrite an
  existing one, and report the derived set at INFO the way both existing seeding
  steps already report theirs.
- **[Bare-metal publication view breaks across the derivation]** → The view is built
  from `resource.attributes[bare_metal_publication]` and `capacity`; a derived
  resource has no `bare_metal_publication` attribute, so it projects no view — the
  same as today for a host without one. Cover it with a focused test rather than
  assuming, since the view's `_whole_resource_available` check reads `capacity` and
  `available` together and the derivation changes where `capacity` comes from.
- **[Two seeding idioms in one file invite confusion]** → Document the reason for the
  difference at the new step, since "why is this one unconditional" is exactly the
  question a reader will have and the pool import already answers it for itself.
- **[`available` key semantics change for derived rows]** → `_project_host` omits
  `available` only when `capacity_resource is None`. After derivation, hosts that
  previously projected no `available` will project one. The reconciler treats a
  present-but-empty `available` differently from an absent one ("ignorance is not
  zero" versus a loaded authoritative answer), so this needs explicit test coverage
  on the storefront side, not just the provisioning side. This is the highest-risk
  item in the change.
- **[Operators upgrade with a capacity file that disagrees with their hosts]** →
  Declared capacity wins; the derivation never overwrites. Worth an explicit
  operator-facing note, since the intuition may run the other way.

## Migration Plan

1. Add `capacity_definitions_path`, its resolution, and the import step — inert until
   an operator configures it.
2. Add the host-to-capacity-resource derivation, used by both the migration and the
   startup step.
3. Run the derivation as an ordered migration so existing deployments are populated
   before the application serves requests.
4. Redirect `_project_host` to read capacity and attributes from the capacity
   resource only, removing the host fallback and fixing the divergence together.
5. Promote the registration endpoint's documentation and add CLI plus quickstart
   coverage.

Rollback within the freeze window is a code rollback. Derived rows remain and are
ignored by the restored reader.

## Open Questions

- **Should the scalar `total_units` / `units` mirror be retired entirely?** It predates
  multidimensional capacity and is the only reason a primary dimension must exist.
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
- **Should the derivation step be permanently retained or removed with the later
  `DROP`?** The design above assumes removal alongside the INI's GPU variables, but
  the deprecation window's length is a deployment-policy question this repository has
  deliberately declined to fix in advance elsewhere (see `pools-9`'s note on having
  no fleet-wide deployment signal). Decide when the `DROP` follow-up is opened.
- **Should host capacity be gathered rather than declared by hand?** (Repository owner,
  2026-08-11.) This change gives an operator an authoritative place to declare
  multi-dimensional capacity, but asking a datacenter administrator to type vCPU, RAM,
  and disk totals per machine is a poor operator experience when Ansible can read them
  off the host. Most of the machinery already exists:
  `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-check.yml` already
  returns per-host total, allocated, and available vCPU, RAM in MB, GPU count, and GPU
  model strings as structured JSON, and `check_capacity` already exposes it through the
  job queue as a diagnostic read. Nothing writes that output into a declaration. Wiring
  it to propose a declaration for operator confirmation would close the ergonomic gap
  without reintroducing the host as a capacity authority — the gatherer writes the one
  authority, it does not become a second record read at projection time, which is the
  same role this design already assigns the INI's `gpus=` variable. Two caveats before
  this is scoped: `lspci`-derived model strings are not the categorical `gpu_model`
  vocabulary a claim matches on, so a mapping step is required rather than a copy; and
  gathered totals describe the machine, not the portion of it a seller intends to sell,
  so the operator confirmation step is the substance of the feature rather than a
  formality. Deferrable: the declaration surface is the prerequisite and gathering is
  purely additive to it.
