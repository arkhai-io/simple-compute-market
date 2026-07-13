# Market Composition Specification

## Purpose

Define the dependency direction and role/domain/plugin boundaries that keep market orchestration schema-opaque.

## Requirements

### Requirement: Schema-opaque core orchestration
Core role packages MUST own discovery, negotiation, settlement, and servicing control flow without importing a concrete market domain or settlement mechanism.

#### Scenario: Installing core without a domain plugin
- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery behavior and no concrete market verbs

### Requirement: Domain-owned deterministic semantics
A domain package MUST own the listing, message, terms, materialization, receipt, result vocabulary, and pure interpretation required for independent implementations of that market to agree.

#### Scenario: Adding a market domain
- **WHEN** a new listing schema is introduced
- **THEN** its deterministic codecs and reference semantics can be installed without modifying core orchestration

### Requirement: From-below kit dependencies
Kit and domain concept modules MUST NOT depend on core composition packages; role implementations MAY depend on both the relevant core role and domain/kit contracts.

#### Scenario: Architecture boundary tests run
- **WHEN** imports are checked for core, kit, and domain concept packages
- **THEN** core has no domain imports and from-below modules have no upward composition imports

### Requirement: Role-owned executable composition
The buyer executable MUST be core-owned and load domain plugins, and registry behavior MUST be core-owned and schema-configured. The current VM and API-credit storefront executables and the VM provisioning executable are domain-owned composition roots; making those executables generic is proposed work, not current baseline behavior.

#### Scenario: A buyer domain plugin is installed
- **WHEN** the core `market` executable starts
- **THEN** that plugin registers its domain verbs through entry-point composition

#### Scenario: Seller starts a current storefront
- **WHEN** a VM or API-credit storefront is launched
- **THEN** the domain-owned composition root assembles the shared storefront role with that domain's runtime and infrastructure adapters

### Requirement: Versioned market-domain contract
Core role packages MUST expose one versioned market-domain contract for deterministic codecs and role integration hooks, and concrete domain packages MUST implement that contract without core importing their implementations.

#### Scenario: Shipped domains are loaded
- **WHEN** VM, bare-metal, and API-credit plugins are discovered independently
- **THEN** each satisfies the same supported contract version and registers a unique domain identity without modifying core

#### Scenario: Unsupported contract version is installed
- **WHEN** a domain plugin declares a contract version the role does not support
- **THEN** startup fails with the domain identity and supported version range before serving requests

### Requirement: Explicit optional domain capabilities
A domain MUST declare optional capabilities and supply the typed hook set required by each declaration; absence of a capability MUST be valid and MUST NOT require placeholder or no-op implementations.

#### Scenario: API-credit domain has no compute provisioner
- **WHEN** the API-credit domain is composed without a compute-provisioning capability
- **THEN** buyer and storefront roles remain usable and expose no compute-provisioning hooks for that domain

#### Scenario: Declared capability is incomplete
- **WHEN** a domain declares a capability but omits a required hook
- **THEN** composition rejects the plugin with an actionable capability validation error

## Evidence

- Import boundaries: `core/tests/unit/test_carrier_purity.py` and `domains/vms/storefront/tests/unit/test_architecture_imports.py`.
- Core CLI fallback and shipped plugin contracts: `core/buyer/tests/unit/test_cli.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Distribution entry points: `core/buyer/pyproject.toml`, `domains/vms/buyer/pyproject.toml`, and `domains/apicredits/buyer/pyproject.toml`.
