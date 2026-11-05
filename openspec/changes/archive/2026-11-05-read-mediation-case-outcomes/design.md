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

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Case reads retain accepted/pending protection and verify bindings without duplicate filing | `openspec/specs/deal-lifecycle/architecture.md#buyer-surrender-and-cases` | Promoted to specification and companion |
| Existing authority, dependency, wire and persistence boundaries remain applicable | `docs/development/ARCHITECTURE.md` | Verified no repository-wide change needed |

Qualification scope and current-state summary are reconciled in
`docs/development/ROADMAP.md#payment-qualification-boundaries`.

## Validation provenance

The following preserves pre-archive implementation and qualification observations
compressed from the task ledger. Final promotion and review are recorded above.

Round validation: mediation 67 tests and contract/generated-model/typing checks
passed. Corrected reads verified existing deployed cases and pinned records.
Existing failed-attempt financial recovery required supported operator action;
that result is not labelled automatic. A fresh ordinary Arkhai-payment bare-metal
journey subsequently closed its case automatically with payee-signed basis and
released payment at natural maturity, without case intervention. Supported-tool
packaging and comment checks passed. The exact executable commit 6c2fa5004 passed
all 20 root make-test targets in
[Tests CI 41998371221](https://github.com/arkhai-io/simple-compute-market/actions/runs/41998371221),
with no confirmed independent Standards/Spec finding. The default Compose
workflow and its named markers remain unrun, not passed. Formal validation and
documentation closeout remain outstanding.

Documentation promotion: the companion architecture records the accepted current
behavior at `openspec/specs/deal-lifecycle/architecture.md#buyer-surrender-and-cases`. The design-promotion record identifies the unchanged
repository-wide boundaries and roadmap destination. Normative deltas and archival
remain outstanding; documentation edits change no executable package input.

Closeout checks: comment/import discipline and changed/permanent citations pass;
`make check-change` and `make check-architecture-change CHANGE=read-mediation-case-outcomes`
pass with pinned strict validation. Packaging is reused from the unchanged reviewed
executable inputs; no package, lock, code or architecture-rule input changed.
All root make-test targets pass in Tests CI41998371221 on6c2fa5004; subsequent
dev integration adds only workflow/introduction-test changes, with2176tooling and
505E2E-unit tests and packaging passing on the exact resolved code. Applicable
automated ordinary-buyer Arkhai qualification is recorded separately from the
unrun default Compose/Alkahest workflow. No fresh unassisted VM financial run
or LIVE financial processing is claimed. Normative merge/archive and its
independent documentation review remain the final unchecked closeout task.

Normative promotion: `openspec/specs/deal-lifecycle/spec.md#requirement-mediation-case-recovery-preserves-protection-outcomes`.
The archived documentation was independently reviewed at b829afbdb, with no
confirmed Standards or Spec finding.
