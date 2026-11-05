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

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Existing seller servicing adopts validated readiness independently of buyer reads and end recovery | `openspec/specs/deal-lifecycle/architecture.md#background-readiness-adoption` | Promoted to specification and companion |
| Existing authority, dependency, wire and persistence boundaries remain applicable | `docs/development/ARCHITECTURE.md` | Verified no repository-wide change needed |

Qualification scope and current-state summary are reconciled in
`docs/development/ROADMAP.md#payment-qualification-boundaries`.

## Validation provenance

The following preserves pre-archive implementation and qualification observations
compressed from the task ledger. Final promotion and review are recorded above.

Focused verification: the readiness regression failed with `unstarted` before
the fix, then passed. Bare-metal lifecycle/payment integration32 passed; VM
payment/admission/database integration30 passed. The initial implementation
handoff left packaging, frozen-round review and system qualification outstanding;
the subsequent results are recorded below. Closeout remains outstanding.

Round validation: supported-tool packaging and comment checks passed. The exact
executable commit 6c2fa5004 passed all 20 root make-test targets in
[Tests CI 41998371221](https://github.com/arkhai-io/simple-compute-market/actions/runs/41998371221),
with independent Standards/Spec review reporting no confirmed finding.
Automated ordinary-buyer Arkhai-payment system qualification demonstrated fresh
bare-metal readiness before any legacy fulfillment status/access read, followed
by actual GPU work, ordinary teardown, access denial and automatic financial
closeout. VM production code is unchanged; its commitment-to-ready application
regression passed, and unchanged-component physical proof is reused explicitly.
This does not claim a fresh unassisted full VM financial run. The default Compose
workflow and its named markers remain unrun, not passed. Formal closeout must
retain that distinction under the accepted external qualification method in
`docs/development/TESTING.md#accepted-arkhai-purchase-qualification`.

Documentation promotion: the companion architecture records the accepted current
behavior at `openspec/specs/deal-lifecycle/architecture.md#background-readiness-adoption`. The design-promotion record identifies the unchanged
repository-wide boundaries and roadmap destination. Normative deltas and archival
remain outstanding; documentation edits change no executable package input.

Closeout checks: comment/import discipline and changed/permanent citations pass;
`make check-change` and `make check-architecture-change CHANGE=complete-hosted-compute-lifecycle`
pass with pinned strict validation. Packaging is reused from the unchanged reviewed
executable inputs; no package, lock, code or architecture-rule input changed.
All root make-test targets pass in Tests CI41998371221 on6c2fa5004; subsequent
dev integration adds only workflow/introduction-test changes, with2176tooling and
505E2E-unit tests and packaging passing on the exact resolved code. Applicable
automated ordinary-buyer Arkhai qualification is recorded separately from the
unrun default Compose/Alkahest workflow. No fresh unassisted VM financial run
or LIVE financial processing is claimed. Normative merge/archive and its
independent documentation review remain the final unchecked closeout task.

Normative promotion: `openspec/specs/deal-lifecycle/spec.md#requirement-compute-readiness-progresses-without-buyer-polling`.
The archived documentation was independently reviewed at b829afbdb, with no
confirmed Standards or Spec finding.
