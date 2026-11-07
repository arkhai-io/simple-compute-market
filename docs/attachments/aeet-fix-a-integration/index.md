# Lifecycle and servicing repair integration

## Revision and setup

- Merge: `7fb2dae69` integrates `fixA` (`d52c114d8`) into the implementation
  baseline `8b1a5cfb5`, which already contains the servicing repair and the first
  domain repair checkpoint.
- Final code: `1d713730c`, including the schema-free receipt binding read repair
  found by the first aggregate run.
- Required and prepared environment: local library and in-process application
  qualification using this checkout's built `.dist` wheels. No hosted authority,
  browser, cloud target, account credentials or external deployment is required.
- Personas: the existing public deterministic development signers and injected
  authority fixtures. They are not production identities. Each test owns its
  temporary database and seed state; first-use examples create and clean their
  own state.
- Readiness observed: `make dist` and environment refresh succeed; all nine
  servicing first-use examples and the mediation first-use example complete.
- This packet is nonvisual. No screenshots, live monetary rulings, deployed
  mediation, real hardware or deferred rate execution are claimed.

From a clean checkout, reproduce the library/API surface and focused checks:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/deal-servicing test typecheck first-use
make -C kit/deal-lifecycle test
make -C kit/deal-lifecycle-buyer test
make -C kit/deal-lifecycle-client test
make -C kit/arkhai-mediation test demo
make -C kit/arkhai-payments test
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && uv run --find-links ../../../.dist pytest tests/unit/test_receipt_adapter.py -q)
make -C domains/bare_metal/storefront reinit
(cd domains/bare_metal/storefront && uv run --find-links ../../../.dist pytest tests/test_receipt_adapter.py -q)
make check-architecture check-packaging check-locks check-comment-hygiene
bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict
```

The repository aggregate additionally uses the shell-local Podman compatibility
shim and the same proxy environment:

```sh
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
make test
```

## Resolutions and observations

| Claim | Resolution and observed result | Existing regression surface |
| --- | --- | --- |
| Current authority reads remain fail-closed (S-F4/S-F5) | Current payment/dispute observations drive the read outcome; last verified records, payouts and durable replay floors remain separate. Outage/rejection/recovery and empty/shorter history checks pass. | Servicing `tests/integration/test_observation.py` |
| Repair state includes both workers' fixes (O-F3/O-F11) | Missing credentials, respondent repairs and rejected filings all select repair-required state. Every filing's retained outcome is exposed by read/list. Authority rejections remain terminal across restart. | Servicing respondent and `test_review_fix_a.py` integration suites |
| Filing dispatch retains semantics without blocking the loop (S-F1/O-F2/O-F10/O-F11) | Dispatch returns per-filing progress, reserves/adopts semantic originals, and persists accepted/rejected acknowledgements off-loop. Deal lookup, intent enumeration and async read's new filing projection also stay off-loop. Operator submission reduces those outcomes to one command result. | Servicing `test_review_fix_a.py`, `test_database_execution.py`, mediation `test_semantic_filing.py` |
| Respondent/watch, retention and admission fixes survive (O-F4/O-F8/O-F9/O-F10/O-F16) | Respondent sign-or-contest remains the sole counterparty answer path; pinned ruling actors, refresh-before-prune and unlocked authorization with revision CAS remain intact. | Full servicing suite, including evidence, end, respondent, watch/seller and unchanged-phase admission checks; payments retention projection |
| Both kit test targets run in the aggregate (O-F1) | `kit/Makefile` includes both `test-deal-servicing` and `test-deal-lifecycle-client`, retaining both disposition notes in the change's task record. | Focused targets and full aggregate |
| Receipt callbacks remain selected-adapter and lock-safe (O-F12) | The first aggregate exposed schema installation on a second connection while ingress owned a write transaction. `SellerSession(conn, initialize=False)` now reads the immutable binding without schema writes in both domains. All six unchanged domain checks pass, including the held-write-lock assertions. | Both domains' existing `test_receipt_adapter.py` |
| Existing assertions are preserved | The deferred-filing assertion now checks the exact `(intent_ref, pending)` pair in the per-filing result list; its no-authority-submit assertion remains. No new permanent test or relaxed assertion was introduced by this integration. | Servicing `test_ingress.py` |

## Validation

- Focused combined suites: servicing **48**, lifecycle **61**, buyer **20**,
  signed client **2**, mediation **45**, payments **98** passed. Servicing typing,
  all nine asserted examples, mediation typing/resource/model checks and its
  asserted first use passed.
- After the receipt-lock repair: servicing **48**, typing and all nine examples
  passed again; each domain's receipt-adapter suite passed **3** checks.
- Architecture, packaging, locks, comment hygiene and pinned strict OpenSpec
  validation passed after the final code repair. `make check-packaging` includes
  a fresh wheelhouse build.
- First aggregate: stopped at VM unit tests with two receipt-callback failures
  (`sqlite3.OperationalError: database is locked`). The installed schema
  initializer on the read connection was the located cause, repaired in
  `1d713730c` without changing either domain's assertions.
- Final aggregate on `1d713730c`: **passed in 7m26s** with the prescribed
  Podman shim and proxy environment, including both aggregate kit targets,
  lifecycle contracts **37**, VM storefront **1,192 unit / 501 integration**,
  bare-metal storefront **530**, release tooling **1,858**, and Helm
  structural/render checks. The VM unit collection retained its one existing
  collection skip; there were no failures.
- No checkout-owned resident server, container, browser page or external
  deployment was left running. The shim environment is shell-local; its setup
  ensures the shared rootless Podman API socket is active. That shared socket
  is left active rather than interrupting other users.

The source repair packets remain available at
[`aeet-review-19-20-fix-a`](../aeet-review-19-20-fix-a/index.md) and
[`aeet-servicing-review-fixes`](../aeet-servicing-review-fixes/index.md).
Specification promotion, the remaining domain repair work and archival remain
with their existing owning change; this merge does not close that execution.
