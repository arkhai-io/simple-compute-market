## MODIFIED Requirements

### Requirement: Schema-isolated registry composition

One Helm release MAY compose multiple registry instances by aliasing the same
registry role. Each enabled instance MUST select exactly one filter
specification and MUST have independent authority identity, credential Secret,
descriptor, authentication, Service, persistence, and workload coordinates.
Disabling an optional instance MUST emit no resource for that instance and MUST
preserve the existing compute-registry render.

The compute-family instance MUST select its filter specification by the schema
identity naming the family rather than one domain within it, since that
specification carries bare-metal, virtual-machine, and container listings alike. A
deployment MUST NOT select the retired single-domain identity, and because buyer
commands declare the schema identity they understand, a registry and the buyers
querying it MUST move together.

#### Scenario: Compute and API-credit registries are enabled

- **WHEN** an operator enables compute and API-credit registry instances with
  their respective filter specifications
- **THEN** Helm renders two independently named registry workloads, Services,
  PVCs, signer Secret references, descriptors, and schema paths

#### Scenario: API-credit registry is disabled

- **WHEN** an operator renders the default umbrella values
- **THEN** only the existing compute registry resources are emitted and they
  select the `compute.market` filter specification

#### Scenario: A deployment selects the retired schema identity

- **WHEN** values select the compute registry by its retired single-domain schema identity
- **THEN** render or schema validation fails rather than deploying a registry whose
  declared identity no buyer command claims compatibility with

#### Scenario: Registry identities differ

- **WHEN** two registry aliases configure different authority principals
- **THEN** each registry process uses its own identity and credential Secret
  without requiring either to equal an umbrella-global identity
