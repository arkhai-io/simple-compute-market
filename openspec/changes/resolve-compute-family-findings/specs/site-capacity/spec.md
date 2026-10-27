## MODIFIED Requirements

### Requirement: Reservation lifecycle
Capacity reservation MUST use a hold/commit/release lifecycle keyed by durable allocation identity, support expiry of uncommitted holds, and be idempotent for retries.

`reserve()` itself is idempotent by `deal_ref`'s `escrow_uid` when present: a repeat call for an escrow_uid with an existing reservation in any held state (`reserved`, `leased`, `releasing`, `release_failed`, `unmanaged`) returns that reservation rather than admitting a second one. This closes the retry gap `commit`/`release` already closed for their own calls: a caller retrying `reserve()` itself after a crash — before it durably recorded the first reservation's identity elsewhere — does not double-reserve capacity for the same deal. An escrow_uid whose prior reservation already expired or was released is not matched (it has moved out of the held states), so a genuinely new attempt after expiry still admits fresh.

#### Scenario: Two buyers reserve the same final unit
- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

#### Scenario: Reserve is retried for the same deal before its identity is durably recorded elsewhere
- **WHEN** `reserve()` is called again with the same `deal_ref.escrow_uid` while the first reservation is still in a held state
- **THEN** the existing reservation is returned and no additional capacity is admitted

#### Scenario: Reserve is retried after the prior hold expired
- **WHEN** `reserve()` is called again with an `escrow_uid` whose only prior reservation has already expired or been released
- **THEN** a new reservation is admitted, exactly as if no prior attempt had occurred

### Requirement: A reservation's lease tail is written once

The site authority MUST record a reservation's executor target once, written in the
transaction of the caller that records it, without changing the reservation's state or
window and without a capacity event. A recorded target MUST NOT be replaced, and none is
recorded on a `released` or `force_released` reservation. The create and release handles
are lifecycle evidence, and a recorded create handle MUST NOT be replaced.

#### Scenario: A target is recorded on a committed reservation

- **WHEN** a target is recorded on a reservation `commit` has made `leased`
- **THEN** the reservation records it, and its state and window are unchanged

#### Scenario: A different target is recorded later

- **WHEN** a target is recorded on a reservation that already records another
- **THEN** the recorded target is kept

#### Scenario: The recording transaction rolls back

- **WHEN** the caller's transaction that recorded a target rolls back
- **THEN** the reservation records no target

### Requirement: The lease lifecycle's writes are conditional transitions

Each write the lease lifecycle makes to a reservation MUST be a transition conditioned on
the reservation's current state, refused, with nothing written, from any other state, so
that a lifecycle acting on a stale read cannot undo what an operator or a completed release
recorded:

- Entering `releasing` MUST be allowed from `reserved`, `leased`, and `release_failed` (a
  retry). A reservation already `releasing` under the same release handle MUST be returned
  unchanged; one releasing under another handle MUST be refused.
- Recording a release failure MUST be allowed from `reserved`, `leased`, and `releasing`. A
  `releasing` reservation MUST still be releasing under the handle the failure was
  observed for.
- Handing a reservation to an operator (`unmanaged`) MUST be allowed only from `leased`.
- Only a forced release MAY free an `unmanaged` reservation.

No interface MAY set a reservation's state other than through these transitions, commit,
release, expiry, and forced release.

#### Scenario: A stale cycle meets a lease an operator took over

- **WHEN** a lease cycle that read a lease as `leased` asks to begin releasing it after an
  operator has taken it over
- **THEN** the transition is refused, and the reservation stays `unmanaged`

#### Scenario: A stale failure meets a force-released lease

- **WHEN** a release failure observed before an operator force-released the lease is
  recorded afterwards
- **THEN** it is refused, the reservation stays `force_released`, and its capacity stays free

#### Scenario: A caller asks to set a state directly

- **WHEN** a caller wants a reservation in a given state
- **THEN** no ledger operation writes a state it names; the reservation reaches the state
  only through the lifecycle's transitions

### Requirement: Lease truncation neither resurrects nor extends a lease

Ending a lease early MUST only move its lease end earlier. A truncation naming an end later
than the current one MUST be refused. A truncation of a `reserved`, `releasing`,
`release_failed`, or `unmanaged` reservation MUST be refused and MUST NOT change its state:
an uncommitted hold is ended by releasing it, not by truncation. Once a lease is committed,
truncation is the only operation that moves its end.

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

## ADDED Requirements

### Requirement: A stored reservation in a retired state is converted at upgrade

A service whose database holds the site ledger MUST, in its migration chain, convert a
reservation stored as `provisioning` to `unmanaged` and one stored as `provisioning_failed`
to `force_released`, each with a failure reason naming the state it held, so that every
reservation keeps its capacity effect and reads in a state the lifecycle defines.

#### Scenario: A held reservation in a retired state is upgraded

- **WHEN** a database holding a `provisioning` reservation is migrated
- **THEN** the reservation is `unmanaged`, its capacity stays held until an operator
  repairs it, and its failure reason names `provisioning`

#### Scenario: A terminal reservation in a retired state is upgraded

- **WHEN** a database holding a `provisioning_failed` reservation is migrated
- **THEN** the reservation is `force_released`, its capacity stays free, and its failure
  reason names `provisioning_failed`

#### Scenario: No reservation holds a retired state

- **WHEN** a database with no such reservation is migrated
- **THEN** no reservation changes

### Requirement: A site authority answers an unroutable request by what failed to match

The site kit's authentication middleware MUST answer a request that resolves to no route
contract, without signing it, with 404 when no contract names its path, 405 naming the
allowed methods when a contract names its path under another method, and 400 naming the
field when its route's body resource cannot be bound. The middleware MUST resolve a request
against the one ordered table it is given, the first matching contract deciding, so no
request is claimed by two contracts. The site client MUST report an answer carrying no
response authentication as unauthenticated, with its status, and the report MUST contain
no part of the response body, no header value, and no credential.

#### Scenario: A known path is requested with another method

- **WHEN** a signed request uses a method no contract binds to a path a contract names
- **THEN** the authority answers an unsigned 405 whose `Allow` names the contract's method

#### Scenario: The site client receives an unauthenticated answer

- **WHEN** the site client receives an answer with no response authentication
- **THEN** it fails closed and reports the status and that the answer was unauthenticated
