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
The buyer executable MUST be core-owned and load domain plugins; registry behavior MUST be core-owned and schema-configured; storefront/provisioning composition MAY remain domain-owned while the generic executable boundary is migrated.

#### Scenario: Multiple buyer domains are installed
- **WHEN** more than one buyer domain plugin is present
- **THEN** their namespaced verbs compose in one `market` executable

<!-- Provenance: ARCHITECTURE.md “Organizing Principle”, “Package layout”, “CLIs”; evidence: core/tests/unit/test_carrier_purity.py, domains/vms/storefront/tests/unit/test_architecture_imports.py, core/buyer/tests/unit/test_cli.py, domains/vms/buyer/tests/test_plugin_export.py -->
