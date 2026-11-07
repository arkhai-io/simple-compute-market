## ADDED Requirements

### Requirement: Storefront timer loops are held and stepped through one kit controller

Each storefront process MUST hold exactly one kit-owned loop controller and MUST
register with it every timer-driven loop the process runs. A domain MUST NOT
implement its own pause flag, gate, or loop-state reporting. A loop whose tasks are
created by a kit runtime the storefront composes, such as a per-site fan-out, MUST be
declared to the controller by name so that a pause waits for it.

A registration MUST bind the loop's name to the step that runs exactly one cycle of
it, and MAY bind a read-only preview of that cycle. The step MUST invoke the same
operation the loop's timer invokes, so a manual cycle cannot exercise behaviour the
timer does not. A loop with no timer MAY register a step alone.

One pause MUST hold every registered loop at a cycle boundary without cancelling it:
a cycle either completes or never starts, and loop-local state survives the pause.
While held, every registered step MUST remain invocable. Resuming MUST return every
held loop to work. Holding loops MUST NOT affect whether the storefront accepts new
negotiations, which is a separate control.

A loop body MUST read its gate when it starts, so a pause is observable from the
moment the loop runs, and MUST read its gate immediately before doing any work. It
MUST wait out its interval through the controller, which returns early when a pause
is requested. A pause requested at any point in a loop's interval MUST therefore be
observed before that loop's next cycle's work, independently of the interval's
length.

The loop pause MUST be process-local. A restarted storefront MUST resume its loops.

#### Scenario: Every storefront loop is held by one pause

- **WHEN** an operator pauses the lifecycle loops of a storefront
- **THEN** every timer-driven loop that storefront runs, including loops created by a
  composed kit runtime, stops at its next cycle boundary
- **AND** the storefront continues to accept new negotiations

#### Scenario: A held loop is stepped

- **WHEN** the loops are held and an operator runs one cycle of a registered loop
- **THEN** exactly the operation the loop's timer invokes runs once and its result is
  returned
- **AND** the loops remain held

#### Scenario: A pause arrives during a long interval

- **WHEN** a loop with a long interval is waiting between cycles and a pause is
  requested
- **THEN** the loop reaches its gate without waiting out the interval and performs no
  further work until resumed or stepped

#### Scenario: An unregistered loop is stepped

- **WHEN** an operator runs one cycle of a name no loop registered
- **THEN** the request is refused as not found and no work runs

#### Scenario: A storefront restarts while paused

- **WHEN** a storefront whose loops were held restarts
- **THEN** its loops run on their timers until an operator pauses them again

### Requirement: A loop's reported state is established by the loop

A loop's reported state MUST be derived from what the loop has itself acknowledged
at its gate, never from the existence of the task running it. The controller MUST
report each registered or declared loop as one of:

- `starting` — the loop has not yet reached its gate, and so cannot yet observe a
  pause;
- `running` — no pause is requested and the loop has reached its gate;
- `pausing` — a pause is requested and the loop has not yet acknowledged it, so a
  cycle that began before the request may still be writing;
- `paused` — the loop has acknowledged the pause at its gate;
- `exited` or `cancelled` — the loop's task has ended.

A pause request MUST wait, within a bounded window, for every live loop to
acknowledge and MUST then report each loop's state as it stands. A loop that has not
acknowledged within the window MUST be reported `pausing` or `starting`, never
`paused`. The controller MUST be able to name which loops are `starting` and which have
`exited` or been `cancelled`, so a health surface can distinguish a loop that has not
begun from one that has ended.

#### Scenario: A loop is mid-cycle when a pause is requested

- **WHEN** a pause is requested while a loop is part-way through a cycle
- **THEN** that loop is reported `pausing` until it reaches its gate, and `paused`
  only afterwards

#### Scenario: A loop has not yet begun cycling

- **WHEN** a pause is requested before a newly started loop has reached its gate
- **THEN** that loop is reported `starting`, not `paused`

#### Scenario: A loop ends on an exception

- **WHEN** a registered loop's task ends on its own
- **THEN** the loop is reported `exited` rather than `paused` or `running`
- **AND** the controller names it among the loops that have ended
