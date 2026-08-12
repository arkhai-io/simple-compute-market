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
a loop held idle by the pause, a loop whose cycle began before the pause was requested
and has not yet returned to its gate, and a loop that has ended on its own. Reporting
only whether the pause flag is set does not satisfy this: the flag records what was
requested, and the per-loop state records what is true, which only the loop itself can
establish by reaching its gate.

Pausing MUST wait for loops to reach their gates before reporting, and that wait MUST
be bounded. A loop's gate is at the end of its interval, and intervals may be tens of
seconds, so an unbounded wait would make an operator control unresponsive. A loop that
has not reached its gate inside the window MUST be reported as still stopping rather
than as stopped, and that MUST NOT be an error: a cycle in flight is a normal state to
report, and failing the request would replace an accurate answer with none.

#### Scenario: Pausing holds every loop idle

- **WHEN** an operator pauses a storefront and every loop reaches its gate
- **THEN** no timer loop performs further work until it is resumed, and the response
  reports each loop as paused

#### Scenario: A cycle already running when the pause is requested

- **WHEN** a loop is part-way through a cycle at the moment a pause is requested
- **THEN** that cycle runs to completion, the loop is reported as still stopping
  rather than stopped, and the pause request itself succeeds

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

### Requirement: A loop's reported state is established by the loop

A storefront MUST derive each loop's reported state from evidence the loop itself
produces, not from the existence of the task running it. A loop that has been scheduled
but has not yet reached its gate MUST be reported as starting, distinctly from a loop
that is cycling: the first cannot yet observe a pause, and reporting the two alike lets a
caller pause a storefront whose loops have not begun and receive an answer that cannot be
true.

Reading the pause flag and acknowledging the gate MUST NOT be separately available to a
loop. A loop that consults the pause without acknowledging is indistinguishable, from
outside the process, from one that never reaches a gate at all, and the pause control
cannot then report what is true of it.

#### Scenario: A scheduled loop that has not yet cycled

- **WHEN** a storefront reports loop state before a loop has reached its gate for the
  first time
- **THEN** that loop is reported as starting rather than as running

#### Scenario: Every loop acknowledges

- **WHEN** an operator pauses a storefront whose loops are all cycling
- **THEN** every loop reaches its gate within the bounded wait and is reported paused,
  with none left reported as still stopping

### Requirement: Readiness, liveness, and diagnosis are separate surfaces

A storefront MUST distinguish whether its process is worth keeping from whether it can be
relied on. Liveness MUST fail only for a condition no further running can resolve. A loop
that has ended on its own is such a condition while no supervisor restarts one, because
replacing the process is then the only recovery available.

Readiness MUST fail while any timer loop has not yet begun cycling, since a storefront
whose loops have not started will not perform the background work a caller relies on, and
MUST report that condition distinctly from a fault.

A storefront held at its lifecycle pause MUST remain ready. The pause is operator-requested,
the storefront continues to serve and to trade, and treating it as unreadiness would make
an operator control indistinguishable from a failure.

Diagnostic status MUST remain available regardless of either, and MUST report per-loop
state, since a caller consults it precisely when one of the other two is failing.

#### Scenario: A storefront whose loops have not started

- **WHEN** a caller probes readiness before every loop has begun cycling
- **THEN** readiness fails and reports the condition as starting rather than as a fault,
  while liveness continues to succeed

#### Scenario: A storefront with a dead loop

- **WHEN** a timer loop has ended on its own and no supervisor will restart it
- **THEN** both liveness and readiness fail, so the process is replaced rather than left
  serving with background work silently stopped

#### Scenario: A paused storefront is ready

- **WHEN** a caller probes readiness while the lifecycle pause is held
- **THEN** readiness succeeds, and diagnostic status reports each loop as paused

### Requirement: A bounded operator query reports its own truncation

An operator-facing query that caps the rows it returns MUST allow a caller to tell a
complete result from a capped one. Returning a row count alone does not satisfy this: a
caller receiving exactly the cap cannot distinguish the two, and a caller reasoning about
a complete history will silently reason about part of one.

#### Scenario: A query that reaches its cap

- **WHEN** a caller requests more rows than the surface will return and the available rows
  reach that cap
- **THEN** the response reports that it was truncated, in addition to the rows returned
