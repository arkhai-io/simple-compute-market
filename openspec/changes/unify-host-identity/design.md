# Design

## Context

Found while designing `capacity-resource-administration` (2026-09-21), when its
derivation needed to decide whether a host already had a capacity declaration and
could only answer by searching the declaration's attributes under several spellings.
The repository owner's direction: names out of compliance with `ARCHITECTURE.md` are
fixed regardless of which change found them, broadly enough that the next layer up
does not meet the same asymmetry, in a change of their own.

### Census (verified 2026-09-21)

Counts are occurrences in Python, YAML, TOML, and JSON outside `openspec/`.

| Spelling | Occurrences | Files | Concentrations |
|---|---|---|---|
| `vm_host` | 542 | 115 | provisioning service (31 files), VM storefront (30), VM provisioning (19), e2e (9), `kit/site` (4 source, 4 test) |
| `machine_id` | 202 | 53 | bare-metal storefront (19), bare-metal tests (8), provisioning service (7), bare-metal provisioning (6), bare-metal core (5) |
| `kvm_host` | 95 | 26 | host registry, INI parser, inventory rendering |
| `default_vm_host` | 12 | 11 | settings, Helm values, VM adapter |
| `physical_host_id` | 242 | 69 | ledger cross-mode accounting, bare-metal schema — out of scope, see Decisions |
| `executor_target` | 133 | 40 | reservation column and executor action targets — out of scope, see Decisions |

Persisted surfaces: `hosts.name` (primary key) and `hosts.kvm_host`;
`capacity_buckets.attributes` JSON (`vm_host`, `bare_metal_publication.machine_id`);
`capacity_reservations.executor_ref` JSON (`{"vm_host": …}`); fulfillment settlement
metadata and job parameters JSON; the bare-metal storefront's `machine_id` column;
the VM storefront's local `vm_host` column (retired by `pools-9`).

External surfaces: the Ansible playbooks read `vm_host` (VM) and derive `machine_id`
from `executor_target` (bare metal); the published bare-metal listing
`bare_metal.v1` carries `machine_id`; hosted bare-metal candidates require it. No
registry filter specification indexes any of these names.

## Decisions

### The host's identity is `host_id` everywhere, including the registry's own key

`Host.name` is renamed to `host_id` rather than kept beside it. The owner asked
whether `name` has a need independent of the identity; it does not. It is the
primary key, the Ansible inventory alias rendered into every inventory, the value
every `vm_host` and `machine_id` already carries, and the reference job history
keeps. One value, one role — so one name. A separate display name was considered and
rejected: nothing displays hosts by anything other than this alias, and adding one
would create exactly the two-names-one-thing problem this change removes.

INI files are unaffected: the alias is still each line's first token, read into
`host_id`.

### `kvm_host` becomes `ssh_host`

It is the address the provisioner connects to, on a record bare-metal nodes share,
so the `kvm` prefix is VM vocabulary on a domain-neutral record. `ssh_host` groups
with `ssh_user`, `ssh_port`, and `ssh_key_*`, which describe the same connection.
`public_host`, the tenant-facing address, keeps its name: it is already neutral and
already distinct.

### A capacity declaration names its host through a first-class `host_id`

A nullable `host_id` column on `capacity_buckets`, carried by the registration body
and the capacity-definitions document. `kit/site` stays executor-neutral: the value
is an opaque identifier the ledger stores and copies into `executor_ref`, never
resolves. It replaces the declaration's `vm_host` attribute and its
`bare_metal_publication.machine_id`; neither remains on the declaration.

Nullable because a declaration may have no host — logical capacity such as API
credits, and the hostless declarations `project-capacity-resources-without-hosts`
projects.

### Execution references follow

Reservation `executor_ref` becomes `{"host_id": …}`. Fulfillment metadata, job
parameters, and the VM lease API carry `host_id`. The VM playbook's target variable
becomes `host_id`; the bare-metal playbook's `machine_id` variable becomes `host_id`,
still defaulting from `executor_target`. Teardown keeps reusing the recorded value,
as `physical-provisioning`'s "Ansible fulfillment adapter" requires, under the new
key.

### The bare-metal listing becomes `bare_metal.v2`

`machine_id` is a field of a versioned envelope, so renaming it raises the kind.
Bare-metal models, storefront persistence, hosted candidates, and the buyer plugin
move to `bare_metal.v2` together.

### `physical_host_id` and `allocation_mode` have one location

Today the ledger's cross-mode rule reads them at a declaration's top level, and the
bare-metal publication view reads them inside `bare_metal_publication`. The
bare-metal quickstart writes only the nested copy, so a declaration built from it
never participates in the cross-mode rule. They move to the top level only, and the
publication view reads them from there. Top level, because the cross-mode rule is
domain-neutral and belongs to the ledger, while `bare_metal_publication` is one
domain's view configuration; the view deriving from the declaration is the correct
direction of dependency.

### What is deliberately not renamed

- `physical_host_id`: the stable identity of a *physical machine* across hosts. A
  host belongs to exactly one pool, so one machine offered both as VM slices and as
  a whole host is registered as two hosts; `physical_host_id` ties them together for
  cross-mode accounting. Independent need, independent name.
- `executor_target` and `vm_target`: an executor action's target and a VM's name,
  both permitted by `ARCHITECTURE.md`.
- VM-storefront surfaces `pools-9` deletes: renamed code that is then removed is
  churn. The storefront's surviving settle and client surfaces are renamed.
- Registry `host_*` hardware fields: they describe hardware, not identity.

### Migration is one transaction per service and fails closed

The compute-provisioning migration renames the host columns, adds and populates the
declaration's `host_id` from `vm_host`, else an enabled publication's `machine_id`,
strips both from attributes, lifts nested `physical_host_id`/`allocation_mode` to the
top level, and rewrites `executor_ref`, fulfillment-metadata, and job-parameter JSON
keys. A declaration whose `vm_host` and `machine_id` disagree, or whose nested and
top-level cross-mode fields disagree, aborts the migration with nothing written,
naming the row. The bare-metal storefront migration renames its column.

### Sequencing

This change lands before `capacity-resource-administration`'s derivation and
projection sections, which consume the declaration's `host_id`.

## Risks / Trade-offs

- **[Breadth]** Roughly 170 files across provisioning, kits, both compute domains,
  core storefront surfaces, Ansible, and e2e. Mitigated by renaming mechanically per
  surface with the persisted and wire surfaces each covered by a migration or a
  version bump, and by excluding everything `pools-9` deletes.
- **[Recorded JSON keys]** `executor_ref`, fulfillment metadata, and job parameters
  are JSON; a missed key would surface only at teardown. The migration rewrites them
  and a post-migration check counts rows still carrying a retired key, following the
  existing `count_rows_carrying_retired_offering_mode_key` precedent.
- **[Ansible variable rename]** A playbook reading a variable the adapter no longer
  sets targets `localhost` by default. Cover each playbook's rendered variables with
  a test rather than trusting the rename.

## Open Questions

- **Does bare metal need compatibility for `bare_metal.v1`?**
  `DEPLOYMENT_AND_CONFIG.md` says the bare-metal stack is not release-qualified. If it
  is unlaunched, as API credits is, `v1` is removed with no recovery decoder and
  bare-metal storefront databases are migrated but not dual-read. If any accepted
  bare-metal deal or published hosted evidence under `v1` must remain recoverable, a
  recovery-only `v1` decoder is retained, as the hosted-fiat card profile retains its
  historical rows. Assumed unlaunched until answered; no task depends on it before
  planning.
