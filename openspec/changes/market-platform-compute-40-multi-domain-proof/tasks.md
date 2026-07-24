## 1. Reconciled prerequisite evidence

- [x] 1.1 Confirm the common domain contract, capacity-identity contract, and extracted compute service are implemented, synchronized, archived, and covered by focused tests.
- [x] 1.2 Inventory current adapter composition, provider registration, dispatch, release, event sink, cross-mode admission, multi-site aggregation, and domain-conformance coverage; record gaps in `design.md`.
- [x] 1.3 Verify one compute service can compose VM and bare-metal adapter bundles and expose durable jobs through the common compute contract.
- [x] 1.4 Verify both VM-shareable→bare-metal-exclusive and bare-metal-exclusive→VM-shareable conflicts within one site, plus capacity restoration after release.
- [x] 1.5 Verify generic site/compute import boundaries and VM, bare-metal, and API-credit market-domain conformance.

## 2. Complete campaign prerequisites

- [ ] 2.1 Complete and archive `market-platform-bare-metal-10-storefront-composition`, including its runnable seller lifecycle and trusted multi-site configuration.
- [x] 2.2 Complete and archive the selected-site scheduling, durable fulfillment, pull result, restart recovery, and teardown portions of `pools-7-storefront-fulfillment-cutover`.
- [ ] 2.3 Reconcile the final prerequisite APIs and persistence identities into this design/spec without copying prerequisite implementation into the proof harness.
- [ ] 2.4 Record exact wheel/image versions and deterministic backend controls used by the proof topology.

## 3. Enforce explicit executor identity

- [ ] 3.1 Inventory every `executor_kind or "vm"`, default executor, and missing-identity compatibility path in compute contracts, persistence, dispatch, result handling, and release.
- [ ] 3.2 Define and implement an explicit migration, backfill, or quarantine policy for legacy durable rows missing executor identity.
- [ ] 3.3 Remove process-global VM fallback from action, result, teardown, and release dispatch after compatibility handling is proven.
- [ ] 3.4 Add focused tests that missing, unknown, and conflicting executor identities fail before adapter or infrastructure work.
- [ ] 3.5 Verify FulfillmentProvider registration cannot infer, substitute, or override recorded executor identity.

## 4. Build the deterministic 2×2 topology

- [ ] 4.1 Start separately composed VM and bare-metal storefront applications with independent writable state.
- [ ] 4.2 Start site A and site B compute provisioning services, each with VM and bare-metal adapter bundles and controlled production-compatible executor backends.
- [ ] 4.3 Configure each storefront with operator-trusted bindings to both sites and no buyer-controlled routing credentials.
- [ ] 4.4 Seed authority-local Physical Resource fixtures that support deterministic placement and cross-mode conflicts without assuming textual IDs are globally unique across sites.
- [ ] 4.5 Add observable job, result, and release barriers so the scenario uses no sleeps for correctness.

## 5. Exercise every storefront-to-site edge

- [ ] 5.1 Complete a VM lifecycle at site A and a VM lifecycle at site B through reservation, scheduling, fulfillment, pull result, teardown, and capacity restoration.
- [ ] 5.2 Complete a bare-metal lifecycle at site A and a bare-metal lifecycle at site B through the same shared contracts.
- [ ] 5.3 Verify each site executes at least one VM and one bare-metal lifecycle and never selects an adapter from storefront identity or provider identity.
- [ ] 5.4 Verify each storefront persists the selected site and routes all later state-changing operations only to that authority.
- [ ] 5.5 Verify VM and bare-metal storefronts retain separate market semantics, databases, agreement state, receipts, and results while sharing provisioning authorities.

## 6. Prove recovery and isolation

- [ ] 6.1 Restart each storefront after reservation and verify durable selected-site lookup resumes fulfillment without fan-out or cross-site fallback.
- [ ] 6.2 Restart each provisioning authority during accepted work and verify POOLS-7 recovery converges without duplicate infrastructure dispatch.
- [ ] 6.3 Make a selected authority unavailable and verify the owning lifecycle reports/retries that authority rather than submitting elsewhere.
- [ ] 6.4 Re-run both cross-mode conflict directions and verify rejection occurs before executor job creation.
- [ ] 6.5 Verify pool, provider, and access aliases within an authority cannot represent one Physical Resource as independent capacity.
- [ ] 6.6 Verify duplicate polling and teardown are idempotent and capacity is restored exactly once.

## 7. Verification and permanent promotion

- [ ] 7.1 Run the focused 2×2 scenario, VM/bare-metal storefront integration suites, compute service unit/integration suites, site/fulfillment suites, and domain conformance suites.
- [ ] 7.2 Rebuild affected wheels and images and verify both storefronts and both provisioners install without editable sibling paths or undeclared domain dependencies.
- [ ] 7.3 Run deployment-render and configuration tests for trusted per-storefront site bindings and independent writable state.
- [ ] 7.4 Promote selected-site/no-fallback behavior to `openspec/specs/site-capacity/spec.md` and `architecture.md`.
- [ ] 7.5 Promote explicit executor identity to `openspec/specs/physical-provisioning/spec.md` and `architecture.md`.
- [ ] 7.6 Promote deterministic matrix evidence to `openspec/specs/test-compatibility/spec.md` and `architecture.md`, and the accepted topology map to `docs/development/ARCHITECTURE.md`.
- [ ] 7.7 Update `openspec/specs/market-composition/architecture.md`, `fulfillment/architecture.md`, and the design-promotion record with the one-domain storefront and pull-correctness boundaries.
- [ ] 7.8 Run strict OpenSpec validation and archive only after the prerequisite and proof behavior is represented as current permanent architecture.
