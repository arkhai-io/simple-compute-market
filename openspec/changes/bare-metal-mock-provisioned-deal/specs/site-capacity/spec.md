## ADDED Requirements

### Requirement: A reservation's lease tail is written once

The site authority MUST record a reservation's lease tail (its executor target, executor
reference, lease start and end, and create handle) once. A first attachment MUST apply
only to a held reservation that is not yet leased. A repeated attachment to a leased
reservation with the same executor target and lease start MUST return the reservation
unchanged and MUST NOT move its lease end. An attachment naming a different executor
target or lease start MUST be refused. An attachment to a `releasing`, `release_failed`,
or `unmanaged` reservation MUST be refused and MUST NOT change its state. A recorded create
handle MUST NOT be replaced.

#### Scenario: A lease is attached again after it was truncated

- **WHEN** a lease attachment is repeated with the reservation's original window after the
  lease was truncated
- **THEN** the reservation is returned with its truncated end

#### Scenario: A lease is attached to a releasing reservation

- **WHEN** a lease attachment names a reservation that is `releasing`
- **THEN** it is refused, and the reservation stays `releasing`

### Requirement: Lease truncation neither resurrects nor extends a lease

Ending a lease early MUST only move its lease end earlier. A truncation naming an end later
than the current one MUST be refused. A truncation of a `releasing`, `release_failed`, or
`unmanaged` reservation MUST be refused and MUST NOT change its state. Truncation is the
only operation that moves a recorded lease end.

#### Scenario: A releasing lease is truncated

- **WHEN** a caller truncates a reservation whose release is in flight
- **THEN** the truncation is refused, and the reservation stays `releasing` with its
  release handle

#### Scenario: A truncation names a later end

- **WHEN** a caller truncates a lease to an end after its current end
- **THEN** the truncation is refused, and the lease end is unchanged
