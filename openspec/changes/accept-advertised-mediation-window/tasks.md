# Tasks

## 1. Refresh and verify the published consumer boundary

- [x] Refresh `kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/mediation.schema.json`,
  vectors and publication digests from one authoritative publication; run the model
  generator and retain unchanged generated models where the transport closure is unaffected.
- [x] Add focused coverage under `kit/arkhai-mediation/tests/` for the unchanged
  default, shorter advertised minima and malformed values. Retain compute's
  delivery-deadline-plus-authority-minimum check and authority pinning.
- [x] Run the mediation package suite and packaging/comment gates. Reuse exact-input
  passing evidence for unchanged scopes. Review the frozen round independently.

## 2. Closeout

- [ ] Confirm comment hygiene with `make check-comment-hygiene`; return code
  corrections to implementation rather than editing code in closeout.
- [ ] Confirm added/touched imports belong at module level unless a demonstrated
  cycle or deliberate lazy-load requirement justifies their placement.
- [ ] Recheck accepted decisions against permanent documentation ownership.
- [ ] Compress completed-task narrative after preserving rationale in design.
- [ ] Update roadmap mapping or record its explicit no-impact disposition.
- [ ] Update the campaign index status/dependencies and resolve its directory links.
- [ ] Run `make check-packaging` after the frozen implementation is reviewed.
- [ ] Obtain applicable end-to-end pipeline evidence for the final code candidate.
  An unavailable required pipeline is a blocker, not an unrun check to waive.
- [ ] Promote companion architecture/current-state explanations and complete the
  promotion record. The normative delta merges through archival, not manual duplication.
- [ ] Run `make check-doc-citations CHANGE=accept-advertised-mediation-window`,
  resolve every match, then pinned `openspec validate accept-advertised-mediation-window --strict`.
- [ ] Archive last so the verified delta merges into the permanent specification;
  closeout review reads the archived change and companion promotion.

## Design promotion record

| Decision | Destination | State |
|---|---|---|
| Minimum window is advertised authority policy, enforced with compute delivery timing | deal-lifecycle spec and architecture | Pending |

Source checks: mediation consumer56, lifecycle62 and payments-consumer156 tests pass;
models regenerate unchanged. Comment, packaging and change-index gates pass.
Independent implementation review has no remaining material finding. Pipeline
evidence, companion promotion, citations and archival remain pending in order.
