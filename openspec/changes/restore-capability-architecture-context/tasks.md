## 1. Governance and index

- [ ] 1.1 Add `openspec/specs/README.md` as the canonical index linking every capability's `spec.md` and available `architecture.md`.
- [ ] 1.2 Update `openspec/README.md`, `docs/development/ARCHITECTURE.md`, `AGENTS.md`, and `openspec/config.yaml` to define normative specs, companion architecture prose, cross-system documentation, and explicit promotion ownership without duplicating the index.
- [ ] 1.3 Promote the companion-document lifecycle requirement into `openspec/specs/planning-governance/spec.md` and record its permanent destination in `design.md`.

## 2. Composition architecture

- [x] 2.1 Add `openspec/specs/market-composition/architecture.md` covering composition from above and below, typed phase boundaries, package ownership, and current limits.
- [x] 2.2 Add `openspec/specs/registry-discovery/architecture.md` covering schema centralization, signed publisher authority, query-semantic concurrency, and current limits.
- [x] 2.3 Add `openspec/specs/negotiation-protocol/architecture.md` covering canonical signed rounds, transport/policy separation, terms/payment separation, and durability limits.
- [x] 2.4 Add `openspec/specs/storefront-publication/architecture.md` covering seller authority, advisory projection semantics, reconciliation, and site routing trust.
- [x] 2.5 Add `openspec/specs/buyer-orchestration/architecture.md` covering plugin-host ownership, domain/policy/core input separation, persisted runs, and recovery boundaries.

## 3. Capacity and fulfillment architecture

- [x] 3.1 Add `openspec/specs/settlement-servicing/architecture.md` covering lifecycle servicing, codec/hook ownership, heartbeat replay rationale, and current limits.
- [x] 3.2 Add `openspec/specs/site-capacity/architecture.md` covering authoritative admission, private accounting, projection/event privacy, routing identity, and current limits.
- [x] 3.3 Add `openspec/specs/resource-pool-management/architecture.md` covering routing metadata, provider-owned validation, membership, draining, reconciliation, and current limits.
- [x] 3.4 Add `openspec/specs/fulfillment/architecture.md` covering dependency placement, scheduler/provider separation, identifiers/envelopes, and process-local persistence limits.
- [x] 3.5 Add `openspec/specs/physical-provisioning/architecture.md` covering compute composition, adapter registration, durable jobs with transient workers, proof-driven release, and current limits.

## 4. Operations architecture

- [x] 4.1 Add `openspec/specs/deployment-state/architecture.md` covering role-separated topology, state ownership, migration/initialization boundaries, artifact packaging, and verified compatibility posture.
- [x] 4.2 Add `openspec/specs/test-compatibility/architecture.md` covering test jurisdiction, producer/consumer fixtures, deterministic asynchronous seams, staged e2e, and current exceptions.
- [x] 4.3 Keep unresolved publication, package-source, configuration, FRP, typed-client, e2e-extraction, and settlement-generalization claims in this change's deferred design section rather than permanent baseline documents.

## 5. API-credits capability

- [x] 5.1 Verify API-credits authority, pricing, issuance, quota, settlement, and middleware behavior against current implementation and focused unit/conformance/e2e evidence.
- [x] 5.2 Synchronize the new normative contract to `openspec/specs/api-credits/spec.md`.
- [x] 5.3 Add `openspec/specs/api-credits/architecture.md` covering market authorization versus usage identity, quota authority, idempotency boundaries, middleware role, and current limits.
- [ ] 5.4 Add API credits to the capability index and repository-wide service/authority maps without adding endpoint or package inventories.

## 6. Validation and closure

- [ ] 6.1 Check all permanent Markdown links and confirm every indexed capability has a valid `spec.md` and every listed companion exists.
- [ ] 6.2 Run focused API-credits tests that establish the promoted baseline; record passed suites and disclose any unrun system evidence.
- [ ] 6.3 Run strict validation for this change, `planning-governance`, `api-credits`, and all permanent OpenSpec items; distinguish unrelated pre-existing failures.
- [ ] 6.4 Confirm permanent documents contain no change IDs, task references, migration chronology, stale endpoint inventories, or unresolved claims presented as current architecture.
- [ ] 6.5 Complete the design-promotion record, synchronize delta specs, and archive the change only after all permanent destinations are present.
