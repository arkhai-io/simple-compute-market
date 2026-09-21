## Why

`docs/development/ARCHITECTURE.md`'s "One name per concept" names the machine and its
connection identity `host`. The code names that one concept four ways:

| Spelling | Where |
|---|---|
| `Host.name` | The host registry's primary key and the Ansible inventory alias |
| `vm_host` | VM capacity declaration attributes, reservation `executor_ref`, VM lease API, fulfillment metadata, job parameters, the VM playbook's target variable, storefront settle and admin surfaces |
| `machine_id` | Bare-metal publication configuration, the published `bare_metal.v1` listing, bare-metal storefront persistence, the bare-metal playbook |
| `kvm_host` | The host registry's address column, on a record bare-metal nodes share |

Every spelling but `Host.name` also carries a domain prefix or domain vocabulary on a
concept that is domain-neutral. The cost is concrete and recurring: the capacity
projection has to reverse-look-up a declaration's host under each spelling, and
`capacity-resource-administration` found that it could not state "a host has no
declaration" without inheriting that multi-key rule. Each change that touches the
host link meets the same asymmetry one layer further up.

This is a compliance fix against current architecture, not a feature. It is split
from `capacity-resource-administration` so that change keeps its acceptance boundary
and this one carries the rename's own migrations and wire decisions.

## What Changes

- **BREAKING (data, wire):** rename the host registry's identity from `name` to
  `host_id`, and its address column from `kvm_host` to `ssh_host`, beside the
  existing `ssh_user`, `ssh_port`, and `ssh_key_*`. The host API path parameter,
  request and response models, the operator client, and the INI parser follow.
- **BREAKING (data, wire):** give the capacity declaration a first-class optional
  `host_id` naming the host it is delivered through, replacing `vm_host` and
  `bare_metal_publication.machine_id` as the declaration's host link.
- **BREAKING (data, wire):** rename `vm_host` to `host_id` in reservation
  `executor_ref`, fulfillment metadata, job parameters, the VM lease API, and the
  VM playbook variable; rename `machine_id` to `host_id` in bare-metal models,
  persistence, and playbooks, and publish the bare-metal listing as `bare_metal.v2`.
- Rename the `default_vm_host` setting to `default_host_id`.
- Give `physical_host_id` and `allocation_mode` one location on a declaration — the
  top level, where the ledger's cross-mode accounting reads them — and correct the
  bare-metal quickstart, which nests them where that rule never sees them.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: the host registry, declarations, execution references,
  and playbooks name the host `host_id`.
- `site-capacity`: a capacity declaration carries a first-class `host_id`; the
  cross-mode accounting fields have one location.

## Non-Goals

- **Do not rename `physical_host_id`.** It is a different concept with an
  independent need: the stable identity of a physical machine for cross-mode
  accounting. One machine can be registered as several hosts — a host belongs to
  exactly one pool, so a machine offered as VM slices and as a whole host appears as
  a VM host and a bare-metal node — and `physical_host_id` is what ties them
  together.
- **Do not rename `executor_target` or `vm_target`.** `executor_target` is an
  `executor_`-prefixed compound naming an executor action's target, which
  `ARCHITECTURE.md` explicitly permits; `vm_target` names a VM, not a host.
- **Do not rename VM-storefront surfaces `pools-9-retire-local-physical-authority`
  deletes** (CSV import, local physical tables, `compute_allocations`, the orphaned
  physical admin surface, and the always-`None` `vm_host` plumbing). Renaming code
  that is about to be removed is churn; `pools-9` removes it instead.
- **Do not rename the registry filter specification's `host_*` hardware fields**
  (`host_cpu_cores`, `host_ram_gb`, …). They describe hardware on a listing, not
  host identity, and already use the correct noun.
- Do not change capacity admission, scheduling, or fulfillment behaviour.

## Impact

- **Affected code:** `provisioning/compute/service` (host model, migrations,
  capacity inventory, settings), `kit/site` (declaration column, `executor_ref`
  construction, registration model), `kit/site-client`, `kit/fulfillment` (tests),
  `domains/vms/provisioning` (adapter, operator client, Ansible playbooks and
  inventory examples), `domains/bare_metal` (schema, projections, storefront,
  provisioning adapter, buyer), `core/storefront` and `core/storefront-client`
  settle surfaces not retired by `pools-9`, `e2e-tests`, and the bare-metal and
  seller quickstarts.
- **Affected data:** compute-provisioning migration renaming host columns, adding and
  populating the declaration's `host_id`, stripping `vm_host` from declaration
  attributes, and rewriting `executor_ref`, fulfillment-metadata, and job-parameter
  JSON keys; bare-metal storefront migration renaming its `machine_id` column.
- **Wire:** host API, capacity registration, VM lease API, storefront settle
  models, and the bare-metal listing (`bare_metal.v1` → `bare_metal.v2`). None of
  these is a compute-provisioning `VersionedContractModel`; the listing kind is the
  one versioned envelope affected.
- **Deployment:** operator INI files are unaffected — the alias remains the first
  token of each line and is read into `host_id`. Helm values and settings that name
  `default_vm_host` change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "One name per concept" gains the `host_id`
      identifier and states that `physical_host_id` is a distinct concept.
- [x] Existing subsystem specification — `physical-provisioning`, `site-capacity`.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- The host's identity is `host_id` on every surface — `ARCHITECTURE.md`'s "One name
  per concept", `openspec/specs/physical-provisioning/spec.md`.
- A capacity declaration names its host through `host_id` —
  `openspec/specs/site-capacity/spec.md`.
- `physical_host_id` identifies the physical machine across hosts —
  `ARCHITECTURE.md`'s "One name per concept".

## Dependencies and Related Changes

- **`capacity-resource-administration` depends on this change.** Its derivation and
  projection correlation use the declaration's `host_id`.
- **`pools-9-retire-local-physical-authority`** deletes the VM storefront's `vm_host`
  surfaces this change leaves alone. No ordering constraint between the two beyond
  `pools-9`'s existing dependency on `capacity-resource-administration`.
- **`market-platform-compute-40-multi-domain-proof`** proves cross-mode rejection;
  the single-location fix here is what makes a declaration written from the
  quickstart participate in the rule it proves.
- **`retire-vm-remove-job-id`** removes a `vm_`-prefixed reservation column. No
  overlap: that column names a job, not a host.
