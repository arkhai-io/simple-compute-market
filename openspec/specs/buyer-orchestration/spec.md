# Buyer Orchestration Specification

## Purpose

Define registry fan-in, domain plugins, policy-driven negotiation, aggregation, settlement, and run recovery.

## Requirements

### Requirement: Plugin-composed buyer CLI
The core `market` CLI MUST discover domain plugins through entry-point metadata and let each plugin register namespaced verbs without core importing the domain.

#### Scenario: A domain plugin is installed
- **WHEN** the buyer CLI starts
- **THEN** the plugin's verbs are registered without the core package importing that domain

### Requirement: Linear buy orchestration
A buy run MUST compose discovery, candidate filtering/aggregation, negotiation, and settlement through injected hooks and persist stage results needed for inspection and recovery.

#### Scenario: Settlement response is lost
- **WHEN** the run log contains accepted terms and a deal reference
- **THEN** recovery can inspect or resume the deal without renegotiating a second agreement

### Requirement: Domain-owned negotiation surface
Domain buyer adapters MUST own settlement compatibility checks and CLI parameters, negotiation policies MUST own opening and per-round decisions, and the core MUST deliver policy inputs without interpreting schema-specific fields.

#### Scenario: Listing has no compatible settlement tuple
- **WHEN** the selected buyer policy rejects every advertised tuple
- **THEN** the buyer reports no compatible format rather than negotiating malformed terms

### Requirement: Policy-specific opening constraints
Buyer role documentation MUST expose any configured policy constraint that can terminate negotiation before a counter-round. For the current maximizing bisection policy, an explicit opening below the seller's advertised primary rate is unsupported; the default listed-price policy opens at that rate.

#### Scenario: Buyer chooses a bisection opening
- **WHEN** a buyer explicitly configures the maximizing bisection policy
- **THEN** role guidance tells the buyer to choose an initial price at least as high as the listing's advertised primary rate

### Requirement: Schema-opaque aggregation
Core aggregation control flow MUST order and select candidates through registered policies without embedding domain or settlement-kit price vocabulary.

#### Scenario: Alkahest price ordering is requested
- **WHEN** a registered Alkahest aggregation policy is selected
- **THEN** kit code interprets price fields while core applies the resulting ordering

## Evidence

- Core/domain import purity and entry-point composition: `core/buyer/tests/unit/test_carrier_purity.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Injected orchestration and aggregation-policy control: `core/buyer/tests/unit/test_orchestrator.py` and `kit/alkahest/tests/unit/test_aggregation.py`.
- Persisted negotiation resume and agreed-run settlement continuation: `domains/vms/buyer/tests/test_buyer_client_resume.py` and `domains/vms/buyer/tests/test_buy_resume_cli.py`.
- Policy-owned negotiation behavior: VM buyer policy and client tests.

Simultaneous command registration for every installed domain plugin is not independently covered by the cited tests; the baseline claim is limited to the plugin boundary and each shipped plugin's export contract.
