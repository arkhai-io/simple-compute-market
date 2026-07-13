## ADDED Requirements

### Requirement: Adapter-owned compute execution

VM and bare-metal execution MUST consume the common compute-provisioning envelope while concrete adapters own action validation, infrastructure invocation, result interpretation, credentials, and release behavior.

#### Scenario: Generic provisioner dispatches VM work

- **WHEN** a committed allocation identifies the VM executor and a supported action
- **THEN** generic orchestration selects the registered VM adapter without importing or inspecting VM request fields

#### Scenario: Generic provisioner dispatches bare-metal work

- **WHEN** a committed allocation identifies the bare-metal executor and a supported action
- **THEN** generic orchestration selects the registered bare-metal adapter without importing or inspecting access-grant fields

### Requirement: Compute-owned caller contract

Shared storefront/provisioner DTOs and client behavior MUST be owned by compute provisioning rather than the VM domain, while direct VM operator APIs MAY retain VM-owned models.

#### Scenario: Bare-metal storefront installs the shared client

- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models
