## ADDED Requirements

### Requirement: A reservation's release handle has one name

A Capacity Reservation MUST represent its durable release handle, when it has
one, only as `release_job_id`, regardless of the reservation's offering mode. The
handle is absent until release begins. The site authority MUST NOT write a
domain-prefixed mirror of it. Every lease contract that publishes a release
handle, or accepts one in a lease update, MUST name it `release_job_id`.

A reservation's pool, offering mode, and teardown path differ by domain, but the
handle a caller follows to observe release does not, so one name serves every
offering mode that shares the reservation table.

#### Scenario: A VM reservation begins releasing

- **WHEN** the compute lifecycle records the release job for a reservation whose offering mode is the VM mode
- **THEN** the reservation's `release_job_id` is set and no second, VM-named field is written

#### Scenario: A lease is read through either adapter

- **WHEN** a VM lease or a bare-metal lease is read through its adapter's lease contract
- **THEN** the release handle is published as `release_job_id` and under no other name

#### Scenario: An operator corrects a lease's release handle

- **WHEN** a VM lease update supplies `release_job_id`
- **THEN** the reservation's release handle is replaced with that value and the lease response publishes it

#### Scenario: A compute provisioning database is upgraded

- **WHEN** a compute provisioning database whose reservation table holds a domain-prefixed release mirror is migrated
- **THEN** a reservation whose handle is held only in the mirror keeps it as `release_job_id`
- **AND** the column is removed through the same table rebuild that removed earlier physical-placement columns
- **AND** a database without the column migrates unchanged

#### Scenario: A compute provisioning database holds two different release handles

- **WHEN** a reservation's `release_job_id` and its domain-prefixed mirror hold different values
- **THEN** the upgrade stops, naming the reservation, and changes nothing
