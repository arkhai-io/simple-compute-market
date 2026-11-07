## ADDED Requirements

### Requirement: Bare-metal hosted activation proves its prerequisite contract

Bare-metal hosted build, deployment rendering, startup, and protected qualification MUST fail closed until the shipped artifacts and permanent current-state contracts provide a runnable buyer, runnable storefront, completed shared composition seams, selected-site physical fulfillment/result/recovery/teardown, and the exact implemented expanded hosted consumer release. The gate MUST identify each absent/unpromoted capability and exact artifact or evidence mismatch. It MUST NOT accept active-change task status, test-only modules, fake/no-op fulfillment, or a manual override as equivalent.

#### Scenario: Shared composition seam is unfinished

- **WHEN** deployment enables `fiat.stripe.v1` for bare metal without the accepted shared buyer/storefront mechanism registry and routes
- **THEN** render/start/qualification fails before publication or financial/physical mutation

#### Scenario: Permanent spec contradicts completion claim

- **WHEN** an active prerequisite reports complete but current permanent documentation or shipped integration still excludes runnable bare-metal composition
- **THEN** activation remains blocked with the inconsistency named

### Requirement: Bare-metal hosted topology is role-scoped and wallet-free

The production topology MUST deploy exact manifest-pinned bare-metal buyer/storefront, hosted client, identity, settlement-runtime, site, compute-provisioning, and bare-metal adapter artifacts. Buyer and storefront MUST use distinct Ed25519 identities and least-privilege hosted roles; buyer payer-profile authorization and seller account bindings MUST be authority/environment scoped. Hosted-only profiles MUST not mount wallet/chain/RPC credentials. Site/provisioner/evidence trust and access-secret delivery MUST remain separate from hosted/provider credentials and from public config, logs, health, and reports.

#### Scenario: Hosted-only stack is rendered

- **WHEN** Alkahest is disabled and hosted card/bank/ACH profiles are configured
- **THEN** required identity, payer, seller, authority, site, provisioner, resolver/evidence, deadline, and release pins are explicit and no wallet or RPC Secret is mounted

#### Scenario: One role receives another role's secret

- **WHEN** rendering would mount buyer payer authority, seller account authority, hosted service provider credentials, site credentials, or access-delivery credentials into the wrong process
- **THEN** validation fails before deployment

### Requirement: Restart and rollback preserve financial and physical owners

Migrations and deployment cutover MUST preserve the accepted hosted obligation, exact site/resource/Capacity Reservation/allocation, fulfillment/provider operation, lease/access/evidence, collection/reclaim, and teardown identities across buyer, storefront, site, and provisioner restarts. After financial or physical mutation, rollback MUST restore matching artifacts/configuration and resume each immutable operation with its owning authority; it MUST NOT rebuild another authority's state, switch mechanism/profile/site/resource, or republish quarantined capacity.

#### Scenario: Storefront restarts after funded allocation

- **WHEN** the hosted operation is funded and the site allocation is committed before access readiness
- **THEN** startup resumes the same physical lifecycle and neither creates another hosted operation nor selects another host

#### Scenario: Teardown is incomplete during rollback

- **WHEN** the lease expired but authoritative access/executor teardown is unresolved
- **THEN** rollback retains the operation and resource quarantine until the pinned physical authorities reconcile it
