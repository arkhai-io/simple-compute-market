## MODIFIED Requirements

### Requirement: Online bearer consumption
An API gate MUST parse bearer credentials as `<key_id>.<secret>`, verify them through the credits service, and consume a configured fixed amount for each admitted request. Missing or invalid credentials MUST return unauthenticated status, revoked credentials MUST return forbidden status, and exhausted credentials MUST return payment-required status with purchase guidance. Every consumption request MUST carry an idempotency key, and service-side consumption MUST be idempotent per key and idempotency key, so an exact retry of a consume runs again and charges once. Optional middleware caching or batching MUST remain subordinate to the credits service as balance authority.

#### Scenario: Key balance is exhausted
- **WHEN** admitted requests consume the final available units and another request arrives
- **THEN** the next request is rejected as payment required without creating a negative authoritative balance

#### Scenario: Consumption request is retried
- **WHEN** a middleware repeats consumption for one key with the same idempotency key
- **THEN** the credits service charges the balance at most once

#### Scenario: Consumption omits its idempotency key
- **WHEN** a consumption request carries no idempotency key
- **THEN** the credits service refuses it before charging any balance
