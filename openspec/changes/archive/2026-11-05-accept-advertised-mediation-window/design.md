# Design

The consumer validates the authority's published Description through the vendored
language-neutral schema. The authority owns its policy; lifecycle terms enforce
that advertised minimum and, for compute, require the dispute window to cover the
delivery deadline plus that minimum. A shorter advertisement does not remove either
check. Accepted deals retain their pinned authority and terms.

Refresh schema and vectors together from one authoritative publication, update
content digests and run the model generator. Do not hand-edit generated artifacts
or carry producer source identity into this public repository. Existing default
advertisements and signed vectors retain their meaning. Only refreshed consumers
are expected to accept the new shorter non-live advertisement.

Alternatives: locally masking validation would misrepresent the contract; hardcoding
another duration would repeat the policy coupling. Neither is accepted.

Deployment and policy qualification remain separate from source/schema acceptance.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Authority minimum remains advertised policy; compute includes the delivery allowance and pins accepted terms | `openspec/specs/deal-lifecycle/architecture.md#parts-and-terms` | Promoted to specification and companion |
| Existing authority, dependency, wire and persistence boundaries remain applicable | `docs/development/ARCHITECTURE.md` | Verified no repository-wide change needed |

Qualification scope and current-state summary are reconciled in
`docs/development/ROADMAP.md#payment-qualification-boundaries`.

## Validation provenance

The following preserves pre-archive implementation and qualification observations
compressed from the task ledger. Final promotion and review are recorded above.

Source checks: mediation consumer56, lifecycle62 and payments-consumer156 tests pass;
models regenerate unchanged. Comment, packaging and change-index gates pass.
Independent implementation review has no remaining material finding. Pipeline
evidence, companion promotion, citations and archival remain pending in order.

Documentation promotion: the companion architecture records the accepted current
behavior at `openspec/specs/deal-lifecycle/architecture.md#parts-and-terms`. The design-promotion record identifies the unchanged
repository-wide boundaries and roadmap destination. Normative deltas and archival
remain outstanding; documentation edits change no executable package input.

Closeout checks: comment/import discipline and changed/permanent citations pass;
`make check-change` and `make check-architecture-change CHANGE=accept-advertised-mediation-window`
pass with pinned strict validation. Packaging is reused from the unchanged reviewed
executable inputs; no package, lock, code or architecture-rule input changed.
All root make-test targets pass in Tests CI41998371221 on6c2fa5004; subsequent
dev integration adds only workflow/introduction-test changes, with2176tooling and
505E2E-unit tests and packaging passing on the exact resolved code. Applicable
automated ordinary-buyer Arkhai qualification is recorded separately from the
unrun default Compose/Alkahest workflow. No fresh unassisted VM financial run
or LIVE financial processing is claimed. Normative merge/archive and its
independent documentation review remain the final unchecked closeout task.

Normative promotion: `openspec/specs/deal-lifecycle/spec.md#requirement-dispute-timing-terms-are-bounded`.
The archived documentation was independently reviewed at b829afbdb, with no
confirmed Standards or Spec finding.
