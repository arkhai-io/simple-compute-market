## MODIFIED Requirements

### Requirement: Versioned market-domain contract
Core role packages MUST expose one versioned market-domain contract for deterministic codecs and role integration hooks, and concrete domain packages MUST implement that contract without core importing their implementations.

#### Scenario: Shipped domains are loaded
- **WHEN** VM, bare-metal, API-credit, and inference plugins are discovered independently
- **THEN** each satisfies the same supported contract version and registers a unique domain identity without modifying core

#### Scenario: Unsupported contract version is installed
- **WHEN** a domain plugin declares a contract version the role does not support
- **THEN** startup fails with the domain identity and supported version range before serving requests
