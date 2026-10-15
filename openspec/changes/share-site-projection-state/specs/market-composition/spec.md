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
preview MUST record none. A recorded error MUST carry the exception's type and MUST carry its
message only when the storefront's own configuration or publication error raised it, so no
credential, secret, or private URL reaches status. The controller MUST be the one place a loop's cycle runs: a loop
registers its step and its interval, the controller's timer runs the step through the same
operation an operator's step does, and that operation holds the loop's lock, so the timer and a
step never run a cycle concurrently. A kit runtime that fans one loop out into independent
per-site cycles MUST serialize each site's cycle and that site's step instead.
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

#### Scenario: A cycle fails on an unexpected exception

- **WHEN** a publication cycle raises an exception that is not one of the storefront's own
  errors, with a message naming a site URL
- **THEN** the recorded outcome names the failing stage and the exception's type, and not its
  message
