# Design

## Context

The generated mediation contract already defines `FilingAnswer`, including an
accepted `CaseAnswer`, pending protection and errors. The case reader and its
in-process peer instead exchange a bare case. See proposal.md for the effect on
delivery-end recovery.

## Decisions

Return `FilingAnswer` from the case client and validate its existing schema.
Unwrap only accepted cases, checking case reference, Agreement and transaction.
For pending protection, check the returned case reference. The adapter maps
non-accepted outcomes through its existing failure classification and adopts
accepted cases only through verified signed records. No duplicate write is
introduced.

Unwrapping in the client while throwing for pending was rejected: pending is an
ordinary authority outcome, not a protocol defect. Accepting both a bare case and
an envelope was rejected because it hides the contract disagreement. No generated
model or schema edit is needed.

## Risks and validation

The Python return type changes; update all callers and trace assertions in this
package together. Exercise the HTTP boundary using accepted and pending envelopes,
wrong bindings and malformed responses, then run all mediation adapter and trace
tests. A passing contract peer does not replace qualification against a deployed
authority. Preserve that separate obligation.

## Migration and promotion

Publish the client and its callers as one package. No stored data migration or
authority rollout is required. Promote outcome-preserving case recovery to
`openspec/specs/deal-lifecycle/spec.md` and its companion architecture after review.
Repository-wide architecture is unchanged.
