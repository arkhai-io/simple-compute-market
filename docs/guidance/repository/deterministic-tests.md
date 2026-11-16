---
tags: [repository, testing]
---

# Deterministic tests

How this repository's tests stay deterministic: the seams they synchronize on, the
holds every compute-lane scenario takes, and the traps the loops have sprung, as
instances of [`test-determinism.md`](../engineering/test-determinism.md),
[`test-seams.md`](../engineering/test-seams.md), and
[`concurrency-tests.md`](../engineering/concurrency-tests.md).

## No sleeps

**Async test discipline — no sleeps**
([`test-determinism.md`](../engineering/test-determinism.md#no-sleeps)):
`AsyncJobQueue.__init__`'s `on_job_started: Optional[Callable[[str], None]]`,
`None` in production and zero-cost there, is the seam a test of the job queue
synchronizes on.

## Tests wait on events, never on durations

**Tests wait on events, never on durations**
([`test-determinism.md`](../engineering/test-determinism.md#tests-wait-on-events-never-on-durations)).
The storefronts' loopback uvicorn servers, which a test cannot replace with an
in-process transport, stop on an event rather than at uvicorn's poll.

## Leave nothing held

**Leave nothing held**
([`test-determinism.md`](../engineering/test-determinism.md#leave-nothing-held)):
a test that holds a job at a mock rule's gate (`pause_before_result`) ends that
hold by resuming the rule or by cancelling the job, then waits on the execution —
`MockRuleSet.wait_until_released` for the gate and `AsyncJobQueue.wait_until_idle`
for the processing — and asserts the rule's `waiting` count is zero.

## Pause the loop, then advance it explicitly

**Pause the loop, then advance it explicitly**
([`test-seams.md`](../engineering/test-seams.md#pause-the-loop-then-advance-it-explicitly)).
Here the seam is an HTTP control. The stage discipline
diagram under
[`deal-scenarios.md`, "The discipline every scenario follows"](deal-scenarios.md#the-discipline-every-scenario-follows)
draws a scenario following this:

| Loop | Pause | Explicit step |
|---|---|---|
| Lease watchdog | `POST /api/v1/system/lease-watchdog/pause`, answering `paused` and `at_gate` (`WorkerPauseResponse`) | `POST /api/v1/system/check-leases` |
| Fulfillment convergence | `POST /api/v1/system/fulfillment-convergence/pause`, answering `paused` and `at_gate` (`WorkerPauseResponse`) | `POST /api/v1/system/fulfillment-convergence/advance-cycle` |
| VM storefront loops (`publication`, `capacity-events`, `site-projections`, `deal-servicing`, `delivery-recovery`, `payment-reconciliation`, `settlement-servicing`, `negotiation-watchdog`, `introduction-retention` while contact exchange is enabled, and `alkahest-chain-probe` while an Alkahest section is configured) | `POST /api/v1/admin/lifecycle/pause`, which holds them all | `POST /api/v1/admin/lifecycle/<loop>/run-cycle`, previewed by `.../<loop>/dry-run` for `publication`, `capacity-events`, and `introduction-retention` |
| Bare-metal storefront loops (`publication`, `site-projections`, `deal-servicing`, `delivery-recovery`, `payment-reconciliation`, `settlement-servicing`, `negotiation-watchdog`, `introduction-retention` while contact exchange is enabled, and `alkahest-chain-probe` while Alkahest is composed) | `POST /api/v1/admin/lifecycle/pause`, which holds them all | `POST /api/v1/admin/lifecycle/<loop>/run-cycle`, previewed by `.../<loop>/dry-run` for `publication` and `introduction-retention`; the `bare-metal-storefront publish` command is a client of the `publication` step and its preview |
| API-credit storefront loops (`capacity-events`, `settlement-servicing`, `negotiation-watchdog`, `payment-reconciliation` while Arkhai payments is composed, `alkahest-chain-probe` while Alkahest is composed, and `listing-seed` while a seed listing is configured) | `POST /api/v1/admin/lifecycle/pause`, which holds them all | `POST /api/v1/admin/lifecycle/<loop>/run-cycle`, previewed by `.../capacity-events/dry-run` |

A provisioning worker's pause answers `at_gate` beside `paused`: a cycle that
began before the pause finishes first, so a caller that needs the worker held
repeats the pause until `at_gate` is true. A storefront's pause answers each
loop's gate state the same way. `alkahest-chain-probe` probes every configured
chain at each step, and settlement readiness reads only its last results, so a
held storefront judges Alkahest by the probe a stage last stepped.
`listing-seed` finishes once the configured seed listing exists and waits while
a dependency it needs cannot be reached.

Every storefront composes its loops onto the one kit loop controller in
`kit/storefront`, so the routes, response shapes, and the canonical
`StorefrontClient` methods are the same for every storefront. The storefront
loops hold no claim between cycles, so their `run-cycle` is a step: it runs
exactly the cycle the timer runs, through the same locked operation, whether or
not the loops are held, and records its outcome as the timer's cycle does.

A storefront whose source checks read held projections confirms a listing only
from a generation polled within its `[capacity].source_confirmation_seconds`. A
scenario that holds the loops keeps trading, so it steps `site-projections`
wherever a site changed before stepping publication or negotiating, and the
end-to-end lanes widen the window to an hour so a scenario's rounds are not
refused between steps.

Every scenario module a compute pipeline lane selects holds its lane's timers for the
whole module: the storefront's lifecycle loops, provisioning's fulfillment convergence,
and its lease watchdog, and in the VM lane also Alice's storefront loops, since her
publication cycle writes to registries other modules read. Holding every timer the
lane's stages can meet, rather than those an author judges a module depends on, is
what keeps a loop no one thought of from racing an observation. The module takes the
lane's hold fixtures with `usefixtures`, listed first so they are released last. A hold
is taken before the module's first stage and waits until each loop is at its gate, and
is released in a finaliser whatever the module's outcome. Stages assert a hold; they
never pause or resume a service themselves, and a source check enforces it. Two kinds
of module are outside the rule: one no lane selects, such as the real-host modules an
operator runs by hand, keeps the holds it has; and one under `scenarios/core/` reaches
only the dev chain and messages no storefront or provisioning service, so it takes
none.

With convergence held, a stage makes each transition convergence would make. A buy
scenario runs `market buy` in the background through `buy_to_ready`
(`e2e-tests/tests/e2e/roles/helpers/buy.py`): it waits for the buy's escrow and
settlement events and the storefront's dispatch, drains the mock job queue, advances
convergence to `active`, and waits for the buy to end `ready`. A foreground buy would
block on a convergence cycle no one steps. On any failure the helper terminates and
reaps the buy it started, so a failed stage leaves no buyer polling the stack.

The hold helpers are `storefront_loops_held`, `fulfillment_convergence_held`, and
`lease_watchdog_held` in `e2e-tests/tests/e2e/roles/helpers/compute_deal.py`; each
compute lane's `conftest.py` builds its fixtures of the same names on them, and the VM
lane adds `alice_loops_held` for Alice's storefront. A stage reads a hold back through
live system status (`assert_storefront_loops_held`, `assert_lease_watchdog_held`), so a
module that lost its hold fails rather than racing a timer. A lane's cleanup fixtures
are not autouse: pytest sets an autouse fixture up first and so finalises it after the
holds, so each module lists its cleanup after its holds, and the holds keep the timers
stopped while the cleanup runs. `e2e-tests/tests/unit/test_scenario_holds.py` refuses,
from source, any pause or resume call or route outside the hold helpers and the
conftests' hold fixtures, and `e2e-tests/tests/unit/test_scenario_cleanup_order.py`
reads the fixture order pytest resolves for every compute-lane scenario module and
refuses a hold released before the module's other cleanup.
`e2e-tests/tests/unit/test_scenario_lane_holds.py` reads each compute lane's marker
expression from `e2e-tests/Makefile`, where lane membership is written once, collects
the setup plan pytest resolves for it as the lane's own run collects, with skip marks
unevaluated so a module skipped where the check runs is still held to the rule, and
refuses a module missing one of its lane's holds, naming the module and the hold. A
module joining a lane, from any directory, comes under the rule with no second list to
update. A module killed by `helm
test`'s timeout runs no finaliser, and only a restart clears its pause; modules in a
lane run serially.

The traps [`test-seams.md`](../engineering/test-seams.md#pause-the-loop-then-advance-it-explicitly)
lists have each sprung here:

- **A loop with no pause.** Convergence ran a 30s timer with no gate while the
  scenario around it believed everything was stopped, so it claimed the same rows
  the test was explicitly advancing.
- **A "run one cycle" endpoint that is not a step.** Convergence claims a row
  before polling its provider and, on a pending answer, keeps that claim so the
  lease spaces the next poll. `advance-cycle` releases the caller's own claims
  first; `run-cycle` is the production cycle and does not.
- **A loop that sleeps its interval.** A pause landing in a 30-second interval
  outlasted the pause's 5-second bounded wait and reported the loop `pausing`.
  Every timer loop waits through the controller's `idle`, which returns on a pause
  request, and the kit runners refuse a gate without such a wait. The one kind of
  loop whose task gates itself is a fan-out — the per-site capacity-event pollers —
  whose children read their gates under each site's cursor lock. Test it with the
  real loop body and an interval far longer than the test waits. A test that needs
  a self-gating body runs it as a fan-out with no children.

## Database concurrency

Database-concurrency tests follow [`concurrency-tests.md`](../engineering/concurrency-tests.md).
