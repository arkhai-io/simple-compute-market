## ADDED Requirements

### Requirement: Per-site projection state is kit-owned and held once per process

The storefront-side capacity and publication kit MUST own per-site projection state: for
every site a storefront's aggregate capacity client names, the resource-pool and
capacity-bucket projections, their poller, a per-site refresh, the poller's cycle on demand,
the drift check a topology-sensitive error triggers, and a per-site, per-family status. A
storefront that derives listings from site projections MUST compose exactly one instance per
process, built by its composition root and injected into every
consumer; the kit MUST NOT keep that state at module level, and a domain MUST NOT keep a
projection cache of its own. The poller MUST run as a loop registered with the storefront's
loop controller, and its step MUST run exactly the poller's cycle. The state MUST be
domain-neutral: it holds whatever generation a site serves, and a domain's acceptance rules
for a generation apply when that domain reads it. It MUST run one operation at a time on a
site's family, including its version check, so a caller arriving during an operation waits for
it and a failed operation never replaces a confirmation that completed after it began.

#### Scenario: Two consumers read one site

- **WHEN** a storefront's publication cycle and its opening recheck both read one site's
  resource-pool projection
- **THEN** both read the same held generation from the one instance their composition root
  built, and neither fetches the site

#### Scenario: The projection step is run while held

- **WHEN** an operator runs one cycle of the site-projection loop while the loops are held
- **THEN** exactly the poller's cycle runs, waking publication if a resource-pool
  generation changed, and the loops remain held

#### Scenario: One domain refuses a generation

- **WHEN** a site serves a generation one domain's acceptance rule refuses
- **THEN** the state holds that generation, the refusing domain holds that site's listings,
  and any other reader of the state still reads it

### Requirement: A loop records each cycle's outcome with the controller

A storefront loop whose cycle can fail MUST record each cycle's outcome with the kit loop
controller, whether its timer or an operator's step ran the cycle: when it finished,
whether it completed, and, for a failure, the stage that failed and its error. Each
invocation MUST record exactly one terminal outcome, including one that raised, and a
preview MUST record none; a step cancelled while it waits for the loop's lock records a
cancelled outcome naming no stage, because no stage began. A recorded error MUST carry the exception's type and MUST carry its
message only when the storefront's own configuration or publication error raised it, so no
credential, secret, or private URL reaches status. The controller MUST be the one place a loop's cycle runs: a loop
registers its step and its interval, the controller's timer runs the step through the same
operation an operator's step does, and that operation holds the loop's lock, so the timer and a
step never run a cycle concurrently. A kit runtime that fans one loop out into independent
per-site cycles MUST serialize each site's cycle and that site's step instead, and MUST record
each site's timer cycle with the controller under that site's own loop name.
The controller MUST report, in one snapshot, every loop's state and the last outcome each loop
recorded, for a storefront's system status to read; a loop that has exited or been cancelled
MUST remain distinguishable from a running loop whose last cycle failed.

#### Scenario: A stepped cycle fails

- **WHEN** an operator steps the publication loop and the cycle fails
- **THEN** the controller's snapshot reports that cycle as failed with its error, as it
  would for a timer-run cycle

#### Scenario: A step is requested while the timer's cycle runs

- **WHEN** an operator steps a loop whose timer cycle is in progress
- **THEN** the step runs after that cycle completes, never alongside it, and each records its
  own outcome

#### Scenario: One site's capacity-event feed fails

- **WHEN** one site's capacity-event poller cycle fails while another site's succeeds
- **THEN** the controller's snapshot reports the failing site's loop with that cycle failed, by
  its error's type, and the other site's loop with its own outcome

#### Scenario: A cycle fails on an unexpected exception

- **WHEN** a publication cycle raises an exception that is not one of the storefront's own
  errors, with a message naming a site URL
- **THEN** the recorded outcome names the failing stage and the exception's type, and not its
  message

## MODIFIED Requirements

### Requirement: Storefront timer loops are held and stepped through one kit controller

Each storefront process MUST hold exactly one kit-owned loop controller and MUST
register with it every timer-driven loop the process runs. A domain MUST NOT
implement its own pause flag, gate, or loop-state reporting. A loop whose tasks are
created by a kit runtime the storefront composes, such as a per-site fan-out, MUST be
declared to the controller by name so that a pause waits for it.

A registration MUST bind the loop's name to the step that runs exactly one cycle of
it, and MAY bind a read-only preview of that cycle. The step MUST invoke the same
operation the loop's timer invokes, so a manual cycle cannot exercise behaviour the
timer does not. A loop MUST register in one of two forms: a timer loop, whose timer
the controller runs over its step, or a fan-out, whose task a composed kit runtime
owns and which runs independent per-child cycles, each child under its own declared
name. A fan-out MUST register with its step and the names of its children, and each
child MUST be declared as the fan-out's child when it registers, so status lists every
child before its first cycle; a child the fan-out's task reaches later MUST be declared
then. A name registered in one form MUST be refused in the other. A storefront MAY
register a loop's step before the loop itself, so every step is invocable from the
moment the storefront serves, but a step registration runs no loop. Starting the
registered loops MUST be the only way a loop's task starts, and it MUST start every
registered timer and fan-out together; it MUST name every fan-out's children before
starting any task, so a fan-out whose children cannot be named leaves no loop started.

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

#### Scenario: A fan-out's children are listed before their first cycle

- **WHEN** a storefront registers its capacity-event fan-out for its configured sites
- **THEN** status lists each site's poller before the fan-out starts, and starting the
  storefront's loops starts the fan-out's task with the timers

#### Scenario: A name is registered in both forms

- **WHEN** a loop name registered as a timer loop is registered as a fan-out, or the
  reverse
- **THEN** the second registration is refused and the first stands

#### Scenario: An unregistered loop is stepped

- **WHEN** an operator runs one cycle of a name no loop registered
- **THEN** the request is refused as not found and no work runs

#### Scenario: A storefront restarts while paused

- **WHEN** a storefront whose loops were held restarts
- **THEN** its loops run on their timers until an operator pauses them again
