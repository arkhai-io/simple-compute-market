## ADDED Requirements

### Requirement: Schema-isolated registry composition

One Helm release MAY compose multiple registry instances by aliasing the same
registry role. Each enabled instance MUST select exactly one filter
specification and MUST have independent authority identity, credential Secret,
descriptor, authentication, Service, persistence, and workload coordinates.
Disabling an optional instance MUST emit no resource for that instance and MUST
preserve the existing compute-registry render.

#### Scenario: Compute and API-credit registries are enabled

- **WHEN** an operator enables compute and API-credit registry instances with
  their respective filter specifications
- **THEN** Helm renders two independently named registry workloads, Services,
  PVCs, signer Secret references, descriptors, and schema paths

#### Scenario: API-credit registry is disabled

- **WHEN** an operator renders the default umbrella values
- **THEN** only the existing compute registry resources are emitted and they
  select the `vms.compute` filter specification

#### Scenario: Registry identities differ

- **WHEN** two registry aliases configure different authority principals
- **THEN** each registry process uses its own identity and credential Secret
  without requiring either to equal an umbrella-global identity
