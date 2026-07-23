## 1. Obligation identity and persistence

- [ ] 1.1 Inventory every single-obligation and `obligations[0]` assumption across plans, Alkahest adapters, storefront claims, servicing, and buyer reclaim.
- [ ] 1.2 Define stable obligation/idempotency identity, per-step states, aggregate status, and compatibility/backfill in `design.md`.
- [ ] 1.3 Add migrations/repositories for per-obligation materialization, attempts, conditions, collection, reclaim, and receipts.
- [ ] 1.4 Backfill existing agreements as one obligation and add dual-read compatibility tests.

## 2. Generic lifecycle engine

- [ ] 2.1 Add idempotent mechanism ports and servicing operations for materialize/check/collect/reclaim.
- [ ] 2.2 Support buyer-funded and seller-funded direction without branching on obligation position.
- [ ] 2.3 Add claims/restart/concurrency/uncertain-acknowledgment/partial-failure repair tests.
- [ ] 2.4 Remove first-obligation runtime assumptions after compatibility parity is proven.

## 3. Concrete policies

- [ ] 3.1 Implement deterministic interval schedule/rounding/remainder rules and conservation tests.
- [ ] 3.2 Implement seller-funded penalty-bond plan/materialization/claim/reclaim semantics with direction tests.
- [ ] 3.3 Expose per-obligation and aggregate operator state without claiming deferred heartbeat adjudication.

## 4. Verify and promote

- [ ] 4.1 Run core settlement, Alkahest, storefront servicing, buyer reclaim, migration, packaging, and end-to-end multi-obligation suites.
- [ ] 4.2 Promote lifecycle/policy requirements to `openspec/specs/settlement-servicing/spec.md` and rationale/limitations to `architecture.md`.
- [ ] 4.3 Record heartbeat/oracle exclusions and promotion destinations in `design.md`, then run strict validation before archive.
