# Design: bring host inventory under definition documents

## Context

- **Definition documents.** Relays, pools, and capacity declarations reach the
  provisioning service as mounted YAML documents. Each startup applies a
  document only when its digest differs from the one recorded with the last
  apply, and records the digest in the apply's own transaction; an explicit
  import reconciles regardless and records nothing. The generic rule is
  `openspec/specs/resource-pool-management/spec.md`'s "Atomic authoritative
  reconciliation"; the capacity and relay forms are in
  `openspec/specs/physical-provisioning/spec.md`; the operator account is
  `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Definition documents".
  `DefinitionDocumentImporter`
  (`provisioning/compute/service/src/compute_provisioning_service/services/definition_documents.py`)
  is the gate. Contributed document kinds, such as VM's relays, run before
  pools, because pool configuration may name them.
- **Host inventory today.** `seed_inventory_if_empty`
  (`provisioning/compute/service/src/compute_provisioning_service/app_runtime.py`)
  parses `inventory_ini`, or the file at `inventory_path`, as an Ansible INI and
  applies it only while the hosts table is empty. It catches every exception and
  logs it, so an inventory naming an unknown pool, a refused pool move, or a
  parse error starts the service with no hosts. The parser skips a malformed
  entry with a warning and imports the rest. Under Helm the inventory reaches
  the service as `inventory_ini` in the operator-managed provisioning-secrets
  profile; the pod's checksum annotation does not cover that Secret, so editing
  it does not roll the pod. The INI names a key by file path and never carries
  key material.
- **Host writes.** `HostAuthority.apply_inventory`
  (`provisioning/compute/src/compute_provisioning/hosts/service.py`) upserts in a
  transaction it opens and commits itself, so it cannot share the digest's
  transaction. An INI entry always names a key path (defaulting to
  `/home/appuser/.ssh/id_ed25519`), cannot state `enabled` or a connection kind,
  and leaves an existing host's pool unchanged when it states no `pool_id`. The
  `ssh` codec keeps a stored protected key when a submitted connection names
  neither `key_path` nor `private_key`, and refuses such a connection for a new
  host.
- **Execution.** Execution renders only from the registered host record and
  refuses a host with none
  (`openspec/specs/physical-provisioning/spec.md#requirement-execution-inventory-comes-only-from-the-registered-host-record`),
  so a host only in the file is refused at dispatch.
- **Capacity derivation is gone.** No host write declares capacity, and the host
  record carries no hardware, so hosts and capacity declarations are independent:
  a declaration's `host_id` is not checked against the host registry.
- **Disabling a host does not stop it selling.** Site admission and settlement
  scheduling never read a host's `enabled` flag; only a create's job submission
  refuses a disabled host, and its dispatch then retries. This is a recorded
  defect, owned by `keep-new-deliveries-off-disabled-hosts`.

## Goals / Non-Goals

**Goals:**

- A host document an operator edits and rolls is applied; a restart against an
  unchanged document changes nothing.
- Hosts are declared in a YAML document with the registration API's field names,
  like the other definition documents.
- An existing site can produce a first document that reproduces its registry.
- One general method for definition documents is written down for operators and
  for the next document kind.

**Non-Goals:**

- Changing how execution resolves a host.
- Deciding who generates a host's key material
  (`contain-embedded-host-key-material` owns key material's lifetime on the
  execution path).
- Making a disabled host unsellable (`keep-new-deliveries-off-disabled-hosts`).
- Requiring a capacity declaration to sit in its host's pool (Open Questions).
- Changing the INI import route's semantics.

## Decisions

### D1. Host inventory is a digest-gated definition document

A startup applies the host document only when its digest differs from the one
recorded under the document kind `hosts`, and records the digest in the same
transaction as the apply. An explicit import reconciles regardless and records
no digest.

*Rationale.* A process start is not a submission and a changed document is; this
is the rule the other three documents follow, and it is the only rule under which
editing the document does what an operator expects. A deployment applies a chart
with no operator API call in it, so a site must be establishable from
configuration alone, which is why hosts keep a startup document at all.

*Rejected.* Registering on every start only the hosts not yet registered: it
reverts nothing, but leaves every edit except an addition unapplied, and adds a
fourth rule. Keeping seed-if-empty and reporting drift: it treats the symptom.
Retiring startup seeding: it gives up configuration-only deployment.

### D2. The host document is YAML with the registration API's field names

The document is a top-level `hosts` list. Each entry has `host_id`, optional
`pool_id`, optional `enabled`, and a `connection` of `kind`, `version`, and
`public` — for `ssh`, `ssh_host`, `ssh_user`, `ssh_port`, `public_host`,
`public_port`, and `key_path`:

```yaml
hosts:
  - host_id: kvm1
    pool_id: vm-default
    connection:
      kind: ssh
      version: 2
      public:
        ssh_host: 10.0.0.5
        public_host: 203.0.113.9
        ssh_user: ubuntu
        key_path: /home/appuser/.ssh/id_ed25519
```

Startup reads no INI. `inventory_ini` and `inventory_path` are retired: a
configuration stating either refuses startup naming `host_definitions_path`, as
`playbook_path` is refused, and the packaged defaults of `inventory_path` in
`settings.toml` and the provisioning chart's values are removed. The INI remains
the format of `POST /api/v1/hosts/import`, the Ansible distribution's route.

*Rationale.* The document must be a declaration. The INI cannot state `enabled`
or a connection kind or version, always names a key path (so reconciling it
would replace a per-host embedded key with the default key file on every edit),
and treats an absent `pool_id` as "leave it", which makes it a merge format. A
YAML document matches the other three, evolves through the codec's versions
(an older service refuses a version or kind it does not serve, naming what it
does), and is format-neutral, so it belongs to the compute family rather than to
the Ansible distribution.

*Rejected.* Reconciling the INI: one operator file for registration and Ansible
host preparation, but the limits above. Reconciling both formats: two
authorities over the same rows. INI now and YAML later: two operator migrations
and semantics specified only to be replaced. The cost accepted is that operators
who prepare hosts with Ansible keep a separate INI for that, with addresses
written twice.

### D3. The document is a `definitions.hosts` chart value rendered into the ConfigMap

The provisioning chart renders a non-empty `definitions.hosts` into its
ConfigMap, mounts it at `/app/config/host-definitions.yaml`, and sets
`host_definitions_path` itself; its schema refuses `host_definitions_path`,
`inventory_path`, and `inventory_ini` under `config`, and `host-definitions.yaml`
as a `configFiles` name. Compose stacks mount a host document and set
`PROVISIONING_HOST_DEFINITIONS_PATH`: the bare-metal stack's inventory file
becomes a host document, and the VM seller stack mounts one in place of the INI
baked into its image.

*Rationale.* The document carries addresses, ports, users, pool ids, and key
file paths, never a credential, so it is configuration. A ConfigMap edit rolls
the pod through the checksum annotation, so "edit and upgrade the release"
applies it with no manual step, and a chart-derived path cannot disagree with
the mount. The chart's former refusal of inventory content as values ends for
this document; credentials stay out of values.

*Rejected.* An operator-managed Secret: its edits do not roll the pod, which
re-creates the silent no-op, and it would be the one definition document in a
Secret. Either source selected by values: two render paths for no stated need.
`configFiles` with a separate path setting: two settings that can disagree.

### D4. A host the document stops naming is retained

Import creates and updates the hosts the document names and leaves every other
registered host unchanged, including its enabled state. Each apply reports the
registered hosts it does not name: in the startup log, and in the import
response. Stopping a host is an explicit `enabled: false`, in the document or
through the API.

*Rationale.* Hosts registered through the API, as every end-to-end lane registers
them, must coexist with the document; disabling unnamed hosts would disable them
on the first edit to any entry. Disabling also does not stop a host's
declarations selling today, so a removed line would become capacity that cannot
be delivered. Retention matches relays and capacity declarations.

*Rejected.* Disabling, like pools. Disabling unless the host carries live work:
the host authority reads no site or VM state, and the outcome would depend on
timing. Refusing a document that omits a registered host: the API and the
document could not coexist. The revisit trigger is in Open Questions.

### D5. An entry declares the whole host

Applying an entry registers the host or wholly replaces its non-secret state: an
omitted `pool_id` unplaces it, an omitted `enabled` means enabled, and the
connection is replaced through its kind's codec, which keeps the stored
protected key when the entry names no `key_path`. A pool change runs the host
pool-change hooks. An entry equal to the stored host, compared on the read that
omits secrets, writes nothing, runs no hook, and leaves `updated_at` alone.

*Rationale.* The document then says exactly what each named host is, as capacity
and relay entries do. The accepted cost is the capacity trade: a host disabled or
moved through the API is restored to the document's statement by the next change
to the document unless the document restates it. The export (D12) makes a first
document reproduce stored state, and a refused move refuses the whole document
(D7).

*Rejected.* Merging like `PUT /api/v1/hosts/{host_id}`: deleting a line would
change nothing, and the omitted-versus-null distinction D2 moved away from would
return. Replacing everything except `enabled`: one field with two meanings, unlike
its siblings.

### D6. The first document applies

A site with no recorded `hosts` digest applies its host document when one is
first configured, exactly as any changed document; writing the first document is
the operator's submission. An upgraded site keeps its registered hosts and,
until its operator configures a document, applies none. The upgrade path is to
export the registry (D12), edit, and mount.

*Rejected.* Recording the digest without applying: the first document would
silently not apply. Applying only into an empty registry: the old rule.

### D7. A document that cannot be applied fails whole

Validation is strict (a quoted number is an error) and runs in two stages, as
capacity's does. Every structural problem is reported with its location: an
unknown field, a missing `host_id` or `connection`, a duplicate `host_id`, a
wrong type, or a `connection.secrets` (D9). Only a structurally valid document
is checked against stored state, and every refusal found there is reported: an
unknown pool, a codec refusal (an unknown kind, a version not served, a new host
naming no key), and a pool-change hook refusing a move. Any problem leaves the
whole document unapplied; at startup it fails the start and records no digest,
so the next start retries. A configured path with no document fails startup.

A hook refusal at startup — a move of a host holding relay leases — keeps the
service from starting until the document is corrected, since leases cannot drain
while it is down. This is the behaviour of a capacity document's refused move
under a live reservation, and the remedy is to revert the edit; operator
documentation says so.

The INI import route keeps its own rules: it upserts, an absent `pool_id` leaves
a host's pool unchanged, and a malformed entry is skipped with a warning.

*Rationale.* With a digest recorded, a skipped entry stays missing until the
document changes again, which is the failure this change removes; logging and
continuing is the current silent failure. The INI route is an operator's API
convenience, not a reconciled declaration, so it is left as it is.

### D8. The family kit owns the document; the service gates it

Parsing, two-stage validation, the equality check, a session-scoped apply that
writes through the host authority's codecs and pool-change hooks in the caller's
transaction, and the export live with the host authority in
`compute_provisioning.hosts`; the entry model sits in
`compute_provisioning_contracts` beside `HostCreate`. The service's
`DefinitionDocumentImporter` gains the `hosts` kind, read from
`host_definitions_path`. The startup step `seed-inventory` is replaced in place:
after the stored-pool declaration check and before capacity definitions, so the
pools a host names exist, from their document or the fresh-site seed.
`seed_inventory_if_empty` is removed. The Ansible distribution keeps only the INI
parser and its import route.

*Rationale.* The document is format-neutral and hosts are the family's, so the
service composes them directly, as it does capacity. The contributed-document
seam runs before pools and serves a domain's resources.

*Rejected.* An ordering slot on the contributed-document seam: not needed for a
family resource.

### D9. The document names key material and never carries it

An entry stating `connection.secrets` is a structural problem. A key is named by
`key_path`, a file on the service's filesystem — under Helm a Secret volume the
operator mounts — or kept from the stored host by omitting `key_path`. Registering
a host with key material remains an API act: `POST /api/v1/hosts` with
`secrets`, or the INI route's `embedded` mode.

*Rationale.* Definition documents name secrets and never carry them, as a relay
entry names the profile key holding its token.

*Rejected.* An entry naming a profile key holding key material, read once at
creation as a relay's token is: key files already reach the pod by mount, and
per-host keys in a profile scale poorly. It can be added later without a format
change.

### D10. A declaration need not sit in its host's pool

This change does not require a capacity declaration naming a host to be in that
host's pool. See Open Questions.

### D11. Implementation cadence

One round of two sessions, then closeout:

1. The family host document: the entry model; parsing and two-stage validation;
   the equality check; the session-scoped apply in the host authority; the
   export; the export and import route contracts, route services, and
   controllers; the typed client methods; their unit and integration tests.
2. Wiring and retirement: the importer's `hosts` kind and startup step; removing
   `seed_inventory_if_empty`; retiring `inventory_ini` and `inventory_path` and
   their packaged defaults; the chart's `definitions.hosts`, schema, and render
   tests; the compose stacks and the topology secrets script; operator
   documentation drafts.

### D12. The host registry exports a canonical host document

`GET /api/v1/hosts/export`, a family host route admitting the administrator,
returns every registered host as a host document, without secrets: a host
holding a protected key appears with no `key_path`. A host stored at a connection
version its codec does not serve cannot be stated in the document, so the export
reports it rather than emitting an entry it does not hold. Importing an unedited
export changes nothing. The typed family client gains `export_hosts()`.

*Rationale.* An existing site's first document must reproduce its registry —
pools and enabled states set through the API, and hosts registered through it —
which an INI conversion cannot. This follows the pool document's canonical
export and its round-trip requirement.

*Rejected.* Documentation only: a hand-written first document easily unplaces or
re-enables hosts. An offline INI-to-YAML converter: it converts the file, not the
site.

### D13. Definition documents follow one method, written down

`DEPLOYMENT_AND_CONFIG.md`'s "Definition documents" opens with the method every
kind follows, and each kind's section states only its own rules:

- one `<kind>_definitions_path` setting, derived by the chart from
  `definitions.<kind>`, rendered into the ConfigMap so an edit rolls the pod,
  refused under `config`, and mounted under a name `configFiles` refuses;
- a stable digest kind recorded in the apply's transaction;
- a session-scoped apply; strict two-stage validation reporting every problem;
  any problem leaves the document unapplied, fails startup, and records no
  digest; an entry equal to stored state writes nothing;
- an explicit import that always reconciles, records nothing, and offers
  validate-only;
- a stated rule for what the document does to entries it stops naming;
- no credential: secrets are named by profile key or file path;
- a slot in startup's dependency order;
- a canonical export where the kind round-trips.

### D14. An import route reconciles a submitted host document

`POST /api/v1/hosts/definitions/import`, a family host route admitting the
administrator, reconciles the submitted document regardless of the digest and
records none, answering the created, updated, and unchanged hosts and the
registered hosts it does not name. With `validate_only` it reports the problems
and the planned changes without applying either. A pool-change hook's refusal
answers 409; every other problem answers 400 with its location. Its request
model follows the capacity-definitions import's. The typed family client gains
`import_host_definitions`.

*Rationale.* The explicit-import half of the definition-document contract needs
a surface in the document's own format, and it completes the export's round
trip.

## Risks / Trade-offs

- [Operators lose startup INI seeding] → Startup refuses a stated
  `inventory_ini` or `inventory_path` naming `host_definitions_path`; seller
  quickstarts and the upgrade notes give export, edit, mount.
- [A document edit restores API changes to the hosts it names] → The same trade
  capacity documents make; the export reproduces stored state, and operator
  documentation states it.
- [A refused pool move keeps the service from starting] → As for capacity
  documents; the error names the host and the remedy is reverting the edit.
- [Ansible operators keep two host lists] → The INI import route stays for
  operators who keep one file and import it.

## Open Questions

- **Should a document disable the hosts it stops naming?** Retained today (D4),
  partly because disabling a host does not stop its declarations selling.
  Revisit when `keep-new-deliveries-off-disabled-hosts` lands.
- **Should a capacity declaration naming a host be required to sit in that
  host's pool?** Today a host's pool is placement intent. One piece of evidence
  that it is not purely intent for VM: a VM create leases its relay port on the
  relay of the declaration's pool, while the VM pool-change hook keeps a host's
  relay uniform by the host's pool, so a declaration in a relay-backed pool naming
  a host placed under another relay may lease a port the host's tunnel client
  does not dial. This is unproven end to end; no lane runs a relay-backed pool.
  Revisit when `prove-relay-provisioning` and `admit-relay-proxies-by-grant`
  land, or when shape derivation from host facts is designed. If those relay
  changes have not landed by this change's closeout, record the relay-pool
  mismatch as unowned Goal 1 work in `docs/development/ROADMAP.md`.
