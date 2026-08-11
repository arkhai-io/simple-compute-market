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

**Superseded 2026-08-11** by "Pause stops the loops by cancelling their tasks": two loop
bodies are in core and cannot consult a VM-local flag, so cancellation replaces
flag-checking. The property this entry was protecting — no partial sweep, no half-advanced
cursor — is preserved differently and is recorded there.

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
  already reports `paused`; it should report which loops are halted rather than a bare
  boolean, so an operator who paused and forgot has one place to see it.
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

### Pause stops the loops by cancelling their tasks; resume restarts them

Two of the five loop bodies live in core — the claims engine's `run()` and the capacity
poller's `site_events_poller` — so a VM-local flag cannot be consulted inside them. The
uniform VM-local mechanism that needs no core change is to hold the task handles the
startup helper already returns and cancel them on pause, restarting on resume.

Uniform beats mixed: flag-checking the three VM-local loops and cancelling the two core
ones would implement one concept two ways, and a reader would have to know which loop is
which to predict pause's behaviour.

One consequence is real and belongs in the spec rather than a comment: the capacity
poller's `last_applied` cursor is loop-local, so cancelling loses it, and a restart
re-positions at the feed head and re-runs its full reconcile. That is self-healing by
design — it is the same path the poller takes after a restart or a ledger reset — but it
means resume performs a reconciliation, so a scenario resumes at teardown, never
mid-assertion.

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
