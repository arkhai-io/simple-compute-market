# Tasks

## Status: discuss phase only — no implementation tasks yet

The defect is reproduced and its mechanism is traced (see `proposal.md`). What is not
settled is where the freshness constraint belongs, and that decides the plan:

1. Does the storefront already record a latest-observed capacity version per site that
   the reopen pass can compare against, or does this change add one?
2. Should a reopen pass that finds itself behind skip, or re-read availability and
   proceed? Skipping is simpler and converges on the next delta; re-reading closes the
   window sooner at the cost of a synchronous fetch inside a subscriber.
3. Does the same reasoning apply to the bare-metal storefront's reconciliation, or is
   that path structured differently enough to need its own answer?
4. Is a freshness gate on the reopen sufficient, or must the subscriber's reconciliation
   and an inline reserve's close be serialized? The second occurrence shows an inline
   close reported and then not observed, which a freshness gate alone would not explain.

Once those are resolved, this file gets a real plan, ending with the closeout task
defined in `openspec/README.md#plan-closeout-requirements`.

## Diagnostic result (run 31608431467, 2026-08-12)

The instrument this change was waiting for now exists, and has been used.

With the storefront's timer loops held idle and reconciliation advanced deliberately, the
flap **does not reproduce**: zero `compute_listings_reopened` events across a full green
end-to-end run, against a reopen observed in three separate runs while the poller was
running. In two of those the reopen was triggered by a delta belonging to a *different*
resource, and in one by a registration rather than a release.

That narrows the change rather than closing it. The reopen requires the timer path, which
is what a stale-view defect predicts — a reconciliation acting on an availability view older
than a reservation it has not yet observed. It does not show the reopen decision is correct:
an advance-driven reconcile reads a current view, so it would not exhibit a stale-view defect
even if one is present. Open question 4 — whether a freshness gate suffices or the subscriber
and an inline close must be serialized — is still open, and the evidence for it is unchanged.

What this does settle is how to reproduce it under control: hold the loops, take a
reservation, and drive a reconciliation whose availability view is deliberately older than
that reservation. That is a unit- or integration-level construction now that the seams exist,
and it does not need an end-to-end run.

## Third occurrence — end-to-end run 31636711115 (2026-08-12)

Recorded because it corrects the conclusion drawn from run 31608431467, which
`archive/2026-08-13-storefront-lifecycle-pause-and-advance` task 6.3 reported as "does not
reproduce with the
loops idle". It reproduces. Holding the loops moved it, it did not remove it.

```
20:18:56.888  compute_listings_reopened      compute-e2e-buy-001  capacity_version 1
20:18:56.993  stale_compute_listings_closed  compute-e2e-buy-001  capacity_version 2
```

One listing, reopened and re-closed inside 105 ms — the same shape as the two occurrences
in the proposal, and again with the reopen on the wrong side of it.

What is new is *where* it sits. Both events follow a scenario module's teardown
`POST /api/v1/admin/lifecycle/resume` by a few hundred milliseconds. The capacity poller
leaves its gate, reads the event feed from `after=0`, runs its convergence reconcile — which
reopens a listing the deal path had already closed — and then re-closes it on the next
capacity version it drains. Every scenario assertion has finished by then, so the run is
green and the flap is invisible unless someone reads the compose log.

Two consequences for this change:

- The earlier evidence should be read as "an advance-driven reconcile does not exhibit it",
  not "the defect does not occur". Deliberate advances read a current view and were never
  going to sample it; the timer path still does, and now does so at a predictable moment.
- That predictable moment is a better reproduction than the original races. A scenario that
  pauses its loops, closes a listing through the deal path, and then resumes produces the
  reopen at a known point rather than at a random one — which is close to the
  construction the previous note called for, and available end-to-end as well as at
  integration level.

The open questions are unchanged; this adds a third sample and a reliable trigger.
