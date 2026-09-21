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
naming the row. The bare-metal storefront is reset rather than migrated; see "Bare
metal: reset the preprod storefront database and drop `bare_metal.v1`".

### Sequencing

This change lands before `capacity-resource-administration`'s derivation and
projection sections, which consume the declaration's `host_id`.

### VM-storefront classification (task 0.2, 2026-09-21)

Rule: a site `pools-9-retire-local-physical-authority` names for removal or freezing
is left; everything else is renamed.

| Site | Disposition | Why |
|---|---|---|
| `services/fulfillment_service.py` (`vm_host` parameters, `_do_shutdown`), `services/vm_fulfillment_service.py` (`reserved_vm_host`) | left | `pools-9` 3.5 removes the always-`None` threading |
| `services/resource_capacity_validator.py` | left | `pools-9` 4.5 deletes it |
| `utils/sqlite_client.py`, `utils/migrations.py` local physical tables and `compute_allocations.vm_host` | left | `pools-9` 2.3 and 4.4 freeze them |
| `data/*.csv`, `listings/resource_csv_importer.py`, `listings/resources.py` and `listings/models.py` host-row denormalization | left | `pools-9` Section 5 retires CSV import and the local host table they read |
| `models/capacity_admin_models.py`'s `UsageStartedEventRequest`, `controllers/admin_controller.py`'s usage-started route, `storefront_client`'s `notify_usage_started` | **renamed on the wire** to `host_id` | The route survives `pools-9`; only the table it writes into is frozen. The controller maps `host_id` onto the frozen column until `pools-9` removes the write |
| `services/vm_job_spec_service.py`, `services/admin_settle_service.py`, `core_storefront` `EvaluateSettleResponse`, `storefront_client`'s settle evaluation | renamed | Surviving admin settle path; reads the site's probe payload, which now names `host_id` |
| `services/fulfillment_resume_runtime.py` | left (reclassified during implementation) | Its `vm_host` reaches `_register_vm_lease_with_settings`, which sends the provisioning client's `LeaseRegistration` and ignores `vm_host` entirely — the always-`None` threading `pools-9` 3.5 removes |
| `cli_publish.py`'s `machine_id` | renamed | Reads the bare-metal publication view |
| `settings.toml`'s `default_vm_host` and its `groups/config.py` comment | **removed** | No storefront code reads it; the provisioning service owns the setting |

### Decisions made during implementation (2026-09-21)

- **Two more spellings.** The census missed `relay_port_leases.host_name` and the
  job-result field `vm_host_ip` (the host's tenant-facing address). They became
  `host_id` and `host_ip`.
- **The bare-metal domain identity stays `bare_metal.v1`.** The domain contract's
  identity had been derived from the payload kind. Operator `storefront_domains`
  configuration and the combined storefront's durable listing and thread
  bindings name the identity, so renaming it would have broken configuration and
  orphaned bindings. `BARE_METAL_DOMAIN_IDENTITY` is now its own constant; only
  the payload kind moved to `bare_metal.v2`. VM already keeps these apart
  (`compute.v1` against its payload kinds).
- **Provider operation envelopes move to schema 2; kinds do not change.** VM
  `vm.ansible.create.v1`/`teardown.v1` and bare-metal
  `bare_metal.fulfillment.create.v1`/`teardown.v1`/`result.v1` name the host in
  their payloads. Their `schema_version` is 2; dispatch accepts only 2; the
  migration rewrites stored schema-1 operations. Kind strings are never renamed.
- **`SettlementResource.host_id` and `settlement_records.resource_host_id`.**
  Providers read the host from a field rather than from the attribute snapshot.
- **`host_id` stays matchable in claims.** The feasibility view adds it to its
  normalized facts beside `resource_id`, and the migration rewrites
  `claim_attributes`. Otherwise a stored reservation pinned to a host would
  stop matching at scheduling.
- **One declaration per host is enforced at write time.** `capacity_buckets.host_id`
  is unique; registration naming a host another declaration holds is a 409.
- **An enabled bare-metal publication requires the declaration's `host_id`.**
  The projection's former requirement for an explicit `machine_id` moved to the
  declaration's own field, keeping the fail-closed behaviour.
- **The legacy `vm_leases` backfill emits the current shape** and joins the host
  table on whichever key column exists, so it runs correctly before or after the
  registry rename.
- **Distribution version bumps are deferred** to one bump after
  `capacity-resource-administration`, which changes the same packages. Each bump
  relocks every consumer's `uv.lock`; doing it twice is churn.

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

### Bare metal: reset the preprod storefront database and drop `bare_metal.v1` (decided 2026-09-21)

**Supersedes** an earlier same-day decision to migrate the bare-metal storefront
database behind a guard that refused to run while any bare-metal agreement was
non-terminal. The owner rejected that guard as a strategy: bare-metal contracts can
run for a year, and forcing operators to drain them before patching is not viable.

What the rename touches in bare-metal state (verified 2026-09-21): `machine_id`
appears in signed negotiation terms, the listing, the materialization, the receipt,
and the access result, and the `bare_metal.v1` kind keys the accepted plan's service
terms, which feed the obligation identity shared with the hosted authority. The
digest-pinned hosted records — the accepted binding, lease-ready result and evidence,
and the derived fulfillment identity — do not contain `machine_id`, so this rename
does not invalidate them.

The durable way to evolve such state — keep producing only the new kind, keep a
read-only decoder for the old one, retire it when a measured count of live
references reaches zero, and verify stored proofs over stored bytes — is a
repository-wide rule, and it is captured as its own change,
`version-accepted-artifacts`, which must land before bare metal is released. Building
it inside a rename would bury a policy decision in a mechanical change.

For this change, bare metal is not in production and its only preprod deployment
serves the owner's own nodes, so:

- the bare-metal storefront database is **reset**, not migrated, following the
  manual procedure in `tasks.md` Section 4;
- `bare_metal.v1` is removed with no decoder;
- the bare-metal storefront **refuses to start** against a database written under the
  retired kind, naming the reset procedure, rather than failing later on a decode.
  Detection is structural — the retired `machine_id` column in
  `derived_bare_metal_listings` — so it needs no decoder;
- the compute-provisioning database, which VM shares, is migrated normally
  (Sections 1–3); its bare-metal rows are unsigned state.

The drain guard is dropped entirely: it is throwaway effort that
`version-accepted-artifacts` makes unnecessary.

## Open Questions

None. The bare-metal compatibility question was answered on 2026-09-21; see "Bare
metal: reset the preprod storefront database and drop `bare_metal.v1`".
