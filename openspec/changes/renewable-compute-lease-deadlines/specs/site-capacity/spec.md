## ADDED Requirements

### Requirement: Commit records an activation deadline where the pool resolves a delivery deadline

The first commit of a reservation whose pool resolves a delivery deadline MUST record an activation deadline: the later of the deal's commitment instant, as the commit supplies it, and the lease start, plus the deal's accepted `delivery_deadline_seconds` where the commit carries one, else plus the value the pool resolves. A commit to a pool that resolves none MUST record none, whatever the commit carries. A recorded deadline MUST NOT be rewritten by a repeated commit, by activation, by truncation, or by a later change to the pool. A reservation committed before the site recorded deadlines MUST carry none. The site's reservation view MUST show the deadline, null where none is recorded.

#### Scenario: A commit carries the deal's accepted deadline

- **WHEN** a reservation in a pool resolving 1800 seconds is first committed with an accepted deadline of 1800 seconds, a commitment instant of 10:00 and a lease starting at 10:00
- **THEN** the site records an activation deadline of 10:30

#### Scenario: A lease starts after the deal's commitment

- **WHEN** a lease starting at 12:00 is committed with a commitment instant of 10:00 and an accepted deadline of 1800 seconds
- **THEN** its activation deadline is 12:30, and its agreed window is unchanged

#### Scenario: A commit carries no accepted deadline

- **WHEN** a commit carrying no accepted deadline names a reservation in a pool resolving 1800 seconds
- **THEN** the site records a deadline from the pool's 1800 seconds

#### Scenario: The pool states that it enforces none

- **WHEN** a commit carrying an accepted deadline names a reservation in a pool that resolves none
- **THEN** the reservation is committed with no activation deadline

#### Scenario: The pool was lengthened after the deal was accepted

- **WHEN** a deal accepted with 1800 seconds is committed after its pool's deadline was raised to 3600
- **THEN** the site records the deadline from 1800 seconds

#### Scenario: A commit is repeated after the pool changes

- **WHEN** a committed reservation is committed again after its pool's delivery deadline changed
- **THEN** its recorded deadline is unchanged

#### Scenario: A lease predates the deadline

- **WHEN** the site's schema is migrated over a lease committed before it recorded deadlines
- **THEN** the lease carries no activation deadline

### Requirement: An unactivated lease is due at its activation deadline

A lease with an activation deadline and no recorded activation MUST be due at the earlier of that deadline and its lease end. A lease with a recorded activation, and a lease with no activation deadline, MUST be due only at its lease end; a null `activated_at_utc` MUST NOT by itself make a lease due. Admission MUST account a lease's agreed window whatever its deadline, and its capacity MUST stay held until release succeeds.

#### Scenario: A storefront stops before delivery

- **WHEN** a lease's activation deadline passes with no activation recorded and its lease end still ahead
- **THEN** the lease is due

#### Scenario: A lease was activated before its deadline

- **WHEN** an activated lease's activation deadline passes with its lease end still ahead
- **THEN** the lease is not due

#### Scenario: A lease with no deadline was never activated

- **WHEN** a lease with no activation deadline and no recorded activation is read before its lease end
- **THEN** the lease is not due

#### Scenario: A reservation overlaps a lease past its deadline

- **WHEN** a new reservation overlaps the agreed window of a lease whose activation deadline has passed and whose release has not succeeded
- **THEN** admission still accounts the lease against capacity

## MODIFIED Requirements

### Requirement: The lease lifecycle's writes are conditional transitions

Each write the lease lifecycle makes to a reservation MUST be a transition conditioned on
the reservation's current state, refused, with nothing written, from any other state, so
that a lifecycle acting on a stale read cannot undo what an operator or a completed release
recorded:

- Entering `releasing` MUST be allowed from `reserved`, `leased`, and `release_failed` (a
  retry). A reservation already `releasing` under the same release handle MUST be returned
  unchanged; one releasing under another handle MUST be refused.
- Entering `releasing` because a lease became due MUST also be conditioned on what the due
  read observed of the lease: its lease end, any deadline the site enforces on it, and
  whether an activation was recorded. Where any of them has changed, the transition MUST be
  refused, with no event, no report and no provider call.
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

#### Scenario: Activation wins against a stale due read

- **WHEN** a cycle reads a lease due at its activation deadline, and the lease is activated
  before the cycle asks to begin releasing it
- **THEN** the transition is refused with nothing written, and the lease stays `leased`
  until its lease end

#### Scenario: Expiry wins against activation

- **WHEN** a cycle begins releasing a lease it read as due and unactivated, and activation
  is requested afterwards
- **THEN** the lease is `releasing` once, and the activation is refused

#### Scenario: A truncation falls between the due read and the claim

- **WHEN** a lease's end is truncated after a cycle read it as due and before the cycle asks
  to begin releasing it
- **THEN** the transition is refused with nothing written, and a later cycle reads the lease
  again

### Requirement: Commit begins a lease once and never resurrects one

The first commit of a reservation MUST leave it `leased` with its window: the start named,
else the time of the commit, and the end named. A lease with no negotiated start therefore
begins at commit. A repeated commit of a `leased` reservation MUST return it unchanged and
MUST NOT move its lease start or end, whatever window it names. Committing a reservation
MUST be refused when the reservation is `releasing`, `release_failed`, or `unmanaged`, and
MUST NOT change its state. A commit MAY name the deal it serves; an escrow it names MUST be
recorded where the reservation records none, on a repeated commit too, and MUST NOT replace
a recorded one. A commit MAY carry the deal's accepted `delivery_deadline_seconds` and its
commitment instant. A first commit whose accepted deadline exceeds the delivery deadline
its pool resolves MUST be refused, leaving the reservation's state unchanged and recording
nothing. A commit MUST answer with the reservation as the authority recorded it,
through every client layer between the caller and the authority.

#### Scenario: A resume pass commits a lease again

- **WHEN** a storefront's resume pass commits a `leased` reservation with a window it
  computed from the current time
- **THEN** the reservation is returned unchanged, with the window its first commit recorded

#### Scenario: A truncated lease is committed again

- **WHEN** a lease committed until T2 is truncated to T1 and a commit then names T2
- **THEN** the reservation is returned unchanged and the lease ends at T1

#### Scenario: A hold placed before the deal had an escrow is committed

- **WHEN** a reservation that records no escrow is committed with a deal reference naming
  one
- **THEN** the reservation records that escrow, and an operator finds it through the site's
  escrow filter

#### Scenario: A releasing lease is committed again

- **WHEN** a commit names a reservation whose release is in flight
- **THEN** it is refused, and the reservation stays `releasing` with its release handle

#### Scenario: The pool was shortened below the deal's accepted deadline

- **WHEN** a deal accepted with 1800 seconds is first committed after its pool's delivery
  deadline was lowered to 900
- **THEN** the commit is refused, and the reservation stays `reserved` with no deadline
  recorded
