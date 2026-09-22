# Design: bring host inventory under definition documents

Status: design phase. Not planned. Nothing here is decided.

## Context

- **Definition documents.**
  `provisioning/compute/service/src/compute_provisioning_service/services/definition_documents.py`
  imports relays, pools, and capacity documents. Each is gated by the digest of
  the last applied document, recorded in the same transaction as the apply.
  `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Definition documents" section
  states the contract, including "a process start is not a submission".
- **Host inventory.** `seed_inventory_if_empty` in
  `provisioning/compute/service/src/compute_provisioning_service/app_runtime.py`
  applies `inventory_ini`, or the file at `inventory_path`, only when the hosts
  table is empty. Its comment gives the reason: API changes must survive a
  restart. That is the same reason the digest gate exists, reached by a cruder
  rule that also ignores a changed file.
- **Execution.** Execution renders only from the registered host record and
  refuses a host with none
  (`openspec/specs/physical-provisioning/spec.md#requirement-execution-inventory-comes-only-from-the-registered-host-record`).

## Open questions

- **A registered host the document stops naming.** Pools are disabled, and
  relays and capacity declarations are retained. Hosts are never hard-deleted,
  because job history references them. What is the least surprising treatment,
  and does it depend on whether the host backs a live obligation?
- **The first startup after upgrade.** An existing deployment has hosts and no
  recorded inventory digest. Applying the mounted inventory then could revert API
  edits made since first boot. Recording its digest without applying could leave
  the operator's latest edit unapplied.
- **Where the document comes from.** Helm injects `inventory_ini` through the
  provisioning-secrets profile, while definition documents are defined as never
  carrying a credential and naming secrets by key instead. Can an inventory name
  key material by profile key, as a relay names its admission token? How does
  this meet `contain-embedded-host-key-material`?
- **Format.** Keep the Ansible INI format, or define a YAML host document beside
  the relay, pool, and capacity documents with the registration API's field
  names?
- **Ordering and derivation.** Applying the INI derives capacity declarations
  for hosts with GPUs that no declaration names. How does that order against a
  capacity document naming the same hosts, and does a host document keep the
  derivation at all?
