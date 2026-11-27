## RENAMED Requirements

- FROM: `### Requirement: Service calls use the shared version 2 identity contract`
- TO: `### Requirement: Service calls use the shared version 3 identity contract`

## MODIFIED Requirements

### Requirement: Service calls use the shared version 3 identity contract

A provisioning authority MUST authenticate each inbound service request with
the shared `arkhai.market-request-signature.v3` profile and MUST sign each response with
the shared response profile. Verification MUST use the complete counterparty
principal selected by route and authority state, bind the request or response
body digest, require the authority's own principal in the request's audience,
enforce bounded freshness, classify replay durably, and run locally without a
chain or external identity call. Only the version 3 request and response
profiles authenticate the service boundary; shared credentials, caller-selected
expected identities, and unsigned mutation responses MUST NOT do so.

The authority MUST durably reserve `(principal, request_id)` with the request's
hash before dispatch, and resolve an exact retry as the route's declared
exact-retry resolution says: a `RERUN` route runs again, and a `RECORDED` route
returns the recorded status and body under a freshly signed response without
repeating the operation. On a `RERUN` route one caller MAY reclaim an exact
unfinished request after its dispatch lease expires; a `RECORDED` request is
dispatched once, as `marketplace-identity` requires. An in-progress exact retry
or reuse with changed signed content MUST NOT dispatch a second operation.
Relay token rotation and grant-key staging MUST be declared `RECORDED`: each
replaces the relay's value with the request's, and its response holds no secret.

#### Scenario: An inbound request is authenticated

- **WHEN** a storefront calls a provisioning authority with a correctly signed
  version 3 request
- **THEN** the authority verifies its role, exact registered principal, method,
  semantic operation and resource, audience, request identity, origin,
  `created`, and body digest before dispatch

#### Scenario: Request content is changed

- **WHEN** any bound request field or body content is changed after signing
- **THEN** verification fails before the authority performs the operation

#### Scenario: A mutation response is returned

- **WHEN** the authority acknowledges a state-changing request
- **THEN** it signs the status, the request binding, authority principal,
  `created`, and body digest, and the caller verifies that exact authority
  before accepting the acknowledgement

#### Scenario: An exact completed request to a convergent route is retried

- **WHEN** a caller repeats an exact `terminate` request for a lease after losing
  the acknowledgement
- **THEN** the route runs again, finds the lease already releasing or released,
  and answers its current state under a fresh signed response

#### Scenario: An exact completed request is retried

- **WHEN** a caller repeats an exact `POST relays` request that named no relay
  ID, within the retention, after losing the acknowledgement
- **THEN** the authority returns the recorded outcome under a fresh signed
  response and creates no second relay

#### Scenario: An unfinished request is retried

- **WHEN** an exact retry arrives while the original dispatch lease remains
  active
- **THEN** the authority rejects it as still in progress without dispatching a
  second operation

#### Scenario: A grant-key staging is retried after a later staging

- **WHEN** an operator stages a relay grant key and loses the acknowledgement,
  stages another, and the first staging's exact retry arrives within the
  retention
- **THEN** the authority answers the first staging's recorded outcome, its
  public half, and the later staged key remains staged

#### Scenario: A request identity is replayed

- **WHEN** a previously reserved request identity is reused with changed
  content, operation, role, principal, or origin
- **THEN** the authority rejects it as a replay conflict rather than dispatching
  the operation

#### Scenario: Verification runs without external dependencies

- **WHEN** an Ed25519 or EIP-191 signature is verified
- **THEN** verification completes locally without a chain node, RPC endpoint,
  or external identity service

### Requirement: A failure after authentication is answered signed

A provisioning authority, and the services the site kit hosts, MUST answer a
request that fails after it was authenticated — a route raising an unexpected
error — as `marketplace-identity` requires of every authority: with a signed 500 response carrying a fixed
detail that reveals nothing of the error, and MUST log the error itself. On a
route declared `RECORDED`, that response MUST be recorded as the request's
outcome, so an exact retry receives the same signed answer rather than an
unsigned one or an in-progress refusal; on a route declared `RERUN`, nothing is
recorded and an exact retry runs the route again.

#### Scenario: A route raises after authentication

- **WHEN** an authenticated request reaches a provisioning route that raises an
  unexpected error
- **THEN** the caller receives a signed 500 its typed client verifies, and the error is
  logged by the service

#### Scenario: The failed request is retried exactly

- **WHEN** the caller retries a failed request to a `RECORDED` provisioning route with
  the same request identity and body, within the retention
- **THEN** it receives the recorded signed 500 without the route running again

#### Scenario: The failed request to a re-run route is retried exactly

- **WHEN** the caller retries a failed request to a `RERUN` provisioning route with the
  same request identity and body
- **THEN** the route runs again and its answer is signed

#### Scenario: A route behind the site kit's middleware raises

- **WHEN** an authenticated request to the API-credits service reaches a route that
  raises an unexpected error
- **THEN** the caller receives a signed 500 its typed client verifies, and the error is
  logged by the service

## ADDED Requirements

### Requirement: Provisioning operations are recognisable when repeated

A relay create MUST name its `relay_id`, and a repeat under a recorded ID MUST be
refused without creating a relay. A grant-key activation MUST name the staged key it
activates, and MUST be refused, activating nothing, when that key is not the one
staged. Host capacity and diagnostics reads MUST key the job they submit by the
request, as the VM job routes do, so a repeat answers the job the first submitted. A
principal rotation whose nonce is already recorded with the same intent MUST be
answered with the applied rotation before the active-principal and intent-expiry
checks. A fulfillment scheduling request whose reservation already holds an assignment
MUST be answered with it before the pool's delivery is checked.

#### Scenario: A relay create is retried after the relay moved

- **WHEN** a relay create applies, its acknowledgement is lost, an operator then
  changes the relay's endpoint, and the create's exact retry arrives
- **THEN** the service refuses the retry under the recorded relay ID and creates no
  second relay

#### Scenario: An activation is retried after a later staging

- **WHEN** an activation of staged key K1 applies, its acknowledgement is lost, the
  operator stages key K2, and the activation's exact retry arrives
- **THEN** K2 stays staged and is not activated

#### Scenario: A provisioning rotation is retried after its intent expired

- **WHEN** a provisioning principal rotation applies, its acknowledgement is lost,
  and its exact retry arrives after the intent's expiry
- **THEN** the service answers the applied rotation and does not refuse the retry

#### Scenario: A host capacity check is retried

- **WHEN** a host capacity check's exact retry arrives after the first submitted its
  job
- **THEN** the service answers that job and submits no second one
