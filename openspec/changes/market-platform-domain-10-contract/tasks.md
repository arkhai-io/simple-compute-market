## 1. Reconcile Current Domain Boundaries

- [ ] 1.1 Inventory every `StorefrontDomainRuntime`, buyer entry point, publication source, policy hook, settlement/fulfillment hook, and shared-client provision-terms caller
- [ ] 1.2 Classify the current VM, bare-metal, and API-credit surfaces as required, optional, domain-local, or obsolete
- [ ] 1.3 Update the design and delta specs if current code invalidates a proposed hook or compatibility assumption

## 2. Define the Core Contract

- [ ] 2.1 Define stable domain identity and independent contract-version types in the lowest core carrier package
- [ ] 2.2 Replace the codec-only runtime with focused immutable codec, buyer, storefront, publication, settlement, and fulfillment capability protocols
- [ ] 2.3 Add typed optional-capability registration and startup validation for duplicate identities, unsupported versions, and incomplete declarations
- [ ] 2.4 Export the public contract with typing metadata without importing concrete domains

## 3. Establish Domain Conformance

- [ ] 3.1 Add a reusable conformance suite for identity/version, codecs, optional capabilities, buyer hooks, storefront hooks, and validation failures
- [ ] 3.2 Add a minimal external-style fake domain proving core extension without core edits or repository-layout assumptions
- [ ] 3.3 Run the suite against the VM implementation and fix only VM-owned adapters
- [ ] 3.4 Run the suite against the bare-metal implementation and fix only bare-metal-owned adapters
- [ ] 3.5 Run the suite against the API-credit implementation and verify compute provisioning remains absent

## 4. Migrate Role Composition

- [ ] 4.1 Make core buyer discovery and command assembly consume the selected domain contract
- [ ] 4.2 Make shared storefront publication, negotiation, settlement, and fulfillment services consume contract capabilities
- [ ] 4.3 Update all three domain entry points and composition roots to provide the new contract
- [ ] 4.4 Extend architecture-boundary tests to reject concrete-domain imports and name-based branches in core

## 5. Cut Over the Negotiation Wire

- [ ] 5.1 Define the versioned domain provision envelope and domain-owned payload validation
- [ ] 5.2 Migrate VM, bare-metal, and API-credit producers and consumers from the flat compute-shaped form
- [ ] 5.3 Bump shared client/server compatibility and make unsupported envelope versions fail before negotiation policy runs
- [ ] 5.4 Remove legacy provision-term coercions, obsolete entry points, and superseded integration paths after every caller migrates

## 6. Verify the Contract

- [ ] 6.1 Run focused core carrier, buyer, storefront, and import-boundary tests
- [ ] 6.2 Run all three domain conformance suites and their affected role tests
- [ ] 6.3 Run negotiation wire round-trip and incompatible-version scenarios
- [ ] 6.4 Validate OpenSpec artifacts and reconcile the initiative index after behavioral verification
