# Tasks

## 1. Preserve canonical public evidence

- [x] 1.1 Add a failing core buyer regression under `core/buyer/tests/unit/` for nested canonical public signer evidence and private/extended/noncanonical rejection; verify the exact failure before changing validation.
- [x] 1.2 Update `core/buyer/src/core_buyer/run_log.py` to validate the narrow public identity shape through the existing identity codec; verify evidence round trips and the complete core buyer suite.
- [x] 1.3 Exercise the ordinary VM end command and retained signed result under the corrected package, preserving the same operation identity on retry; verify no repeated physical or financial effect.
- [x] 1.4 Run packaging/comment gates and share one applicable full-suite/end-to-end/independent-review round on the frozen candidate.

- [x] 1.5 Project `core/buyer/src/core_buyer/orchestration.py` settlement-poll observations to public status while returning authenticated delivery intact; verify a real signed HTTP sequence and run-log canary regression under `core/buyer/tests/integration/`, and rerun the core buyer suite.

## 2. Closeout

- [x] 2.1 Confirm `make check-comment-hygiene` and return any code correction to implementation.
- [x] 2.2 Confirm touched imports belong at module scope and verify affected suites.
- [x] 2.3 Check durable documentation ownership against the accepted design.
- [x] 2.4 Compress task narrative while retaining design and validation evidence.
- [x] 2.5 Reconcile the buyer evidence gap in `docs/development/ROADMAP.md`, or record its explicit no-impact disposition.
- [x] 2.6 Reconcile this row/dependencies in `openspec/changes/README.md`; run `make check-change-index`.
- [x] 2.7 Run `make check-packaging` and `make check-architecture-change CHANGE=retain-public-signer-evidence-in-buyer-logs` on the reviewed candidate.
- [x] 2.8 Record applicable passing end-to-end pipeline scenarios for the final candidate; an unavailable required pipeline remains an explicit blocker.
- [x] 2.9 Promote canonical public signer evidence validation to `openspec/specs/buyer-orchestration/architecture.md`, retaining the normative delta for archive; complete the promotion record.
- [x] 2.10 Run `make check-doc-citations CHANGE=retain-public-signer-evidence-in-buyer-logs` and pinned strict OpenSpec validation; resolve every relevant citation.
- [x] 2.11 Archive last, merging the verified delta into `openspec/specs/buyer-orchestration/spec.md`, then complete closeout review and archive cleanup.

## Design promotion record

| Decision | Permanent destination | State |
|---|---|---|
| Preserve canonical public signer evidence while refusing private carriers | buyer-orchestration specification and architecture | Promoted to specification and companion |
| No new protocol, dependency edge or repository-wide authority | Existing architecture remains applicable | Verified unchanged |

Validation: core buyer169, including signed HTTP private-result canary coverage passed. All20root make-test targets pass on6c2fa5004 in
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
