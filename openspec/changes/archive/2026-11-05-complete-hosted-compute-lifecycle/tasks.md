# Tasks

## 1. Readiness adoption

- [x] 1.1 Add a failing commit-to-ready regression in `domains/bare_metal/storefront/tests/integration/test_lifecycle_dispatch.py`, using the real application/database and typed lifecycle client with an active external fulfillment fake; verify no legacy status/access call is needed and repeated cycles preserve one fulfillment/availability instant.
- [x] 1.2 Update `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py` to adopt an already dispatched unavailable delivery through the existing fulfillment service, with independent error handling from site/end recovery; verify the regression and refusal/teardown cases.
- [x] 1.3 Add the equivalent commitment-only regression in `domains/vms/storefront/tests/integration/test_payment_settlement.py`; verify background completion without buyer status reads and change VM production code only if that test fails.
- [x] 1.4 Run both storefronts' affected lifecycle/payment integration suites and packaging/comment gates; record failing-parent and passing-candidate evidence. Share one full-suite/end-to-end/independent-review round for the final frozen executable candidate.

## 2. Closeout

- [x] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [x] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [x] 2.3 Check durable documentation ownership against the accepted design.
- [x] 2.4 Compress task narrative while retaining design and validation evidence.
- [x] 2.5 Reconcile the readiness gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [x] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [x] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=complete-hosted-compute-lifecycle` on the reviewed candidate.
- [x] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [x] 2.9 Promote readiness ownership/rationale to `openspec/specs/deal-lifecycle/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [x] 2.10 Run `make check-doc-citations CHANGE=complete-hosted-compute-lifecycle` and pinned strict OpenSpec validation; resolve every relevant citation.
- [x] 2.11 Archive last, merging the verified delta into `openspec/specs/deal-lifecycle/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Seller servicing adopts validated readiness without buyer polling and keeps end recovery independent | deal-lifecycle specification and architecture | Promoted to specification and companion |
| No new timer, protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verified unchanged |

Validation: bare-metal lifecycle/payment32 and VM payment/admission/database30 passed. All20root make-test targets pass on6c2fa5004 in
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
