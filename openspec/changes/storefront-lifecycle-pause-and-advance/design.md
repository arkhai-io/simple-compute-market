# Design

## Context

Verified against the tree during the 2026-08-11 debugging session. Re-verify before
implementing.

### What the storefront starts, and through what seam

Five background loops, all scheduled through one helper —
`core_storefront.app_startup.start_storefront_background_task`, taking a named
`StorefrontBackgroundTask(name, task_factory, ...)`:

| Loop | Interval | What a cycle does |
|---|---|---|
| `negotiation_watchdog` | configured | Times out stale negotiation threads |
| `claims_engine` | 30s | Sweeps settlement claims: submit, detect collectable, collect |
| `fulfillment_resume` | 30s | Re-drives unfinished accepted escrows |
| `capacity_events_poller` | 1s | Tails each site's capacity-event feed, emits deltas, reconciles derived listings |
| `site_projection_poller` | ~5s | Refreshes the two projection caches |

The shared named seam is what makes one flag sufficient: pause belongs at the seam, not
copied into five loop bodies. The API-credits storefront starts its loops through the
same helper, so a core-owned implementation covers both without a second copy — and the
kit-composition goal wants this code core-owned anyway.

### What pause means today

`_GLOBALLY_PAUSED` is a module-level bool in `market_storefront.server`, set by
`POST /api/v1/admin/pause`, read only by `sync_negotiation`, which raises
`StorefrontPausedError` on a new negotiation. It is per storefront process; nothing about
it is site-scoped. The endpoint summary reads "Pause new negotiations globally", and the
response message says "New negotiations will receive 503".

### What provisioning already does

`pause_lease_watchdog` / `resume_lease_watchdog` toggle a flag the lease loop consults;
`force_check_leases` is documented as "bypasses the pause flag — always runs";
`fulfillment-convergence/run-cycle` runs one production cycle. Scenario stage 10a already
calls `pause_lease_watchdog()` before arming a teardown gate, so the convention is
established and the suite already uses it — on one service only.

## Claims-engine impact assessment (requested 2026-08-11)

The question was whether extending pause to the timer loops breaks a scenario that
currently depends on one running while the storefront is paused.

**No current scenario pauses the storefront at all.** The only pause-related call in the
VM suite is a teardown safety net (`ensure_storefront_resumed`) that clears a residual
pause if one is somehow set; its own docstring records that admin pause/resume moved to
the smoke suite. So no stage runs with the flag set, and widening the flag's effect
cannot change any current stage's behavior.

**No scenario asserts on claims-engine output.** Searching the scenarios for
`claim_submitted` / `claim_collectable` / `claim_collected` and for any `claims` stage
event returns nothing; the only occurrences of "claim" in the VM scenarios are prose
about *capacity* claims, an unrelated sense of the word.

**The engine is nonetheless live during the VM scenarios**, which is the part worth
recording. Run 31483777656 shows the VM storefront emitting `claim_submitted` at
10:51:30 and `claim_collectable` / `claim_collected` at 10:51:35 — so once scenarios
pause at setup, that sequence stops happening on its own. Nothing asserts it today, but a
future stage that wants to observe collection will need a manual-advance control for
`claims_engine`, and it should be added then rather than now.

The same reasoning applies to `fulfillment_resume` and `negotiation_watchdog`: no
scenario asserts on either, and both become steppable-on-demand work once a stage needs
them.

**Conclusion:** extending pause to all five loops is safe against the current suite. The
risk is not breakage but silence — a scenario that used to be carried by a background
sweep will now simply not advance, and will fail on the assertion after it rather than at
the pause. Scenario conversion should therefore be part of this change, not a follow-up.

## Decisions

### One flag, storefront-scoped, matching the existing pause

The pause flag stays per storefront process. Per-site pausing would introduce a scope the
existing control does not have, for no identified need, and two scopes named "pause"
would be worse than one blunt one. A storefront aggregating several sites pauses its
poller for all of them.

### Pause halts every loop rather than a named subset

"Paused" should mean the storefront makes no state change on its own. A definition that
covers negotiations but leaves five loops writing is surprising to an operator reading
the endpoint, and it is unusable for a scenario that wants to observe side effects in
order. Halting everything is also the simpler contract to document and to reason about at
a review.

### Pause is checked at the top of a cycle, never mid-cycle

**Stands, after a detour.** A cancellation-based mechanism briefly replaced this while
core was out of scope, and did not preserve the property — see "Pause holds the loops idle
behind a flag" below for why, and for the reversal.

Each loop consults the flag before doing work and skips to its next interval otherwise.
No task is cancelled, no cursor advances, no partial sweep is left behind. The capacity
poller's `last_applied` cursor and its truncated-page `continue` both depend on the loop
body running to completion once entered, so a mid-cycle interruption is the one thing
this must not do.

### Manual advance bypasses the pause, and there is one of them for now

**Superseded 2026-08-11** by "Advance calls the work the loop was calling, per loop":
every loop has an advance endpoint rather than only the capacity poller, because each
one's unit of work already exists as a callable and the cost is one route apiece. The
bypass property is unchanged — with the loops cancelled there is nothing to bypass.

`force_check_leases`'s documented contract — "bypasses the pause flag; always runs" — is
the right precedent: a manual cycle exists precisely to run while paused. One control is
added, for `capacity_events_poller`, because that is the loop the derived-listing
assertions race.

`site_projection_poller` already has its advance control in
`POST /api/v1/admin/capacity/projections/refresh`, which is why the projection assertions
are already deterministic and the listing ones are not. Recorded because the asymmetry is
the evidence for this whole change: the loop with a control produces stable assertions,
the loop without one produces a race.

The remaining three get controls when a scenario needs to step them. Adding five now
would be speculative surface on a lifecycle boundary.

### Scenarios pause once at setup and never resume mid-run

A scenario pauses in its readiness stage and advances explicitly thereafter. Pausing and
resuming around individual stages would reintroduce exactly the uncontrolled windows this
removes.

## Risks / Trade-offs

- **[A paused storefront looks healthy but does nothing]** → The system status surface
  reports each loop's state rather than a bare boolean, so an operator who paused and
  forgot has one place to see it, and a loop that died is distinguishable from one held
  idle.
- **[A stage forgets to advance and fails on a later assertion]** → Real, and the failure
  message will point at the assertion rather than the missing advance. Mitigated by
  pausing in one place (the readiness stage) and by naming the advance control after what
  it advances rather than after the endpoint it calls.
- **[Widening pause changes operator behavior]** → An operator who paused to stop taking
  negotiations now also stops background work. That is the intended meaning, but it is a
  behavior change on an existing endpoint and belongs in the endpoint description and the
  operator documentation, not only in a spec.
- **[Divergence between the two storefronts]** → API-credits starts its loops through the
  same seam; if the flag lives in the VM storefront's `server.py` rather than in core, the
  two will diverge. The flag moves to core with the seam.

## Decisions from the 2026-08-11 design review

### The pause lives in the VM storefront, not core, and not a new kit package

Recorded constraint (repository owner): core changes carry heavy review and this campaign
is bug-fixing. Kit was offered as an alternative home; there is no kit package this
belongs to — kit holds identity, config, policy, site, site-client, resource-pools,
fulfillment, and alkahest, none of which owns storefront background work — and creating
one is a larger architectural act than the change it would serve. So the pause flag and
the task handles stay in the VM storefront, beside the existing `_GLOBALLY_PAUSED`.

The consequence to accept: the API-credits storefront starts its loops through the same
core helper and does **not** get this behaviour. That is a deliberate, recorded asymmetry
rather than an oversight, and it resolves when storefront runtime moves to kit under
Goal 4.

### Pause holds the loops idle behind a flag each one consults per cycle

**Revised 2026-08-11**, replacing an earlier decision to cancel the loops' tasks. That
decision followed from a constraint that has since been lifted: with `core_storefront`
out of scope, a VM-local flag could not be seen by the two loop bodies that live there,
and cancellation was the only uniform mechanism left. Core is now in scope for a minimal
change, which makes the better mechanism available, so the earlier decision is replaced
rather than layered over — it was a workaround for a constraint, not a conclusion.

Each loop consults a pause predicate once per cycle, before any work. The two core loops
— `site_events_poller` and `ClaimsEngine.run` — take it as an optional keyword defaulting
to `None`, so every other caller including the API-credits storefront is unaffected; the
three VM-local loops read it directly.

Cancellation was the weaker mechanism on every axis that matters here. `Task.cancel()`
only *requests* cancellation: the coroutine observes it at whatever await it happens to be
sitting on, which may be part-way through a reconcile that has written some of its rows.
A flag checked before a cycle begins means every cycle either ran to completion or never
started, which is the property this change actually needs and which the earlier decision
claimed to preserve without doing so. Cancellation also discards loop-local state — the
capacity poller's feed position above all — forcing a resumed poller to re-converge from
the feed head, and it opens a window in which a restarted loop can overlap a predecessor
still unwinding. Holding a live task idle has none of these consequences: nothing is torn
down, nothing is interrupted, and resume is a flag flip rather than a restart.

The cost is that a paused loop is a live task doing nothing, which a reader might mistake
for a leak. The status surface answers that directly by reporting each loop as `paused`
rather than as `running`.

### Advance calls the work the loop was calling, per loop, and returns what that work returns

Recorded direction: an advance endpoint calls the underlying service operation the loop
was invoking and returns roughly what it already returned. Visibility comes from adding
read APIs for the state a scenario wants to inspect, not from enriching the advance
response — a bare 200 would still make the paradigm work.

Every loop turns out to already have that unit of work, which is why this is cheap:

| Loop | Underlying operation an advance endpoint calls |
|---|---|
| `claims_engine` | `ClaimsEngine.tick()` — `run()` is a thin loop over it |
| `fulfillment_resume` | `resume_incomplete_fulfillments_once(sqlite_client=...)` |
| `negotiation_watchdog` | `_watchdog_tick(sqlite_client)` |
| `site_projection_poller` | `ProjectionCache.poll_once()` — already exposed as `POST /api/v1/admin/capacity/projections/refresh` |
| `capacity_events_poller` | see below |

### The capacity-events advance calls the storefront's own full reconcile

This is the one loop whose work is inline in core's loop body, with no callable unit to
invoke. Three options were weighed.

**Rejected — reimplement the drain VM-locally.** Duplicating the cursor handling and the
backwards-head branch would be an alternate transition, which
`ARCHITECTURE.md`'s operator-control rule forbids.

**Rejected — extract a one-cycle function from `site_events_poller`.** Behaviour-preserving
and about fifteen lines, and it is what a green-field design would do; ruled out by the
no-core constraint above. Recorded so that whoever revisits this after the kit extraction
knows it is the tidier shape.

**Accepted — advance calls `_full_reconcile`**, the VM-supplied callback the poller itself
invokes at startup and after a ledger reset. It is production code, it is the storefront's
own listing-reconciliation reaction, and it is precisely the handler whose effect the
scenarios assert.

The trade-off to record: `_full_reconcile` runs both the close and the reopen passes
unconditionally, while the delta subscriber runs one or both depending on the delta kind.
So advance exercises a superset of the subscriber's reaction, not an identical path. For
the assertions this serves — does a listing close when capacity is held, does it reopen
when released — the superset is the stronger check. A scenario that specifically needs
per-kind routing is not expressible through this control, and would be the trigger for the
core extraction above.

### Pause status is observable per loop, and the smoke suite asserts it

The admin status surface reports each loop's state rather than a single boolean, read from
the task handles the storefront now holds. The smoke suite's existing pause test is
extended to confirm the loops actually stopped, so "paused" is verified rather than
asserted — the endpoint returning 200 has never proven the background work stopped, and
after this change that is the substantive half of what pause means.

## Superseded open questions

The four questions below were answered in the 2026-08-11 review; the decisions above
record the outcomes. Kept for the reasoning they contain.

## Open Questions

- **Does the flag move to `core_storefront` in this change, or stay VM-local with a
  core-side predicate injected?** Moving it is cleaner and is where the kit-composition
  goal is heading; injecting is smaller and avoids touching the API-credits storefront in
  a change about test methodology. The answer decides this change's blast radius.
- **What does the advance control return?** `force_check_leases` returns a summary of
  what it did. For the capacity poller the useful summary is how many events were drained
  and which deltas were emitted, since a scenario asserting "one advance, no reopen" wants
  to distinguish "nothing to do" from "did work and reopened nothing".
- **Should advance drain until caught up, or run exactly one iteration?** The poller has an
  explicit `continue` for truncated pages, so one iteration may leave work outstanding and
  a scenario would need to call twice without knowing it. Draining to the feed head is
  probably the right unit, and is what makes a single call deterministic.
- **Does the smoke suite's pause/resume test still hold?** It asserts pause returns 503 on
  new negotiations. That stays true, but the test's description of what pause means will
  need updating alongside the endpoint's.

---

## Post-merge defect review — run 31623897337 (2026-08-12)

Five failures, two causes in the run and a third the second one masked. This section
records the decisions taken with the repository owner before Section 9 onward was planned.

### Context: four of five loops never acknowledged their gate

`await_quiescence` waits on `_ACKED[name]`, and only `gate(name)` sets it. One loop —
`site_projection_poller` — calls `gate`. The other four read `is_paused()` directly, which
reads the flag without acknowledging: `negotiation_watchdog` and `fulfillment_resume`
inline, `claims_engine` and `capacity_events_poller` by passing `is_paused` as the
`paused` predicate into their `core_storefront` loop bodies. The compose log is
unambiguous — `set=['site_projection_poller']`, `gate calls so far:
{'site_projection_poller': 48}` — so the other four had never reached a gate in the
process's lifetime, the bounded wait always expired, and `loop_states()` correctly
reported `pausing` for all four.

`gate`'s own docstring states the invariant this violates: reading the flag and
acknowledging "must not be separately forgettable". They were separately forgettable
because `is_paused` remained importable. The mechanism was right; only one of five call
sites used it.

Nothing below the end-to-end level could catch this. `tests/unit/test_lifecycle_registry.py`
drives a synthetic loop whose comment reads "through `gate`, as every production loop
does" — which is the assertion that turned out to be false. It proves the mechanism and
never the wiring, the same shape as the defect task 4b.2 recorded for startup keywords.

### Decision: the unacknowledged read becomes unavailable

`is_paused` becomes module-private. After the four call sites move to `gate`, no
production consumer of the unacknowledged read remains, so keeping it exported preserves
only the ability to reintroduce this defect. The two `core_storefront` seams already
accept `paused: Callable[[], bool] | None`, so an acknowledging predicate satisfies them
and no core change is needed for this part.

**Alternative rejected — leave `is_paused` public and rely on review.** This defect
survived three closeout passes, one of which asserted "five gated loops". A convention a
closeout can assert falsely is weaker than an import that does not exist.

### Decision: loop names get one source of truth

Each loop name is currently a bare string in two places — the `StorefrontBackgroundTask`
in `startup.py` and the gate call in the loop body. A mismatch acknowledges a name nobody
waits on and leaves the registered name unacknowledged forever: the exact symptom just
diagnosed, with a different cause. Names become constants in `lifecycle`, and `gate`
records a warning when handed a name that was never registered.

### Decision: `running` must be earned, and `starting` is a distinct state

`loop_states()` returns `running` for any registered handle where `not handle.done()`.
Registration is `asyncio.create_task` inside the lifespan, so all five names appear before
any coroutine has executed a step. `running` therefore means "a task object exists", not
"this loop is cycling and will observe a pause" — and the scenario's own pre-pause check,
which asserts every loop is `running`, passed at 17:45:04 with the negotiation watchdog at
zero gate calls.

A fifth state, `starting`, means registered and never yet acknowledged a gate. This is
also the answer to "has this loop ever gated": it falls out of the state machine rather
than needing a parallel field, and it makes the failure just diagnosed a single status
read. The gate-call counter stays diagnostic logging only — an API consumer needs to know
whether a loop is live, not how many times it has cycled.

### Decision: readiness and liveness separate, and readiness gates the stack

The storefront answers `/health` as soon as its routes are mounted, and `/health` says
nothing about background work. Compose's healthcheck and both Kubernetes probes all point
at it, so "the stack is up" is true before any loop cycles — which is why a scenario could
pause a storefront whose loops had not started.

Three surfaces, three meanings:

| Surface | Meaning | Not-OK condition | Code |
|---|---|---|---|
| `/health` | liveness — is this process worth keeping | a loop has ended on its own | 503 |
| `/ready` | readiness — can this process be relied on | any loop still `starting`, or ended | 503, `status: "starting"` while starting |
| `/api/v1/system/status` | diagnosis | never fails; body carries `checks.loops` and the per-loop map | 200 |

A deliberately paused storefront stays ready. Pause is an operator-requested state, the
storefront still serves and still trades, and a readiness surface that failed on it would
mark every scenario's container unhealthy the moment it paused.

`exited` degrades liveness rather than readiness alone because no supervisor restarts a
dead loop today: a loop's task is created once and nothing observes its completion. Under
that arrangement pod replacement *is* the recovery mechanism, and liveness is how it is
requested. Two consequences are accepted deliberately: a loop that dies deterministically
at boot produces a crash loop, which is the visible failure the current silence replaces;
and if loop supervision is added later, `exited` should move to readiness-only. That is
recorded as the trigger rather than built now.

Loops can in fact die. `fulfillment_resume_loop` has no `try/except` around its sweep — the
per-escrow handler does, but a failure in `list_incomplete_primary_escrows` or client
construction escapes and ends the loop — and `capacity_events_poller_loop` ends if its
`gather` raises. Nothing logs either. Hardening both and logging task completion is part of
this section, so that `exited` stays genuinely exceptional and liveness stays a real signal.

**The suite stops waiting, and asserts instead.** With compose's healthcheck on `/ready`,
`docker compose up -d --wait` already gates the whole run on the loops being live. The
scenario's readiness stage then *asserts* all five are `running` rather than polling for
it — consistent with `TESTING.md`'s no-waiting rule, and a loud failure if the gate ever
regresses.

### Decision: the negotiation watchdog's pre-loop delay is restructured

`watchdog_loop` sleeps 15s before entering its loop, and its interval sleep sits at the top
of the body, so its first gate lands ~17s after boot. The suite's first pause landed 13s
after registration — inside that window, so even a correct acknowledgement would have been
~1s from flaking. The delay's stated purpose is not to misclassify threads created while
the clock settles, which is a constraint on the *sweep*, not on the gate. The loop is
entered immediately, gates every interval, and holds the sweep behind a not-before
deadline.

`ClaimsEngine.run` has the same sleep-before-gate ordering and costs one interval on every
pause. It is in `core_storefront`, which this change's proposal fenced off. The fence is
struck for this one ordering change: the fence existed to avoid widening a VM-local pause
into core, and moving a sleep to the end of a loop body carries none of that risk. Recorded
rather than done silently, because a scope fence removed without a reason is how the next
reader loses the reason it existed.

### Decision: truncation becomes visible to the caller, not only the operator

`list_stage_events` clamps `limit` to 500 silently. The controller separately rejects
`>500` with 422, which is what stage 09bb hit — so over HTTP the silent clamp is currently
unreachable, and every in-process caller still meets it. Raising the controller cap would
convert a loud 422 into a silent short read, which is the worse failure.

The cap stays at 500 and gains two things: a log line where the clamp happens, and a
`truncated` flag on the response. `count` alone cannot distinguish a complete page of 500
from a truncated one, which is the same diagnosis problem one layer up from the one being
fixed. Stage 09bb asks for the whole claims log; with the flag it can assert that it got it.

### Decision: the claims stage event carries the domain's settlement identity

Stage 09bb filters `data["escrow_uid"]`, which no claims-lifecycle event sets. The stage is
not stale — it has never executed. This change's own "Claims-engine impact assessment
(2026-08-11)" records that a search of the scenarios for `claim_submitted` returned
nothing; task 4.2c added the stage afterwards, and run 31623897337 is the first run to
reach it, where the 422 stopped it two lines before the filter.

The identity is present under another name. `claim_ref` *is* the escrow uid for
alkahest — `submit_claim` sets `claim_ref=escrow_uid`, and production already depends on
that equivalence where `_on_event` feeds `escrow_uid=fields.get("claim_ref")` into lease
truncation. What is missing is the column: `stage_events.escrow_uid` is populated only from
a field literally named `escrow_uid`, so every claims-lifecycle row has it NULL while
`lease_truncated_after_abandonment`, emitted by the same module, fills it. The claims stage
is inconsistent about its own identity column and the new stage tripped over it.

The translation happens at the domain seam. `claims_runtime._on_event` is the VM hook over
core's mechanism-neutral emitter and already performs exactly this translation one line
below; `submit_claim` does the same for the direct fulfillment-path emission. Core keeps
emitting `claim_ref` and learns no alkahest vocabulary.

**Alternatives rejected.** Filtering the test on `claim_ref` fixes the symptom and leaves
the column NULL for the whole claims lifecycle, so the next reader meets the same
inconsistency. Emitting both names from `ClaimsEngine` puts mechanism vocabulary in a core
carrier.

### Scope judgement

Sections 9 through 11 are this change's own contract: its spec delta already requires per-
loop state that "only the loop itself can establish by reaching its gate", and the code
does not hold that. Section 13 is this change's own stage 09bb. Section 12 is a storefront
API defect this change found rather than caused; it is absorbed here on the same basis the
convergence-backoff fix already was, and the alternative — a separate change for a log line
and a boolean — was judged more process than the defect is worth. Section 10's readiness
surface is the largest judgement call: it is new operator-facing behaviour with helm and
compose impact, and it is here because the pause contract is not achievable without it, not
because it is adjacent.

### Two "environmental" failures that were not

Recorded because the error was in the reasoning, not the code, and the same reasoning will
be available next time.

Three integration tests failed on an unmodified baseline during this work and were first
reported as environmental. All three were the session's own dependency set:

`test_amountless_exact_escrow_can_start_and_accept` failed because an unpinned `dynaconf`
resolved to 3.3.5 where the lockfile pins 3.2.13. `settings.set` on a list merges in the
newer version and replaces in the older, so a test helper overriding `negotiation.policies`
appended to the configured chain rather than replacing it and left `bisection` ahead of
`accept_exact_listing`. The symptom — a counter where an accept was expected — looks exactly
like a policy defect. `pyproject.toml` bounds dynaconf only as `>=3.0.0`, so this is
reachable by any resolution that does not go through the lockfile.

`test_alkahest.py::test_rust` and `::test_python` need an `anvil` binary. It is not on PyPI,
which is where the search stopped; it is a Foundry release asset on GitHub, a host already
reachable, and fetching it turns both green in seconds. The tests' own failure message names
the repository's host bootstrap script, which is the correct instruction for a developer
machine and was misread as a statement that the runtime could not be obtained here. That
exclusion had been carried in this change's task 6.1 since an earlier session; it is amended
there rather than quietly dropped.

The generalisable part: "fails identically on the baseline" establishes only that a change
did not cause a failure. It says nothing about whether the failure is a defect, and treating
the two as the same claim is what let a wrong dependency version sit unexamined. It also cut
both ways here — the newer dynaconf *masked* a defect in this change's own new test, which
set an absent settings key and relied on 3.3.5 tolerating its deletion at teardown.

---

## Task 2.8 diagnosed, and three findings alongside it (2026-08-12)

### 2.8 was never about the reconcile

Three attempts read the failure as a data-shape problem — which availability keys the
view produces, whether a resource counts as exhausted — and the task's own note passed
that reading forward. It is wrong. Asked directly, with the fake site's ledger holding two
of four GPUs, the reconciler answers correctly:

```
availability: {(None,'pool-h200-1'): 2, ('default','pool-h200-1'): 2}
stale:        ['listing-3x', 'listing-4x']
```

The precondition is seed-and-reserve, and `test_admin_reserve_capacity_closes_oversized_listings`
in the same file already establishes it with the same two helpers.

The cause is that the route reconciles a different database. `full_capacity_reconcile`
resolves its path from the module singleton — `get_sqlite_client().db_path`, which is
`settings.db_path` — while the integration fixture seeds a `tmp_path` database and wires it
into the container. So the reconcile ran, correctly, against an empty database and found
nothing. `close_order` compounds it: it takes `db_path` for the query and mutates through
`get_sqlite_client()` for the write.

This was already known and written down, in a neighbouring test that works around it:

> That global singleton defaults to settings.db_path, not this test's own db fixture, so it
> must be patched here or the fallback check silently finds nothing.

That test patches `publication_service.get_sqlite_client`. Nobody connected the note to
2.8's three failures, and the patch is the mocked-internals shape `TESTING.md` forbids —
so the one test that could see the problem was also the one hiding it.

### Decision: inject the unit of work, minimally

The reconcile path takes its sqlite client as a parameter, defaulted to today's resolution
so no caller changes behaviour; the admin route passes the container's client and the poller
passes the one it already builds. This is the injected-dependency seam `AGENTS.md` prefers
over patching a global, and it is what makes the transition observable at all.

Deliberately narrow. Several changes are already slated against the storefront persistence
layer, so this adds a parameter to the functions 2.8 needs and does not attempt to retire
the singleton, rework how the container resolves a unit of work, or touch the other call
sites of `get_sqlite_client`. The trap is recorded where the next reader of that layer will
meet it.

**Alternative rejected — point the singleton at the temp database from the fixture.** Two
lines, and it unblocks 2.8 today. It also pins a production global from a test and leaves
the next caller of `full_capacity_reconcile` to rediscover the same thing, which is what
happened here three times.

### Decision: cover both reconcile passes, not one

`full_capacity_reconcile` runs a close pass and a reopen pass, and the advance route's own
docstring already records that it runs both unconditionally where the delta subscriber runs
one or both by delta kind. The requirement 2.8 serves is that a control does not diverge
from its loop. A single close assertion leaves half of what this control does unasserted,
and the reopen half is where the divergence would be least obvious — a scenario advancing
after a release is exactly the case the storefront's own timer path handles by delta kind.
Reserve-advance-observe-close and release-advance-observe-reopen are one setup and two
assertions.

### The ambient-database write, recorded rather than fixed

Until the injection lands, exercising this route from a test mutates the checked-out
storefront database at `settings.db_path` — the developer's own `agent.db` — rather than a
temporary one. It is gitignored, so nothing reaches version control, but a suite that writes
to shared ambient state can contaminate a later run on the same checkout. The injection
removes it for this path; other `get_sqlite_client()` writers are out of scope here and the
hazard is stated for whoever takes the persistence layer next.

### Dependency bounds: one fixed, one larger than it looked

`dynaconf` is declared `>=3.0.0` in four distributions and `>=3.2` in a fifth. Between 3.2
and 3.3, `settings.set` on a list key changed from replacing to merging, which silently turns
a test's policy-chain override into an append and makes a negotiation test fail as though the
policy were wrong. The demonstrated breakage is in test helpers rather than production
config layering, so the bound is about keeping the suite meaningful; that is still worth
holding, and stating the reason is what lets someone lift it deliberately.

The `[rl]` extra's torch resolution — which breaks `make reinit` for every developer, not
just one host — is **not** the small fix it was characterised as, and the characterisation is
withdrawn rather than acted on. Two candidate fixes were tried and each moved the failure
rather than removing it: narrowing the darwin environment to `python_full_version < '3.13'`
still fails because the `pytorch-cpu` index carries no darwin wheels at all, and scoping the
index to `sys_platform == 'linux'` then fails on linux/x86_64/3.13 with only `torch<2.7.0`
visible. Why the CPU index is pinned at all, and whether the `rl` extra should participate in
the default resolution, are questions for whoever owns that dependency. Recorded with the
evidence so a third attempt starts further along.
