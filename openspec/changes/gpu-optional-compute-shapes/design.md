# Design: GPU-optional compute shapes

## Context

- **Host records.** `HostCreate`, `HostUpdate`, and `HostResponse`
  (`provisioning/compute/contracts/src/compute_provisioning_contracts/hosts.py`) carry
  `gpu_count` and `gpu_model`; the `hosts` table stores them
  (`provisioning/compute/src/compute_provisioning/hosts/db.py`); the INI parser maps
  `gpus=` and `gpu_model=` onto them
  (`provisioning/compute/ansible/src/compute_provisioning_ansible/inventory.py`). In
  production code only the host authority stores and returns them. The upgrade migration
  `20260921_004` read them once to derive declarations; no host write declares capacity.
- **The compute schema.** `COMPUTE_CAPABILITY_SCHEMA`
  (`domains/compute/src/arkhai_compute/capability_schema.py`) marks `gpu.count` and
  `gpu.model` `required=True`, and the shape kit
  (`kit/capability-shape/src/market_capability_shape/__init__.py`) reads `required` as
  "present in every shape". It is the only schema that uses `required`.
- **VM publication** assumes GPUs end to end: the `VmListing` validator and
  `ComputeResource` require both fields, resource dispatch recognises compute by a
  `gpu_model` key, `resource_is_compute` is `"gpu_model" in resource`, the reconciler
  drops a member without `gpu_count` before feasibility and groups pricing by
  `shape.gpu_model`, the Alkahest delivery facts always write both fields, and the admin
  reserve route reports `allocated_gpu_count or 1`.
- **Bare metal.** Derivation is schema-driven; `BareMetalListing` requires both fields,
  `claimed_attributes` emits every schema attribute, and `whole_machine_claim` refuses
  empty claimed attributes.
- **The registry.** `core/registry/filter-spec.yaml` (version 6) requires
  `listing_resource.gpu_model`. Only the dry-run `validate-publish` route enforces the
  listing schema; the GPU filters are `on_missing: fail`.
- **Resource type.** A claim names one resource type, matched by equality at admission and
  scheduling. VM claims always name `compute.gpu`; bare metal declares and schedules
  `compute.bare-metal`, which restates its offering mode.
- **What already copes.** The VM requirement delegate sets no GPU variables without a
  `gpu_count` dimension and the playbook attaches no GPU; pool VM defaults cover RAM,
  vCPU, and disk only; the site ledger stores `units=0` with the real dimensions; the
  admissibility kit judges policies under a schema with nothing required; `linear_price`
  prices only the families a shape names.

## Goals and non-goals

Goals: a host record describes how to reach a machine and nothing about its hardware; a
VM or bare-metal shape without GPUs can be declared, published, filtered, claimed, and
fulfilled.

Non-goals: deriving shapes from host facts; changing admission, scheduling, provisioning,
or the claim vocabulary; introducing new resource types; any migration of bare-metal
persisted state, since bare metal has not launched.

## Decisions

### D1. A required field is required when its family appears

The shape kit's `ShapeField.required` means "required whenever the shape names this
field's family". The compute schema keeps `gpu.count` and `gpu.model` marked `required`,
so a compute shape names both or neither: `{cpu: {count: 8}, memory: {gib: 32}}` is valid,
`{gpu: {count: 2}}` and `{gpu: {model: H100}}` are refused. No family is required.

*Rationale.* A GPU commitment always names how many and which model. The refusals that
exist today survive: a model with no count would publish `gpu_model: H100` on a listing
whose claim reserves and whose fulfillment attaches no GPU, and a constraint stated with
no `offer` (`gpu.count: {min: 2, max: 8}`) still leaves the base shape unreadable, holding
the pool, because the admissibility kit reads base shapes under the real schema. Only the
compute schema uses `required`, shapes valid today stay valid, and digests do not move.
Every compute shape still carries a quantity.

*Rejected.* Plain optional fields, which admit the model-only shape above and turn a
missing `offer` into a silent publication. A compute-only check outside the kit, which
breaks the one-implementation rule for shape validation and which the admissibility
kit's base-shape read would not see. Also adding a `required_families` list, which
nothing needs, and letting `gpu.count` stand without `gpu.model` ("GPUs of any model"),
which no product asks for.

### D2. The VM default stays GPU-only, and a pool that yields nothing is reported once

The default generator yields GPU-only shapes from members declaring a GPU count and model,
as today. A member declaring no GPU yields no default shape and is not reported. When a
pool states no listing shapes and no enabled member declares a GPU, the pool is reported
once, saying the VM default generates GPU shapes only and that the pool must state
`listing_shapes`. A seller sells CPU-only VMs by stating shapes on the pool hint or a
storefront override.

*Rationale.* A CPU slice has no natural unit to enumerate. Every existing pool publishes
exactly what it publishes now. A pool may legitimately publish nothing so long as its
operator can easily discover why. The generator stays the domain's seam for another
default policy.

*Which pools are reported.* The report's condition is the delta's: no stated shapes, and no
enabled member declaring a positive GPU count. So a pool whose members all declare
`gpu_count: 0` is reported, as one whose members declare none is; a zero-count member beside
a GPU member is silent, as a member is never reported on its own account. A pool with no
enabled member is not reported: it publishes nothing for want of members, which stating
shapes would not change.

*Rejected.* Enumerating vCPUs, which publishes on the order of two hundred listings per
large host and leaves the memory each slice is given unreserved at scale, and which must
also decide whether GPU members sell CPU slices by default. One whole-member shape per
member, which sells a machine as one VM, rarely what a VM seller wants. A ratio ladder,
which commits to a ratio nobody stated.

### D3. The registry's listing schema requires only `region`

`core/registry/filter-spec.yaml` moves to `version: 7` and its `listing_resource` requires
`[region]`; `schema` stays `{id: compute.market, version: 2}`. The filters are unchanged:
the GPU filters stay `on_missing: fail`, so a GPU-less listing is excluded from every GPU
query and appears in queries that name no GPU term. No filter selects GPU-less supply.

*Rationale.* The published contract would otherwise call valid supply invalid, and the
dry-run route the e2e flows call would refuse it. A buyer after GPU-less supply bounds
the dimensions it needs and orders by price, which `market buy`'s price-ranking
aggregation policies already do. A consumer relying on `gpu_model` being present is the
backwards incompatibility the version records; an older buyer's cached ETag is refused and
it refetches. The identity is unchanged, so `schema.version` is too.

*Rejected.* A `has_gpu` existence filter, which also needs the evaluator to judge absence
itself: today a listing the path resolves nothing for is decided by `on_missing` before
an `exists` test runs, so `exists:false` matches nothing. Keeping the requirement.
Enforcing the whole schema at publish, a larger decision about listings already accepted.

*The publish requirement (10 F4).* `registry-discovery`'s "Schema-driven listing validation"
says an ordinary publish validates against the listing shape; the publish route refuses only
the retired spellings. That gap predates this change, and nothing here depends on it.
`store-registry-listings-as-published` names it and chooses whether publish enforces the
specification, so its delta reconciles the requirement; this change's delta leaves it alone
rather than fixing the current behaviour as normative while it is under design.

### D4. Every VM declaration keeps the `compute.gpu` resource type

GPU-less VM declarations are declared `compute.gpu`, and VM claims name `compute.gpu` for
every shape. A stated CPU-only shape lands on any member that fits it, a GPU host
included, so a GPU machine's spare vCPU and memory sell as VMs: the mechanisms are
neutral, and nothing forbids it.

The resource type is meant to become the category of compute shape — `compute.gpu`,
`compute.cpu`, `compute.db` — orthogonal to the offering mode, with a scheduling cursor per
category. That is direction, not current behaviour, and is recorded as a roadmap gap, as
is bare metal's use of `compute.bare-metal` to restate its offering mode, on which its
scheduling request depends.

*Rejected.* `compute.cpu` now, chosen by the VM claim from the shape: a CPU-only shape
could then never use a GPU host's spare capacity, since a claim names one kind and a host
carries one declaration. A claim naming several kinds, which changes admission and the
claim vocabulary. Renaming `compute.gpu`, which is the right name for GPU capacity.

### D5. The host GPU fields are retired

- **Storage.** The provisioning service's migration drops `hosts.gpu_count` and
  `hosts.gpu_model` by rebuilding the table from the model, following
  `20261023_002_hosts_pool_optional`. It logs nothing per host.
- **Upgrade (10 F3).** The upgrade is fail-forward: an older provisioner maps both columns
  and cannot read the rebuilt table, and its migration IDs are recorded as applied, so
  rolling the provisioning service back past this release means restoring its pre-upgrade
  database backup. `DEPLOYMENT_AND_CONFIG.md` states this beside the other fail-forward
  upgrades.
- **API.** `HostCreate`, `HostUpdate`, and `HostResponse` lose both fields. A request
  that still sends them is accepted with the fields ignored, as the models ignore any field
  they do not define.
- **INI.** `gpus=` and `gpu_model=` are no longer read; like every variable the parser does
  not read, they are ignored without a warning.
- **The one non-production reader.** The e2e host harness
  (`e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`) decides whether to update an
  existing host by comparing its GPU count and pool; with no GPU field to read, it compares
  the pool alone.

*Rationale.* Declarations already state every dimension a site sells, and every host
with GPUs at upgrade received a declaration then. Refusal or warning code would stay
until something retires it, while the failure it guards against — an operator expecting a
field that affects nothing to be recorded — is easily diagnosed and fixed. The same
weighing was made for the migration's log line. Each retirement is judged case by case;
no general rule is adopted.

The drop departs from `ARCHITECTURE.md`'s expand/contract rule for non-additive schema
changes, whose only stated exception is a disposable-database reset contract. That rule
protects old and new readers that coexist and a rollback after a failed deployment. No two
provisioner versions share the database: the chart deploys with `strategy: Recreate`
over one ReadWriteOnce volume, and one operator upgrades sites and storefronts together
(`ARCHITECTURE.md` "Operators"). What remains is rollback, which the upgrade note above
answers with the pre-upgrade backup, as this service's earlier single-release column drops
did.

*Rejected.* Refusing the two names with 422 naming capacity declarations, and warning per
host on an INI parse. Retaining the columns, unread, for a release and dropping them in a
later one: a safe `helm rollback`, bought with two dormant mapped columns and a follow-up
drop that needs an owner. Keeping the fields as descriptive, which contradicts
declarations being the one statement of hardware.

### D6. VM listing models and resource dispatch

`ComputeResource.gpu_count` and `gpu_model` are optional, and the `VmListing` validator
checks D1's rule by flattening the listing's fields through the compute schema rather than
restating it.

*Dispatch (10 F1).* One rule decides a resource payload's kind at every seam that decides
it: `Resource.parse_from_dict`, `resource_is_compute`, and the adapter registry's
`parse_resource_from_dict`, which storefront publication calls. An explicit
`resource_type` selects its adapter; otherwise a payload with a `token` key is a
`TokenResource` and any other mapping is a `ComputeResource`. The compute adapter stops
discriminating on `gpu_model`, so a GPU-less candidate, which carries neither
`resource_type` nor `gpu_model`, reaches compute validation. `ComputeResource` refuses a
mapping whose shape, flattened through the compute schema, is empty: the shape kit's
refusal of an empty shape (D1), not a separate check. Stored VM listings all carry
`gpu_model` and parse as before, so nothing migrates. The buyer CLI's resource display
(`arkhai_vms_listings/buyer_cli.py`, `format_resource`), which also recognises compute by a
`gpu_model` key, follows the same rule.

*Serialization (10 F2).* The resource's serializer omits an absent `gpu_count` and
`gpu_model` as it already omits an absent `asking_rate`, so a GPU-less listing carries no
GPU key, rather than `null`, when stored, refreshed, and published. The refresh
comparison reads a missing key and a stored `null` alike, so no stored listing churns.
Other absent optional fields still publish as `null`; that is a recorded gap, not this
change's.

*Rejected.* Dispatching on `region`, which couples parsing to a field derived from a pool
hint; requiring an explicit `resource_type` on every payload, which stored listings lack.
Publishing `null` GPU fields, which contradicts the listing publishing no GPU field and
which the registry's dry-run refuses, since it types a present `gpu_model` as a string.

### D7. Bare metal

`BareMetalListing.gpu_count` and `gpu_model` are optional, with D1's rule checked through
the schema, and `claimed_attributes` returns only the attributes the listing states.
`whole_machine_claim` refuses an absent `claimed_attributes`, a broken trusted record, and
accepts an empty one, since the claim still pins the Physical Resource and one `units`. A
declaration stating only `units: 1`, or `gpu_count: 0`, stays unresolvable and reported by
name: the shape kit refuses an empty shape and a non-positive quantity, so an operator
states no GPUs by omitting them. Bare-metal persisted state changes without migration.

*Rejected.* Reading `gpu_count: 0` as "no GPUs", which substitutes a meaning for a declared
value the vocabulary cannot carry.

### D8. VM publication

A member's GPU count is no precondition for membership: the site predicate's feasibility
decides, against declared capacity and, for a backed listing, the availability of the
dimensions each shape declares; GPU bookkeeping applies only to shapes that name GPUs. A
malformed `gpu_count` still holds the pool. Pricing groups by an optional model: a
GPU-less shape resolves flat rates or cpu, memory, and storage family rates, and a pool
whose only rates are per GPU model leaves it without a settlement option, refused and
reported as `no_settlement_option`. The per-member omission report is replaced by D2's
pool report.

*Rejected.* Dropping GPU-less members unless a pool states shapes, which makes membership
depend on the shape source.

### D9. Claim, recheck, opening, delivery facts, admin reserve

Claim building already copies only the attributes a listing states. The seller's recheck
and the negotiation opening use D6's `resource_is_compute`. The Alkahest delivery facts'
lease terms omit each GPU key the listing does not state. The admin reserve response's
`gpu_count` is optional and absent for a GPU-less reservation, the `or 1` fallback goes,
and the storefront client's `gpu_count` default of `0` becomes optional.

*Rejected.* `null` values in the lease terms, which state a value nothing committed;
recording the full shape there, which is outside this change.

### D10. Admission, scheduling, and fulfillment are unchanged

Admission treats a dimension a claim does not request as not requested, so a GPU-less
claim fits a GPU host (D4); the requirement delegate and playbook attach no GPU; the
ledger's unit mirror records zero. Placement ranking across sites reads the GPU mirror,
which never decides a VM claim because VM listings are pinned to one site.

### D11. Validation levels

- Unit: the kit's family-conditional rule; the compute schema's accepted and refused
  shapes; bare-metal derivation, listing, and claim; VM shape resolution and dispatch; host
  models without GPU fields; the INI parser.
- Integration: VM publication with GPU-less and mixed members and the pool report; the
  storefront's publication path accepting a GPU-less payload, still parsing a stored GPU
  listing, and refusing a compute mapping with no quantity; the exact registry body of a
  GPU-less VM listing, with no GPU key, on first publication and on refresh; the
  registry's `validate-publish` accepting a GPU-less listing and the GPU filters excluding
  it; the host API and the column-drop migration.
- System: the VM lane's listing-shapes scenario states a GPU-less shape that a `vcpu_count`
  query finds, a `gpu_count` query excludes, and a deal settles through mock provisioning;
  the bare-metal lane publishes a GPU-less machine that a `vcpu_count` query finds.

### D12. The storefront's report is where an operator discovers an empty pool

Every "nothing published" outcome above — D2's pool report, unresolvable bare-metal
declarations, `no_settlement_option`, infeasible stated shapes — reports in the
storefront's system status (`publication_derivation`). A site operator distinct from the
storefront's cannot see it; that remains the change index's unowned item "A site cannot
see why a storefront closed its pool's listings".

### Implementation cadence

Two rounds.

- **Round 1 — vocabulary, contracts, bare metal, host retirement**, in two sessions:
  (A) the kit's family-conditional `required`, the compute schema, the bare-metal listing,
  claim, and derivation, filter spec version 7, and the bare-metal lane's GPU-less
  publication scenario; (B) the host models, the INI parser, the column-drop migration,
  the e2e host harness, and operator documentation. Between the rounds the tree accepts
  GPU-less shapes the VM reconciler cannot yet publish; no deployment or lane states one
  until round 2.
- **Round 2 — the VM path**, in one session: listing models and dispatch, the reconciler,
  claim building, the recheck and opening, delivery facts, the admin reserve response, and
  the VM lane's GPU-less listing-shapes scenario through settlement.

## Risks and trade-offs

- A stated CPU-only shape in a pool of GPU hosts consumes their vCPU and memory, which can
  leave GPUs that no remaining CPU can serve. That is the operator's choice of shapes, as
  any omitted dimension is.
- A GPU-less listing is invisible to buyers who filter on GPU fields, by design.
- Dropping the host columns discards GPU values recorded on hosts after the upgrade
  derivation; they were never sellable. A `helm rollback` of the provisioning service past
  this release does not recover by itself: the older image cannot read `hosts` until its
  pre-upgrade backup is restored.

## Migration

The provisioning service rebuilds `hosts` without the two columns; the upgrade is
fail-forward, and a rollback past it restores the pre-upgrade database backup (D5). No
storefront, registry, or bare-metal migration; the registry's filter spec version changes.

## Open Questions

None.
