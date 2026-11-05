# Tasks

## 1. Preserve canonical public evidence

- [x] 1.1 Add a failing core buyer regression under `core/buyer/tests/unit/` for nested canonical public signer evidence and private/extended/noncanonical rejection; verify the exact failure before changing validation.
- [x] 1.2 Update `core/buyer/src/core_buyer/run_log.py` to validate the narrow public identity shape through the existing identity codec; verify evidence round trips and the complete core buyer suite.
- [ ] 1.3 Exercise the ordinary VM end command and retained signed result under the corrected package, preserving the same operation identity on retry; verify no repeated physical or financial effect.
- [ ] 1.4 Run packaging/comment gates and share one applicable full-suite/end-to-end/independent-review round on the frozen candidate.

- [x] 1.5 Project `core/buyer/src/core_buyer/orchestration.py` settlement-poll observations to public status while returning authenticated delivery intact; verify a real signed HTTP sequence and run-log canary regression under `core/buyer/tests/integration/`, and rerun the core buyer suite.

## 2. Closeout

- [ ] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [ ] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [ ] 2.3 Check durable documentation ownership against the accepted design.
- [ ] 2.4 Compress task narrative while retaining design and validation evidence.
- [ ] 2.5 Reconcile the buyer evidence gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [ ] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [ ] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=retain-public-signer-evidence-in-buyer-logs` on the reviewed candidate.
- [ ] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [ ] 2.9 Promote canonical public signer evidence validation to `openspec/specs/buyer-orchestration/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [ ] 2.10 Run `make check-doc-citations CHANGE=retain-public-signer-evidence-in-buyer-logs` and pinned strict OpenSpec validation; resolve every relevant citation.
- [ ] 2.11 Archive last, merging the verified delta into `openspec/specs/buyer-orchestration/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Preserve canonical public signer evidence while refusing private carriers | buyer-orchestration specification and architecture | Pending |
| No new protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verify at closeout |
