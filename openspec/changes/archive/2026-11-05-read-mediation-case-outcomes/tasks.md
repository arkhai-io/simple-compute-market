# Tasks

## 1. Read and recover case outcomes

- [x] 1.1 Add HTTP-boundary regressions in `kit/arkhai-mediation/tests/integration/test_case_read.py` for accepted/pending envelopes, invalid bindings and malformed shapes; capture the failing accepted response.
- [x] 1.2 Update `client.py`, `adapter.py`, `fixtures/authority.py` and trace assertions under `kit/arkhai-mediation` to consume strict envelopes and preserve pending outcomes; verify the complete package suite and semantic recovery without duplicate POSTs.
- [x] 1.3 Read an existing deployed case through the corrected client and verify its pinned signed records, without creating or changing a case.
- [x] 1.4 Run packaging/comment gates and the applicable full-suite/end-to-end/independent-review round on the frozen candidate.

- [x] 1.5 Refresh paired schema/vector publication resources in `kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/` from one producer publication, update digests and regenerate/check transport models; verify the package contract, typing and suite targets.

## 2. Closeout

- [x] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [x] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [x] 2.3 Check durable documentation ownership against the accepted design.
- [x] 2.4 Compress task narrative while retaining design and validation evidence.
- [x] 2.5 Reconcile the mediation recovery gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [x] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [x] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=read-mediation-case-outcomes` on the reviewed candidate.
- [x] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [x] 2.9 Promote outcome-preserving case recovery to `openspec/specs/deal-lifecycle/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [x] 2.10 Run `make check-doc-citations CHANGE=read-mediation-case-outcomes` and pinned strict OpenSpec validation; resolve every relevant citation.
- [x] 2.11 Archive last, merging the verified delta into `openspec/specs/deal-lifecycle/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Preserve accepted/pending protection and strict deal binding on case recovery | deal-lifecycle specification and architecture | Promoted to specification and companion |
| No new protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verified unchanged |

Validation: mediation67 with contract/model/typing checks passed. All20root make-test targets pass on6c2fa5004 in
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
