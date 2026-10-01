# Design — kit-owned storefront loop lifecycle

## Context

- **VM's lifecycle module is the one working implementation.** It holds loops by a
  flag each loop reads once per cycle rather than by cancelling tasks, so every cycle
  either ran completely or never started and loop-local state survives a pause. Each
  loop acknowledges the flag in the same call that reads it (`gate`), so a status
  report can distinguish a loop that has stopped from one that was merely asked to.
  Pausing waits, bounded at 5 seconds, for every live loop to reach its gate, and
  reports per loop `starting`, `running`, `pausing`, `paused`, `exited`, or
  `cancelled`. Fan-out loops whose tasks it does not own — the per-site capacity
  pollers inside `kit/capacity-publication` — are declared by name so the pause still
  waits for them. Idle loops wait on the pause signal as well as their interval.
- **It is module-global, and partly circular.** Registration, acknowledgements, and
  gate-call counts are module dictionaries; the pause flag lives in `server.py` and is
  read through a function-local import that exists only to break an import cycle.
- **VM's routes call the operation the timer calls.** Each `run-cycle` route invokes
  the loop's own work and returns its result, per `ARCHITECTURE.md`'s operator
  lifecycle rule. The route names map to registered loop names through
  `ADVANCE_LOOP_NAMES`; the negotiation watchdog is held but has no step.
- **Bare metal and API credits have no pause.** Both start a negotiation watchdog and a
  settlement-servicing worker with no predicate; API credits also starts a quota
  capacity-event poller. Bare metal steps only publication, which has no timer.
- **The shared runners already take a pause predicate.**
  `market_storefront_kit.run_negotiation_watchdog(..., paused=...)`,
  `market_settlement_runtime` servicing `run(paused=...)`, and
  `market_capacity_publication` `poll_events(paused=<per-site gate factory>)` each
  accept one. Bare metal and API credits simply pass none.
- **Two runners gate in the wrong place.** The watchdog and servicing worker read the
  predicate, sleep their interval, then work. The predicate is never read between the
  sleep and the work.
- **A dangling citation.** VM's module points at a `storefront-publication`
  requirement that a loop's reported state is established by the loop. No such
  requirement exists in any specification.

## Goals / Non-Goals

**Goals.** One loop lifecycle implementation, composed by every storefront. Every
timer loop a storefront runs is holdable and steppable. A pause is observed before any
work, whatever the loop's interval.

**Non-Goals.** No change to trading pause, loop timings, or cycle work. No extraction
of routes, assembly, or health.

## Decisions

### Carve the loop lifecycle out of the shell change

`kit-owned-storefront-shell` names the timer-loop lifecycle as one of four things it
extracts. The other three — the route set over core models, executable assembly, and
the health and system service — are large, interdependent, and still at the
design-question stage. The loop lifecycle depends on none of them: it is a registry,
a flag, and four routes.

Two changes need it now, and each would otherwise add a bare-metal copy for the shell
change to delete. Carving it out removes that churn and gives the extraction a small
acceptance boundary of its own: VM loop-control parity, and bare metal and API credits
holding and stepping their existing loops.

### The controller lives in `kit/storefront` and is instance-scoped

The loop lifecycle is storefront runtime that differs between domains only in which
loops are registered and what their steps call, which is the definition of
`market-composition`'s "Cross-cutting storefront runtime is kit-owned". `kit/storefront`
is where the shell change places it, and every storefront already depends on that
package, so its Alkahest dependency — the reason introduction glue does not live
there — costs nothing here.

The controller is an object, not module state. One storefront process holds exactly
one. That is what a compute-family storefront serving several domain contributions
will need, since all their loops must answer to one pause; it also removes the import
cycle VM works around, and lets tests construct a fresh controller rather than reset
globals.

### Adopt VM's semantics unchanged

Every property in the Context above transfers as is: flag-at-cycle-boundary rather
than cancellation, acknowledgement folded into the gate read, bounded quiescence,
per-loop state derived from what the loop has done, declared gated names, and idle
that wakes on pause. Each was added in response to a trap a scenario actually hit,
and `TESTING.md` records the traps. There is no second implementation to reconcile:
bare metal and API credits have no pause, so the extraction records no drift beyond
the missing watchdog step.

### A registration binds a loop to its step

A loop registers with its name, a factory that starts its body given a gate and a
wait, the step that runs one cycle, and optionally a read-only preview. Binding the
step at registration rather than in a route table is what keeps the step and the timer
calling the same operation: there is one place that says what a cycle of this loop
is. VM's `ADVANCE_LOOP_NAMES` mapping becomes the route-name form of the registered
names rather than a second table.

Steps are registered when their storefront's composition is built — at import of
VM's steps module, at bare metal's runtime construction, and at API credits'
lifespan start — not when startup starts the loops, so the routes answer the same
whether or not startup has run. A step resolves its collaborators when it runs.
A step for a loop the storefront does not compose is not registered: bare metal
registers settlement servicing only when a settlement worker is composed, so an
uncomposed loop is not found rather than unavailable.

A loop with no timer — bare-metal publication — registers a step and no body. It is
reachable by `run-cycle` and is never reported as held, because there is nothing to
hold; `TESTING.md` already says so for that loop.

Every loop gets a step. The negotiation watchdog's is `sweep_stale_negotiations`, the
operation its timer already calls.

### Loops gate on entry, work when due, then wait

A loop body's cycle is: read the gate, and while it reports held, re-read it on a
short poll; do the work if it is due; then wait out the interval through the
controller's wait, which returns early on a pause request. The gate read that
releases the loop is the last thing before its work, so a pause requested at any
point during the interval is observed before the next cycle's work, and the pause
route's 5-second bound holds regardless of interval. While held, the loop polls its
gate rather than calling the wait again, because the wait returns at once while a
pause is requested and would otherwise spin. This is the shape VM's own loops
already have.

The gate is also read on entry, before the first interval. A loop that waited
before its first gate would be reported `starting` — unable to observe a pause —
for a whole interval, and the first pause of an end-to-end run lands inside that
window; the watchdog's own history records exactly that trap. Ordering the cycle
as "wait, then gate, then work" was considered while designing and rejected when
implementing for this reason.

The watchdog and servicing worker previously gated, slept their interval, then
worked without reading the gate again, so a pause requested during the sleep still
let one full cycle run. Both now follow the shape above and take the injected wait.
Neither works earlier than it did: each holds its first sweep back with a deadline
one interval after start — the watchdog's existing initial-delay deadline, extended
to at least one interval. A sweep that raises still waits its interval, since the
wait sits outside the work's error handler. Without an injected wait both fall back
to a plain sleep.

### Every timer loop waits through the controller

A pause reaches a loop between cycles only if the loop's wait returns on the pause
request, so every registered or declared loop waits through the controller's `idle`
or a wait injected from it. The plan assumed VM's own loops already did; only
publication did, and review found three that waited with a plain sleep —
fulfillment resume, the site-projection poller, and the kit's per-site
capacity-event poller — so a pause landing in a 30-second fulfillment interval
outlasted the 5-second quiescence bound. All of them now wait through the
controller:

| Storefront | Loop | Wait |
|---|---|---|
| VM | negotiation watchdog, settlement servicing | injected `idle` |
| VM | fulfillment resume, site-projection poller, publication | `idle` |
| VM, API credits | capacity-event aggregate and each site poller | injected `idle`, through `run_capacity_event_pollers` |
| Bare metal, API credits | negotiation watchdog, settlement servicing | injected `idle` |
| Bare metal | publication | no timer |

The kit runners — the watchdog, the servicing worker, the site poller, and the
capacity aggregate — refuse a gate without a wait, because gated but
uninterruptible is exactly the combination that defeats the bound. A kit-owned
periodic runner that owns the whole gate-work-wait cycle would enforce this
structurally; it cannot serve the runners in the settlement-runtime and
capacity-publication kits, which sit below `kit/storefront`, so it is left to
`kit-owned-storefront-shell`, which owns loop registration in the composition root.

### Loop tests are coordinated by events

`docs/development/TESTING.md` forbids coordinating background-loop tests through
sleeps. Every test this change adds or touches drives its loops through a wait the
test controls — returning only when ticked or paused — and synchronizes on events
set by the work, the gate, or the controller's own acknowledgement. The regression
guard for the bound runs each storefront's real loop bodies with an hour-long
interval and requires `paused` within a second; with the plain sleep restored in
fulfillment resume, its cases fail.

### API-credit lifecycle routes are covered at component level

The API-credit storefront has no production-application test at all: every test
builds its own application or stubs the lifespan, and its startup needs the credits
service and a capacity authority. Its lifecycle-route test is therefore a component
test and lives in `tests/unit`. Production-application coverage, and a lane of its
own rather than a seat in the VM lane, belong to `apicredits-end-to-end-lane`.

### A framework-free route service, bound by each storefront

The controller is exposed through a route service with no web-framework dependency —
pause, resume, run-cycle, and dry-run by route name — returning plain mappings and
raising an HTTP-shaped error for an unknown loop or a loop without a preview. Each
storefront binds it into its own router behind its own administrator authentication.
That is the precedent `kit/pool-overrides` set, and it keeps authentication with the
storefront until `kit-owned-storefront-auth-and-persistence` decides otherwise.

The wire contract does not change: the same paths, the same response shapes VM serves
today, and the canonical `StorefrontClient`'s existing lifecycle methods.

### VM migrates by binding, not by rewriting call sites

VM's `lifecycle` module becomes a binding of one controller instance: the names its
call sites import — loop-name constants, `gate`, `loop_gate`, `idle`,
`declare_and_gate`, `start_registered_loop`, `capacity_site_loop_name`, and the
state and summary functions — remain importable from the same module and delegate.
The loop-pause flag moves from `server.py` into the controller, which removes the
function-local import. Tests that assert on VM's private registry dictionaries move to
kit, where the registry now lives; tests that drive VM's loops and routes stay in VM
and run unchanged.

The module's citation of a non-existent requirement is replaced by the
`market-composition` requirement this change adds.

### API credits gains controls by composition

`market-composition`'s "An extracted concern leaves no domain-local implementation"
requires a domain that lacked an extracted concern to gain it by composition in the
same change. API credits runs three timer loops and offers no pause, so it registers
all three and serves the routes.

Its capacity-event poller needs what VM's already has: per-site gates declared to the
controller, and an aggregate loop that holds the fan-out task, gates on its own name,
and surfaces the fan-out's failure. VM implements that aggregate locally around the
capacity-publication kit's `poll_events`. Rather than copy it into API credits, it
moves into `kit/capacity-publication` as `run_capacity_event_pollers`, a function
taking a runtime's bound `poll_events`, the aggregate gate, the per-site gate
factory, and the gate cadence, so it needs no dependency on `kit/storefront` and is
testable without a configured runtime. Both storefronts call it.

API credits authenticates administrator routes with the route's name as the signed
operation and the request path as the resource. The canonical client signs lifecycle
calls as `admin_pause_lifecycle_loops`, `admin_resume_lifecycle_loops`,
`admin_run_lifecycle_cycle`, and `admin_dry_run_lifecycle_cycle`, over the resource
`lifecycle` or the loop's route name, as VM and bare metal verify them. API credits'
lifecycle routes therefore authenticate with those names, so one client drives all
three storefronts.

### Loop state is reported, not yet read by health

VM's lifecycle module computes which loops are starting and which have ended, and its
comments say the health surfaces gate readiness and liveness on them. None does: no VM
health or status route reads loop state. The controller keeps both summaries, and the
comments stop claiming a wiring that does not exist. Making health read them belongs
to the health extraction in `kit-owned-storefront-shell`, which owns the health
service all three storefronts will share.

### The loop pause is process-local

VM's loop pause is not persisted, and this change keeps that. A restart resumes every
loop, which is the safe direction: a storefront that came back up silently idle would
stop servicing settlements with nothing to say so. A scenario that restarts a
storefront pauses again afterwards. The trading pause, which is persisted, is
unaffected.

## Risks / Trade-offs

- **[VM regresses through the migration]** → The binding preserves every imported
  name, and VM's loop and route suites run unchanged against it. The suites that move
  to kit are those asserting on registry internals.
- **[Reordering the runners changes first-cycle timing]** → It does not: each runner
  still gates on entry, and its first sweep is still held back one interval by a
  deadline, so neither works earlier or later than it did.
- **[A loop is composed with a gate but no interruptible wait]** → Every runner that
  takes a gate refuses to run without a wait, and each storefront's wiring tests
  drive its real loop bodies with an hour-long interval and require them to be
  reported `paused` within a second.
- **[A storefront forgets to register a loop]** → A loop started outside the
  controller cannot be held. Each storefront's integration suite asserts the
  registered loop names against the loops its startup creates.
- **[The shell change later moves the binding]** → Expected. It composes this
  controller; it does not replace it.

## Open questions

None.

## Migration Plan

1. Add the controller, the route service, and their kit tests.
2. Reorder the shared runners behind an injected wait.
3. Bind VM to the controller; its existing suites pass unchanged.
4. Compose bare metal and API credits.

No persisted state changes, so rollback is a code rollback.
