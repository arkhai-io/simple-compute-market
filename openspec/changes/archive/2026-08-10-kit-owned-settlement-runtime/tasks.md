# Implementation Tasks

## 1. Confirm the cutover boundary

- [x] 1.1 Re-verify VM/API-credit line counts, bare-metal behavior, the unfinished
  composition seam, and the landed obligation runtime.
- [x] 1.2 Record shared control flow, domain/mechanism injections, drift decisions, and
  the prohibition on a second claim lifecycle in `design.md`.

## 2. Build the settlement-runtime kit

- [x] 2.1 Create `kit/settlement-runtime` with models, ports, runtime, servicing, policy,
  and composition modules derived from the landed obligation runtime.
- [x] 2.2 Port stable identity, role authorization, operation lease/CAS, uncertain
  acknowledgement, retry, aggregate-status, and worker tests into the kit.
- [x] 2.3 Add the `ConditionalEscrowClient` port, authoritative status reconciliation,
  pre-materialized adoption, immutable fulfillment binding, and durable due-work sweep.
- [x] 2.4 Prove downward-only imports and keep private fulfillment/provider payloads out of
  generic state.

## 3. Cut over persistence and Alkahest

- [x] 3.1 Make `core_storefront.SQLiteClient` the injected store adapter and migrate legacy
  claim rows atomically into exact stable obligation state.
- [x] 3.2 Remove `ClaimRecord`, `ClaimsEngine`, `settlement_claims` runtime writes,
  dual-write projection, and minimal-obligation fallback after migration parity.
- [x] 3.3 Implement the `alkahest.v1` conditional-escrow adapter over existing codecs and
  preserve trusted-oracle/recipient/all-arbiter check and collection behavior.
- [x] 3.4 Port claim servicing, restart, backoff, abandonment, and collect/reclaim race
  tests to the single runtime.

## 4. Compose domains without copies

- [x] 4.1 Compose VM settlement start/recovery/servicing onto exact obligation refs;
  preserve provisioning, response projection, lease truncation, and failure boundaries.
- [x] 4.2 Compose API-credit settlement/servicing onto the same runtime; preserve quantity,
  key delivery, quota repair, and inline post-issuance rollback.
- [x] 4.3 Replace both local failure-policy engines with the shared ordered dispatcher and
  injected real domain handlers.
- [x] 4.4 Remove both domain-local `settlement_jobs`, `claims_runtime`, and `failure_policy`
  implementations and every obsolete compatibility import.
- [x] 4.5 Keep bare metal explicitly verified-only and prove it gains no synthetic
  fulfillment, claim, collection, or provider dependency.

## 5. Packaging and permanent contract

- [x] 5.1 Add kit aggregate build/test targets; update dependent pyprojects, Makefiles,
  Dockerfile wheel refresh, review-wheelhouse scope, distributions, and manifests.
- [x] 5.2 Regenerate affected `uv.lock` files through `uv`; verify no absolute source paths.
- [x] 5.3 Promote runtime ownership to `market-composition`, lifecycle behavior/rationale to
  `settlement-servicing`, and repository layering to `ARCHITECTURE.md`.
- [x] 5.4 Update Goal 4 current-state and remaining gaps in `ROADMAP.md`.

## 6. Validation and closeout

- [x] 6.1 Run kit, core storefront, Alkahest, VM, API-credit, bare-metal, domain
  conformance, packaging, typing, migration, and focused end-to-end settlement suites.
- [x] 6.2 Confirm no production callsite can write or service the legacy claim lifecycle
  and no extracted domain-local implementation remains.
- [x] 6.3 Run `openspec validate --all --strict` and `make check-comment-hygiene`.
- [x] 6.4 Review moved docstrings/comments and touched local imports; compress task notes;
  complete the design-promotion record; disclose any unrun external check; archive.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Kit-owned single obligation lifecycle and dependency direction | `openspec/specs/market-composition/spec.md`; `docs/development/ARCHITECTURE.md` |
| Stable identity, worker, conditional-escrow port, migration, and bare-metal boundary | `openspec/specs/settlement-servicing/spec.md`; `architecture.md` |
| Drift choices and migration mechanics | This change's `design.md` |
| Current state and remaining gaps | `docs/development/ROADMAP.md` |
