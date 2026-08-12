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
