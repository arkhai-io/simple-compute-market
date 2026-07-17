## 1. Verify Prerequisites and Define the Proof

- [ ] 1.1 Confirm the common domain contract, POOLS-4 capacity-identity contract, and extracted compute service changes are implemented, synchronized, archived, and passing focused tests
- [ ] 1.2 Inventory existing VM/bare-metal adapter, POOLS-3 provider registration, event-routing, allocation-dispatch, and cross-mode conflict coverage
- [ ] 1.3 Select the smallest deterministic topology that proves two storefront ownership contexts and both production adapter compositions without adding a second site
- [ ] 1.4 Define proof fixtures with explicit `pool_id` or `resource_id`, reject unscoped claims, and verify `resource_id` precedence when both identities are present
- [ ] 1.5 Update this design/specs if current implementation already proves or invalidates an intended scenario

## 2. Exercise Concurrent Adapter Composition

- [ ] 2.1 Start one extracted compute provisioner with VM and bare-metal adapter bundles registered concurrently
- [ ] 2.2 Submit valid VM and bare-metal actions through the common contract and observe their durable terminal jobs
- [ ] 2.3 Verify dispatch selects adapters from committed allocation executor identity and rejects executor substitution before infrastructure work
- [ ] 2.4 Verify registered provider identities do not participate in or override adapter selection from the allocation's committed executor identity; do not require provider-backed bare-metal fulfillment
- [ ] 2.5 Verify VM teardown and bare-metal reclaim release their allocations exactly once through their respective adapters

## 3. Prove Ownership-Aware Event Routing

- [ ] 3.1 Create VM and bare-metal allocations with distinct deal/storefront ownership references
- [ ] 3.2 Deliver lifecycle events through the common event sink and verify each reaches only its recorded owner
- [ ] 3.3 Verify allocation ownership overrides any process-global callback default
- [ ] 3.4 Verify duplicate event delivery is idempotent and does not duplicate storefront transitions

## 4. Prove Cross-Mode Physical Accounting

- [ ] 4.1 Hold shareable VM capacity and verify an exclusive bare-metal reservation on the same Physical Resource fails before job creation
- [ ] 4.2 Hold exclusive bare-metal capacity and verify a conflicting VM reservation fails before job creation
- [ ] 4.3 Verify provider references or access aliases cannot create separate capacity identities for the same Physical Resource and bypass cross-mode exclusion
- [ ] 4.4 Release the conflicting allocation and verify capacity version advances and a later eligible reservation succeeds

## 5. Enforce Architecture Boundaries

- [ ] 5.1 Add static checks that generic site and compute modules do not import VM or bare-metal implementation models
- [ ] 5.2 Run the common market-domain conformance suite for VM, bare metal, and API credits with compute optional for API credits
- [ ] 5.3 Run common compute contract suites for both executor adapters, including executor/provider namespace separation

## 6. Verify the Multi-Domain Outcome

- [ ] 6.1 Run the focused two-domain allocation, execution, event, lease, and release scenario without timing sleeps
- [ ] 6.2 Run affected VM and bare-metal integration suites
- [ ] 6.3 Confirm no second-site, non-compute, or test-only public API scope entered the change
- [ ] 6.4 Validate OpenSpec artifacts and reconcile the initiative index after behavioral verification
