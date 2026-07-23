## ADDED Requirements

### Requirement: Intentional typing of public core boundaries

Core packages that advertise typing MUST type their supported public carriers, protocols, clients, and composition-facing contracts without using static declarations as a substitute for runtime domain/behavioral conformance. Type-only imports MUST preserve the repository dependency hierarchy.

#### Scenario: Public contract is changed

- **WHEN** an advertised typed carrier, protocol, or client surface changes
- **THEN** its package typecheck and runtime/conformance tests both verify the change without importing a higher-layer or concrete domain implementation into core

#### Scenario: Package is not yet fully supported

- **WHEN** a package's intended public exports do not pass its declared typing level
- **THEN** the package does not advertise unsupported typed coverage merely to satisfy the campaign inventory
