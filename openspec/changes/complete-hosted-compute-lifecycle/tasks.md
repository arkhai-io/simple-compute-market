# Tasks

## 1. Readiness adoption

- [x] 1.1 Add a failing commit-to-ready regression in `domains/bare_metal/storefront/tests/integration/test_lifecycle_dispatch.py`, using the real application/database and typed lifecycle client with an active external fulfillment fake; verify no legacy status/access call is needed and repeated cycles preserve one fulfillment/availability instant.
- [x] 1.2 Update `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py` to adopt an already dispatched unavailable delivery through the existing fulfillment service, with independent error handling from site/end recovery; verify the regression and refusal/teardown cases.
- [x] 1.3 Add the equivalent commitment-only regression in `domains/vms/storefront/tests/integration/test_payment_settlement.py`; verify background completion without buyer status reads and change VM production code only if that test fails.
- [ ] 1.4 Run both storefronts' affected lifecycle/payment integration suites and packaging/comment gates; record failing-parent and passing-candidate evidence. Share one full-suite/end-to-end/independent-review round for the final frozen executable candidate.

## 2. Closeout

- [ ] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [ ] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [ ] 2.3 Check durable documentation ownership against the accepted design.
- [ ] 2.4 Compress task narrative while retaining design and validation evidence.
- [ ] 2.5 Reconcile the readiness gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [ ] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [ ] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=complete-hosted-compute-lifecycle` on the reviewed candidate.
- [ ] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [ ] 2.9 Promote readiness ownership/rationale to `openspec/specs/deal-lifecycle/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [ ] 2.10 Run `make check-doc-citations CHANGE=complete-hosted-compute-lifecycle` and pinned strict OpenSpec validation; resolve every relevant citation.
- [ ] 2.11 Archive last, merging the verified delta into `openspec/specs/deal-lifecycle/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Seller servicing adopts validated readiness without buyer polling and keeps end recovery independent | deal-lifecycle specification and architecture | Pending |
| No new timer, protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verify at closeout |

Focused verification: the readiness regression failed with `unstarted` before
the fix, then passed. Bare-metal lifecycle/payment integration32 passed; VM
payment/admission/database integration30 passed. Packaging, frozen-round review,
full-suite/end-to-end and closeout gates remain outstanding.
