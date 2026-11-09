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

## REMOVED Requirements

### Requirement: Capacity schema separation

**Reason**: Its only scenario, "Existing host migration", described the pre-floor migration that placed every existing host in the default resource pool before fulfillment records were backfilled; that migration is part of compute provisioning's v0.3.0 floor and its body is deleted with the pre-floor history. Its normative text is kept unchanged as "A capacity reservation is stored apart from its host, pool, and assignment", with a scenario stating the separation itself, since a MODIFIED requirement cannot drop a scenario.

**Migration**: None: the schema's rule is unchanged under the new requirement's name.

### Requirement: A stored reservation in a retired state is converted at upgrade

**Reason**: The conversion it governs (`20261028_001_retired_reservation_states`) is part of compute provisioning's v0.3.0 floor, so every provisioning database the chain adopts has already run it and the chain refuses any older one; the API-credit service's chain starts at its baseline with no adoption path, so no existing API-credit database is migrated. No supported database can still hold a reservation in a retired state, and the conversion is deleted with each service's pre-floor history.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release, or any existing API-credit service database, starts that service from a fresh database.
