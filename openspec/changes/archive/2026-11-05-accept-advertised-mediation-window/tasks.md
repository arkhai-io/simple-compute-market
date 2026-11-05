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

- [x] Confirm comment hygiene with `make check-comment-hygiene`; return code
  corrections to implementation rather than editing code in closeout.
- [x] Confirm added/touched imports belong at module level unless a demonstrated
  cycle or deliberate lazy-load requirement justifies their placement.
- [x] Recheck accepted decisions against permanent documentation ownership.
- [x] Compress completed-task narrative after preserving rationale in design.
- [x] Update roadmap mapping or record its explicit no-impact disposition.
- [x] Update the campaign index status/dependencies and resolve its directory links.
- [x] Run `make check-packaging` after the frozen implementation is reviewed.
- [x] Obtain applicable end-to-end pipeline evidence for the final code candidate.
  An unavailable required pipeline is a blocker, not an unrun check to waive.
- [x] Promote companion architecture/current-state explanations and complete the
  promotion record. The normative delta merges through archival, not manual duplication.
- [x] Run `make check-doc-citations CHANGE=accept-advertised-mediation-window`,
  resolve every match, then pinned `openspec validate accept-advertised-mediation-window --strict`.
- [x] Archive last so the verified delta merges into the permanent specification;
  closeout review reads the archived change and companion promotion.

## Design promotion record

| Decision | Destination | State |
|---|---|---|
| Minimum window is advertised authority policy, enforced with compute delivery timing | deal-lifecycle spec and architecture | Promoted to specification and companion |

Validation: mediation consumer56, lifecycle62 and payment consumer156 passed. All20root make-test targets pass on6c2fa5004 in
[Tests CI41998371221](https://github.com/arkhai-io/simple-compute-market/actions/runs/41998371221).
The later dev merge changes no application package; its exact resolved code passed
2176tooling and505E2E-unit tests, typed Helm loaders without skips and packaging.
Current comment/import, architecture ownership, citation/index and pinned strict
OpenSpec checks pass. Existing independent implementation review has no finding.

Applicable automated Arkhai system proof covers fresh bare-metal readiness before
legacy reads, ordinary end/access denial, automatic case closure and natural
financial release. Buyer end retry preserves its durable operation; existing case
reads verify bindings and signed records. VM application readiness and unchanged
physical evidence are reused, not a fresh unassisted full VM financial run. Default
Compose/Alkahest markers remain unrun. No LIVE financial proof is claimed.

Companion architecture and roadmap describe current behavior; the design records
promotion destinations and retained provenance. Normative archive and independent documentation review are complete.
Both review axes found no confirmed finding; cleanup retains their records.
