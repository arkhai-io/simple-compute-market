## ADDED Requirements

### Requirement: The API-credit lane holds and steps its storefront's loops

The API-credit end-to-end lane MUST hold the API-credit storefront's lifecycle loops
for the duration of its deal scenario and advance each transition the scenario depends
on through the canonical storefront client.

#### Scenario: The API-credit deal runs

- **WHEN** the API-credit lane runs its deal scenario
- **THEN** the storefront's loops are paused at the start, and every loop transition
  the scenario observes was advanced by an explicit step

### Requirement: The API-credit storefront has production-application integration tests

The API-credit storefront's integration tests MUST run the application the storefront
serves through its lifespan, against a real database, driven by the canonical typed
client. A test that assembles its own application or replaces the lifespan MUST NOT
be presented as an integration test.

#### Scenario: A lifecycle route is tested at integration level

- **WHEN** an integration test exercises an API-credit lifecycle route
- **THEN** the loops it holds and steps were started by the storefront's own startup
