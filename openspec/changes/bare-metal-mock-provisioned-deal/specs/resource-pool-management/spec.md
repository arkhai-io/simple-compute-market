## ADDED Requirements

### Requirement: The pool wire contract and client are thin distributions

The resource-pool capability MUST own its pool wire models and pool route contracts in a
contracts distribution that depends on no persistence or web-framework package, and its
typed client in a separate client distribution depending only on those contracts. The
client MUST offer async and sync variants with identical operations over any transport
that provides authenticated requests, so it depends on no compute-provisioning package. The
pool authority imports its models from the contracts distribution, and the provisioning
service that hosts the pool routes assembles the capability's route contracts into its
table without owning them.

#### Scenario: An operator administers pools

- **WHEN** an operator creates or updates a pool through the resource-pool client
- **THEN** the client signs the request from the resource-pool route contracts, and the
  operator's environment installs neither SQLAlchemy nor the compute provisioning kit

#### Scenario: A compute domain hosts no pool model

- **WHEN** the compute provisioning contracts distribution is inspected
- **THEN** it declares no resource-pool model or pool route contract
