---
tags: [engineering, testing]
---

# System tests

How a system test — an end-to-end scenario across deployed services
([Test levels](test-levels.md), "System tests") — is written, and what its evidence
can claim.

## A scenario is a sequence of state changes

A system test proves a deterministic sequence of state changes — a sequence diagram
run repeatably — never wall-clock time. A timer left running is an unscripted
participant in that diagram, and a scenario whose duration a timer sets measures the
timer rather than the work.

A scenario asserts only on side effects it asked for. While a service's timer loops
run, an observation races them: a record reconciled a second later reads differently
from one reconciled a second earlier, and waiting for the system to settle cannot
establish ordering even when it passes. So a scenario:

- holds every loop it depends on once, at the start, through the pause and step
  controls ([Test seams](test-seams.md), "Pause the loop, then advance it
  explicitly");
- for each transition, previews the move where the service offers a preview,
  advances exactly one side effect, and measures that effect through the services'
  typed clients;
- waits only on a request it made, or on an effect its own request caused, bounded —
  an event its request emits, or a message it sends off the request path — or, in
  a run on the wall clock (see "Time a test does not control"), for an instant the
  scenario's own data fixes, then advances what acts on that instant explicitly;
  where one service reads another's state live, it reads the effect once after its
  step rather than polling for it;
- reaches an instant by setting the time every participant perceives, together,
  never by waiting and never by moving one participant alone: once the clocks of
  two participants that exchange signed or timestamped messages disagree by more
  than the exchange's tolerance, every exchange between them fails, and a decision
  one participant dates in another's future is never acted on. Moving a record's
  time into the past and stepping the loop that acts on it, which runs exactly the
  code an expiry runs, is admitted below setting time: weaker, since only that
  record moves, and discouraged once the participants' time can be set;
- leaves a behaviour defined by a window or interval elapsing to a level that can
  drive the clock, rather than waiting for it.

## Time a test does not control

A scenario run against a component whose time it cannot set — a hosted provider, a
security component with a clock of its own — handles that component's time by the
first of these that applies:

- if the scenario does not exercise the component's time-dependent behaviour, keep
  its times out of the way: expiries and windows set far enough ahead that no run
  reaches them;
- if it does, control the component's time through a control of its own, such as a
  provider's test clock, or else through a double standing in for the component
  whose time is set with every other participant's;
- below those, move the record's time into the past and step the loop that acts on
  it;
- otherwise the run uses the wall clock throughout: it waits only for an instant
  the scenario's own data fixes, and a stage needing any other instant skips,
  naming the instant it needed and the component whose time it could not set.

A proxy rewriting the times in a component's responses is none of these: it
changes only what the component reports, never when it acts, and cannot rewrite a
signed value, so it serves only times the scenario does not exercise.

A run either sets every participant's time or leaves every participant on the
wall clock, never a mix: once time is set, a participant whose time was set and one
on the wall clock disagree, and the exchanges between them fail. A shared stage
reaches an instant through one helper in either kind of run, so the stages stay
shared between them.

For example, a billing scenario run against the team's own services and a fake card
processor sets every service's time and the fake's to the end of a trial and steps
the renewal; run against the processor's hosted sandbox, it sets the sandbox's test
clock with the rest; run against a production-like sandbox with no test clock, its
renewal stage skips, naming the trial's end and the sandbox, while its sign-up
stages, which wait for nothing, run.

## A system test reaches services only through their interfaces

The process running a system test cannot import a service's internals. It uses typed
clients, explicit test controls, and the services' stage and event interfaces, the
same no-raw-calls discipline integration tests follow
([Integration tests](integration-tests.md)); an observability seam a system test
needs is designed as such an interface.

A command-line client a system test runs is controlled on the same principles as a
service: a mock layer the test programs overrides its outbound IO and its time.
Unlike a service's, that layer can be applied in the test's own process — the test
runs the shipped command through its entry point there and replaces the command's
own composition factories — so no test functionality ships with the client. The
test still reaches every service only through its interfaces, and reaches into the
client only through those factories, its existing composition seam.

## Locally verifiable and external-topology scenarios

System tests come in two kinds, each with its own coverage. A *locally verifiable*
scenario runs against the repository's own stack, with every external service
replaced by a double; it runs on every pipeline run and proves that the services
compose into working behaviour. An *external-topology* scenario needs services or
hosts the repository does not deploy, such as a hosted provider or a real machine; it
runs only where a deployment supplies them, and it is the only evidence for what they
bring.

An external-topology scenario that performs the work a locally verifiable scenario
performs — a purchase, say — minimally extends that scenario. It shares that
scenario's stages wherever their bodies agree and adds only the stages its external
parts require, so the path both kinds run is proven on every pipeline run and the
external run adds only what no local run can observe. One that performs no such
work extends nothing: it follows, by name, the scenarios whose state it reads on the
same stack. Setup or teardown that needs knowledge the repository lacks — funding an
account at a provider's sandbox, providing the hosts — is the deployment's, and no
scenario performs it. An absent target is a skip naming what is missing, and a stage
whose input the target does not name skips naming that field.

Evidence from an external-topology run is supplied by whoever deploys the topology.
The scenarios assert, and log the identifiers each stage reads; the deployment's
operator presents the outcome as a free-form summary it has sanitized. Raw logs and
records stay in the operator's own storage and never enter the repository.

## An observation is made, failed, or unproven

Where a scenario exists to make named observations, its outcome is per observation,
not per run, because a run that passes with a skipped stage has not run every check
an observation requires. An observation is *made* when every stage requiring it
passed, *failed* when one failed, and *unproven* when none failed and one skipped
naming a prerequisite, which the outcome names. A stage the run did not collect
counts as not run, so deselecting a stage cannot make an observation. An observation
is made only by the stages requiring it, never inferred from another observation.
