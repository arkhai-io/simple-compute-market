## ADDED Requirements

### Requirement: Independently deployable bare-metal seller role

The bare-metal storefront MUST be buildable, configurable, migratable, and deployable independently from the VM storefront while consuming published internal packages and the shared compute-provisioning service contract. VM and bare-metal storefront processes MUST NOT share a writable storefront database.

#### Scenario: Operator deploys both compute storefronts

- **WHEN** an operator enables VM and bare-metal storefront roles for one seller environment
- **THEN** each role has independent process and persistence state and both may connect to the same configured provisioning authorities

#### Scenario: Operator deploys only one compute storefront

- **WHEN** either the VM or bare-metal storefront role is disabled
- **THEN** the enabled role starts without waiting for or resolving the disabled storefront service

#### Scenario: Bare-metal storefront package is installed

- **WHEN** the bare-metal storefront distribution is installed from its built wheel or image
- **THEN** it starts without editable sibling-package paths and includes the declared domain and shared-role runtime dependencies

#### Scenario: Trusted site configuration is invalid

- **WHEN** a configured site has a duplicate or malformed stable identity, unsafe authority URL, missing credential, or unknown field
- **THEN** storefront startup fails rather than dropping, guessing, or merging that binding

#### Scenario: Operator inspects site configuration

- **WHEN** an authenticated operator requests site-binding diagnostics
- **THEN** the response identifies configured site IDs and configuration presence without returning authority URLs or credential values
