## Why

A capacity declaration owns every dimension a site sells
(`openspec/specs/site-capacity/architecture.md`), yet a host record still carries
`gpu_count` and `gpu_model`, which duplicate its declaration. Since
`seed-default-pool-at-runtime` stopped deriving declarations from host inventory, nothing
in production reads those host fields: they are stored and returned, and describe hardware
a declaration already states.

The compute capability schema makes `gpu` its one required family
(`domains/compute/src/arkhai_compute/capability_schema.py`), and the VM listing pipeline,
the bare-metal listing model, and the compute registry's listing schema all assume a GPU,
so a site cannot state, publish, or sell a VM or bare-metal shape for a machine without
GPUs.

## What Changes

- Retire the host's `gpu_count` and `gpu_model` from the host API (`HostCreate`,
  `HostUpdate`, `HostResponse`) and from the INI inventory format (`gpus=`, `gpu_model=`),
  with a provisioning migration that drops the columns; the upgrade is fail-forward, and
  rolling the provisioning service back past it restores its pre-upgrade database backup.
  Requests and inventories that still carry them have the fields ignored. A host's
  hardware is stated only by its capacity declaration.
- The capability-shape kit reads a field's `required` as "required when its family
  appears"; the compute schema then makes no family required while `gpu.count` and
  `gpu.model` appear together or not at all.
- VM publication, negotiation, settlement, and the admin reserve route accept shapes
  without GPUs. The VM default generator stays GPU-only, and a pool that states no shapes
  and whose members declare no GPUs is reported rather than silently empty.
- Bare-metal listings and claims accept machines without GPUs.
- The compute registry's listing schema stops requiring `gpu_model` (filter spec version
  7); its GPU filters keep excluding listings that state no GPU.
- Every VM declaration keeps the `compute.gpu` resource type, so a GPU machine's spare
  vCPU and memory can sell as VMs.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: the host record and the INI inventory format.
- `site-capacity`: projection text about host GPU fields, and what the resource type
  states.
- `market-composition`: the capability-shape kit's required fields and the compute
  schema's families.
- `storefront-publication`: VM default shapes, GPU-less VM members, and bare-metal shapes
  and claims without GPUs.
- `registry-discovery`: the compute listing schema's required fields.

### New Capabilities

None.

## Non-Goals

- Do not derive a full compute shape from host facts. An explicit,
  pool-targeted derivation from an Ansible fact run is its own change; this one
  stays compatible with it: declarations remain the only statement of what
  sells, and a derivation would produce ordinary declarations into a named pool
  as an operator's act.
- Do not change capacity admission, scheduling, provisioning, or the claim vocabulary
  (`settle-capacity-claim-vocabulary` owns the latter).
- Do not introduce new resource types (`compute.cpu`, `compute.db`) or change bare
  metal's `compute.bare-metal`; both are recorded as roadmap gaps.
- Do not add a registry filter selecting GPU-less supply.
- Do not migrate bare-metal persisted state: bare metal has not launched.

## Impact

- Host contracts, authority, and INI parser (`provisioning/compute/contracts`,
  `provisioning/compute/src/compute_provisioning/hosts/`, `provisioning/compute/ansible`),
  and a provisioning migration.
- The capability-shape kit (`kit/capability-shape`) and the compute schema
  (`domains/compute`).
- The VM listings, domain, settlement, and storefront packages: listing models and
  resource dispatch, the reconciler, claim building, the seller's recheck and opening,
  Alkahest delivery facts, and the admin reserve route; the storefront client's reserve
  model.
- The bare-metal domain and storefront: listing model, claimed attributes, and the whole
  machine claim.
- The compute registry's filter spec (`core/registry/filter-spec.yaml`).
- Operator documentation of host inventory and capacity declarations, the e2e host
  harness, and every test fixture that registers a host with a GPU count; a GPU-less
  scenario in the VM and bare-metal end-to-end lanes.

## Dependencies and Related Changes

- Builds on `seed-default-pool-at-runtime` (archived), which removed capacity derivation
  from host inventory, the host GPU fields' last reader.
- Takes two items from the unowned work found by `capacity-shape-envelope`: "A
  host's `gpu_count` duplicates the `gpu_count` of its capacity declaration" and
  "The compute schema requires `gpu.count` and `gpu.model`, so a VM or bare-metal
  listing without GPUs cannot be stated".
- Coordinates with `bring-host-inventory-under-definition-documents`, which
  changes how host inventory enters the registry: a host document it defines carries no
  hardware fields.
- Coordinates with `hollow-pre-floor-provisioning-migrations`: the column drop follows the
  migrations that add `hosts.gpu_model` and read `hosts.gpu_count`, and composes with
  their hollowing in either order.
- `pools-6-fair-scheduling-policy` owns scheduler improvements, including any cursor per
  resource category; nothing here depends on it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, `site-capacity`,
      `market-composition`, `storefront-publication`, `registry-discovery`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A required shape field is required when its family appears; the compute schema
  requires no family and binds `gpu.count` and `gpu.model` together →
  `openspec/specs/market-composition/spec.md` (deltas) and
  `openspec/specs/market-composition/architecture.md#the-compute-family-vocabulary`.
- The VM default stays GPU-only; a pool publishing nothing because it states no shapes and
  declares no GPUs is reported once; GPU-less members are members →
  `openspec/specs/storefront-publication/spec.md` (deltas) and
  `openspec/specs/storefront-publication/architecture.md#listing-shapes-and-the-storefronts-authority`.
- A pool may create no listings, provided its operator can easily discover why →
  `docs/development/ARCHITECTURE.md#holding-or-closing-a-listing-the-storefront-cannot-fully-derive`.
- A GPU machine's spare server resources may sell as VMs: the mechanisms are neutral and
  nothing forbids it → `openspec/specs/storefront-publication/architecture.md#listing-shapes-and-the-storefronts-authority`.
- Bare-metal machines without GPUs, and claims with no attributes →
  `openspec/specs/storefront-publication/spec.md` (deltas) and
  `openspec/specs/storefront-publication/architecture.md#bare-metal-listing-shapes`.
- The compute listing schema requires only `region`; GPU filters exclude GPU-less listings
  → `openspec/specs/registry-discovery/spec.md` (deltas).
- A host record carries no hardware description; retired fields are ignored →
  `openspec/specs/physical-provisioning/spec.md` (deltas), `openspec/specs/site-capacity/architecture.md#declared-capacity-and-connection-identity`,
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, and both seller quickstarts.
- The host column drop is a fail-forward upgrade whose rollback restores the pre-upgrade
  backup, and why the expand/contract rule does not govern it →
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, beside the other fail-forward upgrades.
- A VM listing resource carries no GPU key, rather than `null`, when its shape states no
  GPUs, and one dispatch rule decides a resource payload's kind →
  `openspec/specs/storefront-publication/architecture.md#listing-shapes-and-the-storefronts-authority`.
- Every other absent optional field of a VM listing resource publishes as `null`, where
  the specification says the field is not published → `docs/development/ROADMAP.md`
  (unowned gaps).
- The resource type is the category a claim matches by equality, `compute.gpu` for every
  VM declaration → `openspec/specs/site-capacity/spec.md` (deltas).
- The resource type as the compute-shape category (`compute.cpu`, `compute.db`), and bare
  metal's `compute.bare-metal` restating its offering mode → `docs/development/ROADMAP.md`
  (unowned gaps).
- The registry's `exists:false` cannot express absence → unowned work in
  `openspec/changes/README.md`.
