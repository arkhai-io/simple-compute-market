# Tasks

## 1. Approved boundary

- [x] 1.1 Stage 1 proposal and strict scoped validation completed before implementation approval.
- [x] 1.2 Q10: retarget onto `origin/integration/arkhai-payments` at `4881ca816`; reuse its full-shape fit, registry convergence, closure provenance and 30-second publication loop.
- [x] 1.3 Q11: new deterministic integration property explicitly approved for both listing modes, quiet-cycle/restart retry and stable identity. No hosted purchases, live services, deployment pin changes or merge.

## 2. Implementation

- [x] 2.1 VM `services/site_projection_cache.py`: return successful fresh-known views for both families; preserve failed-site holds and known-empty semantics.
- [x] 2.2 VM `services/capacity_client.py`: refresh before existing close/reopen selection and invoke existing registry convergence even without a local transition. Reuse full-shape selectors, stored candidates and seller guards.
- [x] 2.3 Kit `capacity.py`, `capacity_remote.py` and VM `services/publication_loop.py`: share one serialized decision boundary and run bounded quiet-cycle/startup recovery. No settlement-path effect.
- [x] 2.4 Core `sqlite_client.py`: include missing configured-registry delivery rows in existing divergence discovery. Reuse schema and delivery machinery.

## 3. Validation

- [x] 3.1 Add the approved deterministic integration property at the existing VM publication app boundary; real app/SQLite/lifecycle with external site/registry controls. Cover both modes, 8→0→1, no early closure, same ID, registry failures, quiet cycles and reconstructed runtime over durable state. No sleeps.
- [x] 3.2 Rebuild `.dist` wheels and explicitly reinit kit/core/VM environments. Run affected kit capacity/event/publication/convergence suites, core registry/persistence suites, VM projection/remote-capacity/reconciler/publication unit suites and admin/listings/publication/shape integration suites. Run relevant typing checks. Evidence: `docs/attachments/capacity-listing-reconciliation.md`; 584 passed, two existing skips; two reproduced baseline typing diagnostics remain (SCM #303).
- [x] 3.3 Revalidate scoped OpenSpec on the approved base. Record exact commands/results and disclose unrun hosted end-to-end checks; no live substitution or deployment preparation claim.

## 4. Documentation and closeout

- [x] 4.1 Review code, then promote verified behavior/rationale into storefront-publication spec/architecture, repository architecture and deployment guide; complete the promotion record. Check roadmap and campaign-index currency explicitly.
- [x] 4.2 Run comment hygiene, inspect touched comments/imports, and compress completed task notes while preserving history. Run scoped documentation citations, packaging/architecture checks and strict OpenSpec validation; disclose unrelated failures and unrun pipeline checks.
- [x] 4.3 Committed with hooks enabled and opened [PR #304](https://github.com/arkhai-io/simple-compute-market/pull/304) against `integration/arkhai-payments`. PR includes before/after evidence, baseline validation limitations and image-digest/source-pin rollout. Left open for review; no merge, hosted purchase or pin changes. No automatic checks are attached on this non-staging/dev base.
