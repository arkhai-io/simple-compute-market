## ADDED Requirements

### Requirement: A reservation carries one release handle

A Capacity Reservation MUST carry exactly one durable release handle,
`release_job_id`, regardless of the reservation's offering mode. The site
authority MUST NOT persist a domain-prefixed mirror of it, and every lease
contract that publishes a release handle MUST publish it as `release_job_id`.
A lease update naming a retired mirror field MUST be refused rather than
silently ignored.

#### Scenario: A VM reservation begins releasing

- **WHEN** the compute lifecycle records the release job for a reservation whose offering mode is the VM mode
- **THEN** the reservation's `release_job_id` is set and no second, VM-named field is written

#### Scenario: A lease is read through either adapter

- **WHEN** a VM lease or a bare-metal lease is read through its adapter's lease contract
- **THEN** the release handle is published as `release_job_id` and under no other name

#### Scenario: A lease update names the retired mirror

- **WHEN** a lease update carries `vm_remove_job_id`
- **THEN** the update is refused with a validation error naming `release_job_id`

#### Scenario: A reservation table is upgraded

- **WHEN** a site database that holds the retired column is migrated
- **THEN** the column is removed through the same table rebuild that removed earlier physical-placement columns, and a database without the column migrates unchanged
