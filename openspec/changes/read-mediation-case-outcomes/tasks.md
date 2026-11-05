# Tasks

## 1. Read and recover case outcomes

- [x] 1.1 Add HTTP-boundary regressions in `kit/arkhai-mediation/tests/integration/test_case_read.py` for accepted/pending envelopes, invalid bindings and malformed shapes; capture the failing accepted response.
- [x] 1.2 Update `client.py`, `adapter.py`, `fixtures/authority.py` and trace assertions under `kit/arkhai-mediation` to consume strict envelopes and preserve pending outcomes; verify the complete package suite and semantic recovery without duplicate POSTs.
- [x] 1.3 Read an existing deployed case through the corrected client and verify its pinned signed records, without creating or changing a case.
- [x] 1.4 Run packaging/comment gates and the applicable full-suite/end-to-end/independent-review round on the frozen candidate.

- [x] 1.5 Refresh paired schema/vector publication resources in `kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/` from one producer publication, update digests and regenerate/check transport models; verify the package contract, typing and suite targets.

## 2. Closeout

- [ ] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [ ] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [ ] 2.3 Check durable documentation ownership against the accepted design.
- [ ] 2.4 Compress task narrative while retaining design and validation evidence.
- [ ] 2.5 Reconcile the mediation recovery gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [ ] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [ ] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=read-mediation-case-outcomes` on the reviewed candidate.
- [ ] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [ ] 2.9 Promote outcome-preserving case recovery to `openspec/specs/deal-lifecycle/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [ ] 2.10 Run `make check-doc-citations CHANGE=read-mediation-case-outcomes` and pinned strict OpenSpec validation; resolve every relevant citation.
- [ ] 2.11 Archive last, merging the verified delta into `openspec/specs/deal-lifecycle/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Preserve accepted/pending protection and strict deal binding on case recovery | deal-lifecycle specification and architecture | Pending |
| No new protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verify at closeout |

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
