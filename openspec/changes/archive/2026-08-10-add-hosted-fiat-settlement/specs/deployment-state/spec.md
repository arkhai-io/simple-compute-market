## ADDED Requirements

### Requirement: Immutable hosted release consumption

Marketplace packaging and deployment MUST pin one hosted release manifest that binds the exact client wheel version/hash, service image digest, OpenAPI and conformance-fixture hash, migration/schema version, SBOM, and build provenance. CI and deployment MUST verify the manifest and provenance signatures against an allowlisted hosted-repository identity and MUST reject floating image tags, unverified artifacts, or compatible-major substitution.

#### Scenario: Client wheel and image originate from different manifests
- **WHEN** artifact hashes do not match one signed manifest
- **THEN** packaging and deployment fail before the storefront starts or runs conformance tests

#### Scenario: Hosted readiness is checked
- **WHEN** the storefront starts with hosted settlement enabled
- **THEN** `/health/ready` must report the exact expected manifest, API version, and required capabilities

### Requirement: Marketplace deployment config contains consumer data only

VM deployment configuration MAY contain the hosted service URL, request credential reference, preflight/request timeouts, expected contract/capability version, and trusted manifest identity. It MUST NOT contain Stripe/admin/webhook secrets, EAS signing keys, RPC private configuration, provider IDs, service database state, or service migration controls.

#### Scenario: VM chart renders with hosted settlement enabled
- **WHEN** trusted hosted release values are supplied
- **THEN** the chart configures only the storefront client/adapter and renders no hosted API, worker, migration, Secret, ingress, database, or service PVC

### Requirement: Packaging preserves provider separation

Root and VM packaging, review-wheelhouse scope, publishing workflow, and storefront image MUST include the exact client and thin adapter when enabled. Only the independently released hosted image MAY contain Stripe/EVM implementations. Compose MAY consume that image by digest for E2E but MUST NOT build sibling source.

#### Scenario: Release artifacts are inspected
- **WHEN** marketplace wheels and storefront images are built
- **THEN** they contain no Stripe SDK, hosted service package, EVM gateway implementation, provider credential, or copied hosted model and signature module
