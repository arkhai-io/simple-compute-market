## Why

A capacity declaration owns every dimension a site sells
(`openspec/specs/site-capacity/architecture.md`), yet a host record still carries
`gpu_count` and `gpu_model`, which duplicate its declaration. Once
`seed-default-pool-at-runtime` stops deriving declarations from host inventory,
nothing reads those host fields: they are stored and returned, and describe
hardware a declaration already states.

The compute capability schema makes `gpu` its one required family
(`domains/compute/src/arkhai_compute/capability_schema.py`), so a site cannot
state, publish, or sell a VM or bare-metal shape for a machine without GPUs.

## What Changes

- Retire the host's `gpu_count` and `gpu_model` from the host API (`HostCreate`,
  `HostUpdate`, `HostResponse`) and from the INI inventory format (`gpus=`,
  `gpu_model=`), with a migration that drops the columns. A host's hardware is
  stated only by its capacity declaration.
- Make the `gpu` family optional in the compute capability schema, so a shape
  without GPUs can be declared, published, filtered, and claimed.
- Carry that through the VM default listing generator, which generates only GPU
  shapes; the resource type a declaration without GPUs carries; and the
  bare-metal shape rule, which requires a GPU count and model.

Open for design, not decided here:

- what the VM default generator publishes for a pool whose members declare no
  GPUs;
- whether a declaration without GPUs keeps the `compute.gpu` resource type or
  takes another;
- how the registry's compute filters treat a listing that states no `gpu`
  family.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: the host record and the INI inventory format.
- `market-composition`: the compute capability schema's required families.
- `storefront-publication`: VM default shapes and bare-metal shapes without GPUs.
- `site-capacity`: declarations without a GPU dimension, if their resource type
  changes.

### New Capabilities

None.

## Non-Goals

- Do not derive a full compute shape from host facts. An explicit,
  pool-targeted derivation from an Ansible fact run is its own change; this one
  must stay compatible with it: declarations remain the only statement of what
  sells, and a derivation would produce ordinary declarations into a named pool
  as an operator's act.
- Do not change capacity admission or the claim vocabulary
  (`settle-capacity-claim-vocabulary` owns the latter).

## Impact

- Host contracts, client, authority, and INI parser
  (`provisioning/compute/contracts`, `provisioning/compute/src/compute_provisioning/hosts/`,
  `provisioning/compute/ansible`), and a provisioning migration.
- The compute capability schema (`domains/compute`), VM default listing
  generation, and bare-metal shape derivation.
- Operator documentation of host inventory and capacity declarations, and every
  test fixture that registers a host with a GPU count.

## Dependencies and Related Changes

- Depends on `seed-default-pool-at-runtime` for implementation: it removes
  capacity derivation from host inventory, the host GPU fields' last reader.
- Takes two items from the unowned work found by `capacity-shape-envelope`: "A
  host's `gpu_count` duplicates the `gpu_count` of its capacity declaration" and
  "The compute schema requires `gpu.count` and `gpu.model`, so a VM or bare-metal
  listing without GPUs cannot be stated".
- Coordinates with `bring-host-inventory-under-definition-documents`, which
  changes how host inventory enters the registry.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`,
      `market-composition`, `storefront-publication`, and possibly
      `site-capacity`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
