## ADDED Requirements

### Requirement: A reservation's lease tail is written once

The site authority MUST record a reservation's lease tail (its executor target, executor
reference, lease start and end, and create handle) once. A lease is registered once the
reservation records an executor target. A first registration on a `reserved`,
`provisioning`, or `leased` reservation MUST record the tail it names and leave the
reservation `leased`. A repeated registration with the same executor target and lease start
MUST return the reservation unchanged and MUST NOT move its lease end. A registration naming
a different executor target or lease start MUST be refused. A registration on a `releasing`,
`release_failed`, or `unmanaged` reservation MUST be refused and MUST NOT change its state.
A recorded create handle MUST NOT be replaced, by registration or by any other write.

#### Scenario: A lease is registered on a committed reservation

- **WHEN** a lease is registered on a reservation that `commit` has already made `leased`
  and that records no executor target
- **THEN** the tail is recorded and the reservation stays `leased`

#### Scenario: A lease is registered again after it was truncated

- **WHEN** a registration is repeated with the reservation's recorded target and start and
  its original end after the lease was truncated
- **THEN** the reservation is returned with its truncated end

#### Scenario: A lease is registered on a releasing reservation

- **WHEN** a registration names a reservation that is `releasing`
- **THEN** it is refused, and the reservation stays `releasing`

### Requirement: Commit neither resurrects a lease nor moves a registered lease's window

Committing a reservation MUST be refused when the reservation is `releasing`,
`release_failed`, or `unmanaged`, and MUST NOT change its state. Before a lease is
registered, a repeated commit of a `leased` reservation MAY record the window it names.
Once a lease is registered, a commit MUST return the reservation unchanged and MUST NOT move
its lease start or end. A caller that registers a lease after committing MUST register the
window the commit returned.

#### Scenario: A storefront refreshes the window after provisioning

- **WHEN** a storefront commits a `leased` reservation again with a later window before it
  registers the lease
- **THEN** the later window is recorded, and the storefront registers with that window

#### Scenario: A resume pass commits a registered lease again

- **WHEN** a storefront's resume pass commits a registered lease with a window it computed
  from the current time
- **THEN** the reservation is returned unchanged, and the pass registers with the recorded
  window, which the registration accepts as a repeat

#### Scenario: A releasing lease is committed again

- **WHEN** a commit names a reservation whose release is in flight
- **THEN** it is refused, and the reservation stays `releasing` with its release handle

### Requirement: Lease truncation neither resurrects nor extends a lease

Ending a lease early MUST only move its lease end earlier. A truncation naming an end later
than the current one MUST be refused. A truncation of a `reserved`, `provisioning`,
`releasing`, `release_failed`, or `unmanaged` reservation MUST be refused and MUST NOT change
its state: an uncommitted hold is ended by releasing it, not by truncation. Once a lease is
registered, truncation is the only operation that moves its end.

#### Scenario: A storefront ends an uncommitted hold

- **WHEN** a settlement terminates while its reservation is still `reserved`
- **THEN** the storefront's release frees the hold, and the storefront does not truncate it

#### Scenario: A releasing lease is truncated

- **WHEN** a caller truncates a reservation whose release is in flight
- **THEN** the truncation is refused, and the reservation stays `releasing` with its
  release handle

#### Scenario: A truncation names a later end

- **WHEN** a caller truncates a lease to an end after its current end
- **THEN** the truncation is refused, and the lease end is unchanged

### Requirement: Capacity-definition import has a thin typed client

The capacity-definition import the provisioning service hosts MUST be callable through the
site capability's thin client, which carries its own request and response models and its
own route contract, held in step with the server's by the server-and-client parity test,
so a caller installs no persistence package to import definitions.

#### Scenario: An operator imports capacity definitions

- **WHEN** an operator imports a capacity-definition document through the site client
- **THEN** the request is signed from the site client's own contract, and the parity test
  fails if the server's contract for that route differs

### Requirement: Reservation supersede and the release guard

A negotiated shape change to an already-reserved capacity hold MUST NOT mutate the existing `CapacityReservation` or any settlement assignment already bound to it in place. `CapacityLedgerService.resize_reservation` supersedes it instead: one atomic transaction releases the old reservation, evaluates the new shape's candidacy as if the old hold had already cleared, reserves the new shape under a new `capacity_reservation_id`, and commits or rolls back all of it together. A new shape with no eligible candidate leaves the old reservation exactly as it was — still held, never released — rather than losing it. `resize_reservation` is a single self-managed-session method; it is not composed into a larger caller transaction.

The site authority reclaims capacity from a reservation in exactly three internal paths: a lapsed TTL hold, a terminal release, and a resize's supersede step. Each of these MUST consult an optional `CapacityReleaseGuard`, a `Protocol` this package defines without referencing fulfillment types, in the same transaction and with the same session as the reclaim. The guard answers whether the reservation's capacity may be freed and MAY abandon a not-yet-dispatched settlement assignment in that session; it MUST NOT commit the session. A refused reclaim MUST change nothing: a refused release returns no reservation, a refused resize leaves the old reservation held and unmodified, and a refused TTL lapse leaves the hold for a later sweep. A release of an already-released reservation still offers the guard the reservation, for its abandonment, and returns the released record. `market_site` MUST NOT import `market_fulfillment` to implement the guard, including under `TYPE_CHECKING`; the concrete implementation is supplied at composition time and alone decides what proves the capacity free. A composition that supplies no guard frees capacity on every reclaim.

#### Scenario: Resize evaluates the new shape as if the old hold already cleared

- **WHEN** a reservation is resized to a new shape that only fits once the old reservation's own held capacity is released
- **THEN** the resize succeeds, because release and re-evaluation happen inside the same transaction rather than as two independently committed steps

#### Scenario: Resize rolls back when the new shape is unavailable

- **WHEN** no candidate satisfies the new shape
- **THEN** the whole transaction rolls back and the old reservation remains held, unmodified, with no abandonment applied

#### Scenario: Capacity reclaim always consults the guard

- **WHEN** a TTL hold lapses, a reservation is released, or a resize supersedes a reservation
- **THEN** the configured `CapacityReleaseGuard`, if any, is consulted for the affected `capacity_reservation_id` in the reclaiming transaction, whether or not a settlement assignment exists for it

#### Scenario: The guard refuses a release

- **WHEN** a caller releases a reservation whose capacity the guard does not permit freeing
- **THEN** the release returns no reservation, the reservation keeps its state and capacity, and no settlement assignment is abandoned

## MODIFIED Requirements

### Requirement: A reservation's release handle has one name

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

#### Scenario: A compute provisioning database is upgraded

- **WHEN** a compute provisioning database whose reservation table holds a domain-prefixed release mirror is migrated
- **THEN** a reservation whose handle is held only in the mirror keeps it as `release_job_id`
- **AND** the mirror column is removed without losing any reservation's release handle or other reservation data
- **AND** a database without the column migrates unchanged

#### Scenario: A compute provisioning database holds two different release handles

- **WHEN** a reservation's `release_job_id` and its domain-prefixed mirror hold different values
- **THEN** the upgrade stops, naming the reservation, and changes nothing

## REMOVED Requirements

### Requirement: Reservation supersede and settlement abandonment

**Reason**: The settlement-abandonment hook only reacted to a reclaim; it could not stop
one, so any caller of the site's release could free a delivered lease's capacity with no
teardown proof. The hook becomes a release guard that also decides whether the capacity
may be freed.

**Migration**: Replaced by "Reservation supersede and the release guard" above, which keeps
the supersede rules unchanged and states the guard where the hook was.
