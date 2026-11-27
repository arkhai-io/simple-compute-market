> Permanent destination: `openspec/specs/test-compatibility/spec.md`; test-level placement guidance also promotes to `docs/development/TESTING.md` only where it adds durable methodology rather than change-specific file lists.

## ADDED Requirements

### Requirement: Injected storefront contracts have boundary-owned evidence

Focused tests MUST prove that one caller-supplied compatible domain contract reaches the application, lifespan/container, repository, publication, negotiation, settlement, and fulfillment boundaries by identity, and that incompatible type, domain identity, version, declaration, or hook-set inputs fail before startup side effects. Existing package and integration tests MUST continue to own observable VM listing, negotiation, settlement, and Alkahest parity rather than duplicating those assertions in a new end-to-end lane.

#### Scenario: Distinct compatible contract is injected

- **WHEN** a focused composition test supplies a compatible `compute.v1` contract object distinct from the default object
- **THEN** app state and every constructed domain-sensitive boundary expose that exact object and no test needs to monkeypatch a module-level domain accessor

#### Scenario: Compatibility matrix is exercised

- **WHEN** focused tests supply a non-contract value, unsupported version, wrong stable identity, missing declaration, undeclared implementation, incomplete codec, or incomplete required role capability
- **THEN** each case reports the incompatible domain/version/capability at the composition boundary and proves that repository construction, publication, negotiation, settlement, and fulfillment were not entered

#### Scenario: Existing behavior suites run

- **WHEN** the VM storefront unit, package integration, and selected installed-wheel suites execute with the default injected contract
- **THEN** their existing listing, negotiation, settlement, fulfillment, route, persistence, and Alkahest assertions pass without public fixture changes attributable to parameterization

### Requirement: Parameterization preserves package direction

Architecture and package tests MUST prove that contract injection does not add concrete-domain imports to core or kit packages, cross-import VM and bare-metal composition roots, create editable sibling dependencies, or make an installed VM wheel depend on source-tree module state.

#### Scenario: Import boundary tests inspect production modules

- **WHEN** the repository's architecture import tests scan core, kit, VM, and bare-metal composition modules
- **THEN** dependencies continue to point from each domain-owned composition root into core and kit contracts, never from core or kit into a concrete domain or from VM into bare-metal

#### Scenario: VM storefront is loaded from built packages

- **WHEN** the VM storefront and its internal dependencies are built and installed from ordinary wheels
- **THEN** the default root can construct and inject its contract without editable source paths, import-time test patches, or an undeclared package dependency
