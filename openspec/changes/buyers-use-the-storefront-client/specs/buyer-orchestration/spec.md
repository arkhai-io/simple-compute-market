## ADDED Requirements

### Requirement: Buyers call storefront routes through typed clients

Buyer packages MUST call storefront routes only through the typed client that owns each route, in its sync or async form. A buyer MUST NOT construct a storefront route path or request body itself. Response verification, exact-retry identity, and publisher-trust refresh MUST be behaviors of that client, not of each caller.

#### Scenario: A storefront route changes its request shape

- **WHEN** a storefront changes a route's request body and its typed client changes with it
- **THEN** every production buyer sends the new shape, because no buyer builds that body itself

#### Scenario: A buyer retries a settlement request

- **WHEN** a buyer retries a settlement request after a transport failure
- **THEN** the typed client signs the retry with the same request identity, and the storefront treats it as the same request
