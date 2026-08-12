## ADDED Requirements

### Requirement: A paused storefront performs no timer-driven work

A storefront MUST expose its trading pause and its lifecycle pause as independent
controls. Refusing new negotiations and halting timer-driven work are different
requests: a storefront that stops accepting deals is still expected to finish those
it has accepted, and a storefront whose loops are idle is still expected to trade.
Neither control MAY imply the other.

The lifecycle pause MUST hold every timer-driven loop the storefront runs idle, so
that a storefront with its loops paused changes no state on its own. A loop MUST observe the pause at a cycle boundary: a cycle either runs
to completion or does not begin, and a paused loop MUST NOT be interrupted part-way
through one. Loops MUST NOT be torn down to achieve this, so loop-local position and
progress survive a pause and resuming continues from where the loop stopped rather
than re-converging from an initial state.

A storefront MUST report each loop's current state, and that report MUST distinguish
a loop held idle by the pause from one that has ended on its own. Reporting only
whether the pause flag is set does not satisfy this: the flag records what was
requested, and the per-loop state records what is true.

#### Scenario: Pausing holds every loop idle

- **WHEN** an operator pauses a storefront
- **THEN** no timer loop performs further work until the storefront is resumed, and
  the response reports each loop as paused

#### Scenario: A paused loop retains its position

- **WHEN** a storefront is paused while a loop holds a position in a feed or sweep
- **THEN** that position is unchanged on resume and the loop continues from it,
  rather than restarting from an initial position

#### Scenario: A loop that ends on its own is distinguishable

- **WHEN** a timer loop exits unexpectedly and the storefront is then paused
- **THEN** that loop is reported as exited rather than as paused, so an operator can
  tell a halted loop from a failed one

### Requirement: Lifecycle cycles are operator-invocable while paused

A storefront MUST expose, for each timer loop whose work a caller may need to drive
deliberately, a control that runs one cycle on demand. Such a control MUST invoke the
same operation the loop itself invokes and MUST NOT implement an alternate
transition. Where a loop's work has no separately callable unit, the control MUST
invoke the nearest production handler covering that work and the difference MUST be
recorded at the control.

These controls MUST remain available while the storefront is paused, since operating
on a paused storefront is their purpose.

#### Scenario: A cycle runs while paused

- **WHEN** a caller invokes a lifecycle cycle control on a paused storefront
- **THEN** the underlying operation runs once and its result is returned, and the
  storefront remains paused

#### Scenario: A control does not diverge from its loop

- **WHEN** a lifecycle cycle control runs
- **THEN** the state transitions it produces are those the timer-driven loop would
  produce, so behaviour observed through the control is behaviour production
  exhibits

### Requirement: Lifecycle control coverage is per storefront

Operator lifecycle controls belong to the storefront implementing them and are not
implied for every storefront in the system. A storefront that runs timer loops
without exposing these controls cannot be paused or advanced, and callers MUST NOT
assume otherwise from the presence of the controls elsewhere.

Currently the VM storefront implements pause-and-advance. The API-credits storefront
runs equivalent timer loops — capacity-event polling, projection refresh, claims
sweeping, and fulfillment resumption — and exposes no control over them; its
background work continues regardless of its pause state. This is a current
limitation rather than a deliberate difference in behaviour between the two.

#### Scenario: A storefront without lifecycle controls

- **WHEN** a caller pauses a storefront that does not implement lifecycle controls
- **THEN** new negotiations are refused but timer-driven work continues, and no cycle
  control is available to drive that work deliberately
