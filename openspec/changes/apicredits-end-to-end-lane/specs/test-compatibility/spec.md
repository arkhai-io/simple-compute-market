## ADDED Requirements

### Requirement: API credits runs in its own end-to-end lane

API credits' end-to-end scenarios MUST run in a lane of their own, as a pipeline job
separate from every other domain's lane, so a failure in one domain's lane cannot
hide or stand in for another's evidence. The lane MUST hold and step the API-credit
storefront's lifecycle loops through the canonical storefront client.

#### Scenario: The pipeline runs

- **WHEN** the end-to-end pipeline runs
- **THEN** the API-credit scenarios run in their own job, and the VM lane's stack
  does not include the API-credit services

### Requirement: The API-credit storefront has production-application integration tests

The API-credit storefront's integration tests MUST run the application the storefront
serves through its lifespan, against a real database, driven by the canonical typed
client. A test that assembles its own application or replaces the lifespan MUST NOT
be presented as an integration test.

#### Scenario: A lifecycle route is tested at integration level

- **WHEN** an integration test exercises an API-credit lifecycle route
- **THEN** the loops it holds and steps were started by the storefront's own startup
