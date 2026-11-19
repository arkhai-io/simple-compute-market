## ADDED Requirements

### Requirement: A capacity reservation is stored apart from its host, pool, and assignment

The site-capacity schema MUST name a reservation `CapacityReservation`,
keyed by `capacity_reservation_id`, with explicit site ownership and
globally unique identifiers. It MUST keep host identity, pool membership,
reservable capacity, and settlement-resource assignment separate.

#### Scenario: A reservation is assigned a resource

- **WHEN** a capacity reservation is assigned a settlement resource
- **THEN** the reservation is a `CapacityReservation` keyed by its globally unique
  `capacity_reservation_id`, and the assignment is recorded on the reservation, apart
  from the host record that holds the host's identity and the capacity record that
  holds its pool membership and reservable capacity

### Requirement: Requested offering mode is required and bounded by the pool

Every capacity probe and reservation claim MUST carry a non-empty canonical `offering_mode` naming the requested offering mode, and that key MUST be required. It is the same value a Resource Pool declares as deliverable, the same value the durable listing binding records, and the same value the published listing carries; no surface may name it `executor_kind`, `offering_type`, or `virtualization_type`. The site authority MUST persist that exact value on the Capacity Reservation and MUST NOT infer it from `host_id`, `physical_host_id`, resource kind, market name, matched-resource attributes, or any default. A matching Resource Pool MUST currently declare the requested mode before a new hold is created.

The claim's site-inventory discriminator remains a separate field and a separate axis. Naming the offering mode consistently MUST NOT merge the two.

`executor` MUST NOT be used as vocabulary for the offering mode, for the machine, or for the delivery handler. The machine is a host, the handler is a provider, and the mode is an offering mode.

#### Scenario: Claim omits the requested mode

- **WHEN** a capacity probe or reservation claim omits `offering_mode`
- **THEN** the site authority rejects it before matching resources and does not infer `vm` from a matched resource

#### Scenario: Claim names the requested mode under a retired key

- **WHEN** a capacity probe or reservation claim carries the requested mode under `executor_kind`
- **THEN** the claim is treated as carrying no offering mode and is refused

#### Scenario: Pool does not declare the requested mode

- **WHEN** a Physical Resource matches the requested shape but its Resource Pool does not declare the claim's offering mode
- **THEN** reservation is refused with the mode and pool identified before a Capacity Reservation or debit exists

### Requirement: A reservation's release handle has a single name

A Capacity Reservation MUST represent its durable release handle, when it has
one, only as `release_job_id`, regardless of the reservation's offering mode. The
handle is absent until release begins. The site authority MUST NOT write a
domain-prefixed mirror of it. Every lease contract that publishes a release
handle MUST name it `release_job_id`. Only the lease lifecycle writes the handle;
no lease route accepts one.

A reservation's pool, offering mode, and teardown path differ by domain, but the
handle a caller follows to observe release does not, so one name serves every
offering mode that shares the reservation table.

#### Scenario: A VM reservation begins releasing

- **WHEN** the compute lifecycle records the release job for a reservation whose offering mode is the VM mode
- **THEN** the reservation's `release_job_id` is set and no second, VM-named field is written

#### Scenario: A lease is read through either adapter

- **WHEN** a VM lease or a bare-metal lease is read, through the compute family's one lease surface that serves both
- **THEN** the release handle is published as `release_job_id` and under no other name

#### Scenario: An operator corrects a lease's release handle

- **WHEN** an operator wants to change a lease's release handle
- **THEN** no lease route accepts one: the handle is written only by the lease lifecycle, and a lease that cannot be released is repaired by retry-release or force-release

### Requirement: A lease records its activation instant

A reservation MUST carry a nullable `activated_at_utc`, written only by activation as an ISO-8601 UTC instant from the site's clock. Whether the site has recorded a lease's activation MUST be derived from it and stored nowhere else. Null MUST mean only that no activation is recorded: on a reservation that predates the column it says nothing about whether the resource was delivered, and no consumer may treat it as evidence that it was not.

#### Scenario: The instant is read

- **WHEN** a reservation is read through the site's reservation view
- **THEN** it carries `activated_at_utc`, null until activation and the recorded instant after it

## REMOVED Requirements

### Requirement: Capacity schema separation

**Reason**: Its only scenario, "Existing host migration", described the pre-floor migration that placed every existing host in the default resource pool before fulfillment records were backfilled; that migration is part of compute provisioning's v0.3.0 floor and its body is deleted with the pre-floor history. Its normative text is kept unchanged as "A capacity reservation is stored apart from its host, pool, and assignment", with a scenario stating the separation itself, since a MODIFIED requirement cannot drop a scenario.

**Migration**: None: the schema's rule is unchanged under the new requirement's name.

### Requirement: A stored reservation in a retired state is converted at upgrade

**Reason**: The conversion it governs (`20261028_001_retired_reservation_states`) is part of compute provisioning's v0.3.0 floor, so every provisioning database the chain adopts has already run it and the chain refuses any older one; the API-credit service's chain starts at its baseline with no adoption path, so no existing API-credit database is migrated. No supported database can still hold a reservation in a retired state, and the conversion is deleted with each service's pre-floor history.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release, or any existing API-credit service database, starts that service from a fresh database.

### Requirement: Requested offering mode is explicit and bounded by the pool

**Reason**: Its paragraph on backfilling legacy reservations, settlement assignments, and executor jobs, migrating reservations persisted under the retired key, and quarantining rows with no single proof, and its scenarios "Legacy identity has one durable proof" and "Legacy identity is unproved or conflicting", govern the migrations `20260815_001_pool_declared_offering_modes` and `20260911_001_reservation_offering_mode_name`, which are part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run them, and the chain refuses any older database as unsupported, so their bodies are deleted with the pre-floor history. Its remaining rule is kept unchanged as "Requested offering mode is required and bounded by the pool", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: A reservation's release handle has one name

**Reason**: Its scenarios "A compute provisioning database is upgraded" and "A compute provisioning database holds two different release handles" govern the migration `20260927_001_drop_reservation_release_mirror`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its normative text is kept unchanged as "A reservation's release handle has a single name", with every other scenario, since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: A lease records when it was activated

**Reason**: Its rule that every service hosting the site ledger adds the column in its migration chain, and its scenario "Existing reservations migrate with no activation recorded", govern the migration `20261106_001_reservation_activated_at`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history; the API-credit service's chain starts at its baseline with no adoption path, so no existing API-credit database is migrated. Its remaining rule, including that a null on a reservation predating the column says nothing about delivery, is kept unchanged as "A lease records its activation instant", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release, or any existing API-credit service database, starts that service from a fresh database; the rule is unchanged under the new requirement's name.
