# Buyer Orchestration Specification

## Purpose

Define registry fan-in, domain plugins, policy-driven negotiation, aggregation, settlement, and run recovery.

## Requirements

### Requirement: Plugin-composed buyer CLI
The core `market` CLI MUST discover domain plugins through entry-point metadata and let each plugin register namespaced verbs without core importing the domain.

#### Scenario: VM and API-credit plugins are installed
- **WHEN** the buyer CLI starts
- **THEN** both domains' verbs are available in one process without name collisions

### Requirement: Linear buy orchestration
A buy run MUST compose discovery, candidate filtering/aggregation, negotiation, and settlement through injected hooks and persist stage results needed for inspection and recovery.

#### Scenario: Settlement response is lost
- **WHEN** the run log contains accepted terms and a deal reference
- **THEN** recovery can inspect or resume the deal without renegotiating a second agreement

### Requirement: Policy-owned negotiation parameters
Negotiation policies MUST own their compatibility checks, CLI parameter surfaces, opening messages, and per-round responses; the core MUST deliver policy parameters without interpreting schema-specific fields.

#### Scenario: Listing has no compatible settlement tuple
- **WHEN** the selected buyer policy rejects every advertised tuple
- **THEN** the buyer reports no compatible format rather than negotiating malformed terms

### Requirement: Schema-opaque aggregation
Core aggregation control flow MUST order and select candidates through registered policies without embedding domain or settlement-kit price vocabulary.

#### Scenario: Alkahest price ordering is requested
- **WHEN** a registered Alkahest aggregation policy is selected
- **THEN** kit code interprets price fields while core applies the resulting ordering

<!-- Provenance: ARCHITECTURE.md buyer CLI and policy sections; evidence: core_buyer orchestrator, plugin discovery, policy surface, escrow selection, run-log/recovery tests -->
