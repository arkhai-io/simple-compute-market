# Design

## Context

See `proposal.md`. Bare-metal commit dispatches a durable fulfillment, but only
the fulfillment status/access path adopts its active result. The servicing sweep
recovers lease ends without adopting readiness. VM payment delivery already has
a background task; its equivalent flow needs a regression, not an assumed patch.

## Decisions

1. The existing bare-metal servicing cycle adopts readiness through the same
   domain service used by authenticated fulfillment reads. Reuse result
   validation, selected-site identity, evidence verification and disclosure
   admission rather than writing availability directly from a site lease.
2. Adopt only an already dispatched delivery whose readiness checkpoints are
   incomplete. Availability, private result and receipt can commit separately,
   so a cycle also completes missing result/receipt writes after availability.
   A cycle must not
   schedule another fulfillment or reset a recorded availability instant.
   Ended and past-deadline deals remain governed by end-service admission.
3. Keep readiness observation, site-end recovery and physical-end execution as
   independent attempts. A failed observation must not prevent cleanup.
4. Use the existing timer and its one-cycle handler. Buyer-driven polling and
   a new daemon were considered and rejected: progress belongs to the seller's
   existing durable servicing, including when the buyer disconnects.
5. Verify VM commit through background completion without status polling. Only
   change VM production code if that representative regression fails.

## Compatibility and deployment

No schema or wire change, new setting, or new package edge is required.
Deploy a tested storefront build with trading paused and preserve its database
and accepted obligations. Returning to an older build retains the same records
but restores its readiness defect; no database restoration is involved.

## Risks and validation

Readiness can race an end or deadline. Tests must cover admission refusal and
unchanged physical recovery, and must not infer availability from lease activation.
Provider observation failures remain retryable on a later ordinary cycle.
Use real application/persistence fixtures with controlled external providers and
typed lifecycle clients; no sleeps or legacy status calls may drive the success.

## Cadence and promotion

One implementation section, focused tests and packaging before commit. The frozen
round shares applicable full-suite, end-to-end and independent-review evidence
with other corrections on the same executable candidate. Promote the normative
delta and explanation into `deal-lifecycle`; repository-wide ownership is unchanged.
