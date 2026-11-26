## MODIFIED Requirements

### Requirement: Scheme-neutral storefront authorization

A storefront MUST authenticate publisher, buyer, administrator, and configured service-peer requests through the `arkhai.market-request-signature.v3` profile and MUST authorize complete principals against explicit roles and durable subject bindings selected by route, subject, and site context. Each proof MUST bind the caller role and principal, method, semantic operation, resource, audience, request ID, origin, signing instant, and body digest. The storefront MUST reserve `(principal, request_id)` durably and atomically before route dispatch, reject changed reuse, and resolve an exact retry as the route's declared exact-retry resolution says, never executing a conflicting mutation. It MUST NOT fall back from missing or invalid principal headers to an address in the body, configuration, query, listing, negotiation record, administrator key, or private-key field.

#### Scenario: Body claims the expected buyer address

- **WHEN** a request body names the expected buyer but its proof is missing or belongs to another principal
- **THEN** the storefront rejects the request before negotiation, settlement, fulfillment, or operator state changes

#### Scenario: Provisioning peer uses Ed25519

- **WHEN** an allowlisted Ed25519 service principal submits a valid signed response or callback
- **THEN** the storefront authenticates the configured peer and site binding without requiring an EVM identity

#### Scenario: Exact administrator retry follows a lost acknowledgement

- **WHEN** an administrator re-signs the same `admin_force_accept_negotiation` request with the same principal, request ID and origin after losing the response, within the retention
- **THEN** the storefront returns the recorded outcome without dispatching a conflicting mutation

#### Scenario: Exact retry of an administrator setter

- **WHEN** an administrator re-signs the same `admin_pause_listing` request after losing the response, the listing has been resumed since, and the retry arrives within the retention
- **THEN** the storefront answers the pause's recorded outcome under a fresh signed response without running it again, and the listing stays resumed

#### Scenario: A request ID is reused with changed content

- **WHEN** an authenticated caller reuses its request ID with a different body, role, operation, resource, or origin
- **THEN** the storefront rejects the request before handler dispatch and preserves the first reservation

#### Scenario: Storefront acknowledges an authenticated mutation

- **WHEN** an administrator or configured service peer completes an authenticated mutation
- **THEN** the storefront signs the response over its status, the request binding, storefront principal, signing instant, and body digest
