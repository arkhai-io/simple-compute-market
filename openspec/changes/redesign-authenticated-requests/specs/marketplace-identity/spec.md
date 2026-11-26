## MODIFIED Requirements

### Requirement: Body-bound authenticated request and response version

Every authenticated request MUST use the `arkhai.market-request.v3` profile of RFC 9421 HTTP Message Signatures, with RFC 9530 `Content-Digest` over the request body bytes. Its signature MUST cover the HTTP method, the content digest, and the covered fields `Market-Role`, `Market-Operation`, `Market-Resource`, `Market-Audience`, `Market-Request-ID` and `Market-Request-Origin`; its `keyid` MUST be the complete principal, its `created` parameter the signing instant, and its `tag` the profile. Behavior-affecting query values MUST be represented in the signed semantic body. The route boundary MUST derive the expected operation and resource from the request independently of proxy path spelling, and the authority MUST refuse a request whose stated operation or resource differs from what the route derives.

`Market-Request-Origin` MUST be the request's first signing instant, unchanged on every retry under the same request ID while each re-signing carries a fresh `created`; it MUST NOT be later than the authority's instant plus the configured skew, except on a time-setting operation mounted under injected time, which "The time-setting operation is exempt from request freshness" governs. `Market-Audience` MUST list the principals the caller would accept the answer from, and an authority MUST accept a request only when its own signing principal is listed. A signed delivery to an endpoint that is not a marketplace authority MUST cover `@target-uri` in place of `Market-Audience`.

The receiving authority MUST reserve `(principal, request_id)` with the request's hash, origin included, before dispatch, enforce configured clock skew on `created` — on every operation but a time-setting operation mounted under injected time, which "The time-setting operation is exempt from request freshness" governs — and reject changed reuse, missing fields, unsupported protocols, or invalid proofs. An exact reuse of the same canonical request MUST resolve as its route declares under "Each route declares how an exact retry is resolved", and MUST NOT execute a conflicting mutation.

Every response an authority returns on an authenticated route MUST use the `arkhai.market-response.v3` profile, covering its status and content digest and, from the request, its method, operation, resource and request ID. This MUST hold for refusals as well as acknowledgements, and for a refusal raised while authenticating the request as well as one raised after, including a request no route serves, signed over the operation, resource and request ID the request states, whether the authority authenticates in middleware or inside its routes. A request that fails after it was authenticated — a route raising an unexpected error — MUST be answered with a signed 500 carrying a fixed detail that reveals nothing of the error, and the error MUST be logged; on a `RECORDED` route that answer MUST be recorded as the request's outcome, and on a `RERUN` route nothing is recorded. A signed 500 MUST NOT be taken to mean that the request applied nothing: a write may have committed before the error, so its effect is unknown, and a caller MUST learn what applied by reading current state before sending a replacement write under a new request ID. A caller MUST verify the proof, body, request binding, and exact expected authority before accepting any of them.

An authority MUST NOT withhold response authentication because trust has not been established. A request carries a request identity when it carries the profile's covered fields `Market-Request-ID`, `Market-Operation` and `Market-Resource`. An answer MAY be unauthenticated only when the request carried no request identity, and an authority MUST NOT invent one in order to sign.

A refusal body MUST NOT disclose anything the caller has not already proven it holds. Naming which bound field disagreed is disclosure of the authority's expectation, not of a secret, and is permitted; a refusal MUST NOT list the operations an authority serves.

An authority MUST refuse a request under `arkhai.market-request-signature.v2` as an unsupported protocol. A version 2 request carries no request identity, so that refusal is unauthenticated. Version 2 signed requests and responses retained as evidence MUST remain verifiable.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, audience, request ID, origin, or `created` change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: A request signed for another authority

- **WHEN** a request whose `Market-Audience` lists only site A's principals reaches site B
- **THEN** site B refuses it with a signed 421 whose body code is `audience_mismatch`, and no handler runs

#### Scenario: An authority rotates during an overlap

- **WHEN** a caller's expected-authority set holds an authority's old and new principals and the authority signs with either
- **THEN** the request's audience includes the authority and it is accepted

#### Scenario: A request names an operation no route serves

- **WHEN** a request carrying a request identity states an operation for a path or method the authority does not serve
- **THEN** the authority answers a signed 404, or 405 with `Allow`, whose body code is `operation_not_served`, bound over the stated operation, resource and request ID

#### Scenario: An authority authenticating inside its routes receives an unmatched request

- **WHEN** a request carrying a request identity reaches the registry on a path no route serves
- **THEN** the registry answers a signed 404 whose body code is `operation_not_served`, although no route's authentication ran

#### Scenario: A storefront route raises after authentication

- **WHEN** an authenticated request reaches a storefront route that raises an unexpected error
- **THEN** the caller receives a signed 500 with a fixed detail that its typed client verifies, and the error is logged by the storefront

#### Scenario: The route binds another operation

- **WHEN** the route a request reaches derives an operation or resource different from the one the request states
- **THEN** the authority answers a signed 400 whose body code is `operation_mismatch` and names the stated and bound values

#### Scenario: A version 2 request arrives

- **WHEN** a request signed under `arkhai.market-request-signature.v2` reaches an authority
- **THEN** it is refused with an unauthenticated 400 whose body code is `unsupported_protocol` and lists `arkhai.market-request.v3`, since the request carries none of the version 3 fields a signed answer binds
- **AND** no request identity is invented to sign it

#### Scenario: A request under an unknown profile carries the version 3 fields

- **WHEN** a request whose signature names a profile the authority does not accept carries `Market-Request-ID`, `Market-Operation` and `Market-Resource`
- **THEN** it is refused with a signed 400 whose body code is `unsupported_protocol`, bound over those stated fields

#### Scenario: Version 2 evidence is verified

- **WHEN** a retained version 2 signed response is verified as evidence
- **THEN** its proof, body hash, request identity and authority principal verify as they did when it was captured

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal, request ID and origin after losing the response
- **THEN** the authority resolves it as the route declares — running a `RERUN` route again or answering a `RECORDED` route's outcome — without executing a conflicting mutation

#### Scenario: A credential-capable route is retried after delivery ends

- **WHEN** a buyer repeats an exact request to a credential-capable compute route after the deal's end was admitted
- **THEN** the route runs its read again and refuses disclosure with a response-authenticated refusal
- **AND** the request's reservation stays in force and no earlier response body is returned

#### Scenario: A credential-capable outcome is recorded

- **WHEN** a credential-capable route returns access material
- **THEN** no response body is recorded for it, since the route is declared `RERUN`, and the reservation holds only the request's hash and expiry

#### Scenario: An authority returns a mutation acknowledgement

- **WHEN** an authority returns a mutation response for an authenticated request
- **THEN** the caller accepts it only after the status, the request binding, exact authority principal, `created`, body digest, and response proof verify

#### Scenario: An authenticated route refuses a caller

- **WHEN** an authority refuses a request on an authenticated route, whether the refusal is raised while authenticating it or after
- **THEN** the refusal carries response authentication bound to the route's operation and resource, the caller's request identity, the refusal status, and the refusal body, and the caller reads the refusal after verifying it

#### Scenario: A refusal cannot be bound to a caller

- **WHEN** a request carries no request identity
- **THEN** the refusal is returned unauthenticated rather than signed against an invented identity

#### Scenario: A valid but unexpected authority signs a response

- **WHEN** another valid principal signs the same response body
- **THEN** verification fails because route and configuration context select a different expected authority

#### Scenario: A supported proof scheme is verified

- **WHEN** the verifier checks an Ed25519 or EIP-191 request or response proof
- **THEN** verification completes locally without a chain node, RPC endpoint, or external identity service

#### Scenario: A request arrives outside the skew

- **WHEN** a signed request on any operation but a time-setting one reaches an authority with a `created` outside its configured skew, or a `Market-Request-Origin` later than its instant plus the skew
- **THEN** it is refused for timestamp skew before dispatch

#### Scenario: A signed webhook delivery is replayed to another receiver

- **WHEN** a signed delivery covering one endpoint's `@target-uri` is sent to a different endpoint
- **THEN** the receiver's verification fails because the covered target is not its own

### Requirement: The time-setting operation is exempt from request freshness

The time-setting operation of a service whose administrator requests are signed, mounted only under injected time, MUST verify its request's signature, administrator principal, operation, method, resource and request-id reservation as every request's, and MUST NOT refuse it for timestamp skew, whether on its `created` or on a `Market-Request-Origin` later than the service's instant plus the skew. No other operation MAY be exempt from request freshness. The response MUST be signed at the service's instant after the set.

#### Scenario: The harness advances past the skew

- **WHEN** the harness, already at 1794823200, sends a time-setting request whose `created` and `Market-Request-Origin` are both 1794823200 to a storefront at 1794822300
- **THEN** the storefront verifies the signature, principal and request-ID reservation, moves to 1794823200, and answers signed at 1794823200

#### Scenario: Another operation arrives skewed

- **WHEN** any other administrator request reaches that storefront with a `created` or a `Market-Request-Origin` 900 s ahead of its instant
- **THEN** it is refused for timestamp skew

## ADDED Requirements

### Requirement: Each route declares how an exact retry is resolved

Every authenticated route MUST declare its exact-retry resolution in its route contract: `RERUN`, under which an exact retry runs the handler again and no response body is recorded; or `RECORDED`, under which the outcome is kept for the authority's retention and an exact retry is answered with it. An authority MUST refuse to start, naming the route, when any route in its application carries neither a declaration nor an explicit mark that it is unauthenticated, whether the authority authenticates in middleware or inside its routes; a time-setting operation the authority signs MUST carry a declaration, not the mark. A concurrent exact retry while the first attempt holds its lease MUST be refused as in progress whatever the route declares. On a `RERUN` route one attempt MAY reclaim an expired lease. A `RECORDED` request MUST NOT be dispatched more than once. While its handler runs, the authority MUST renew the attempt's lease until the handler returns or raises, so that the lease ends only when the attempt has ended. An exact retry that finds no recorded outcome after the first attempt's lease has ended MUST be answered with a signed 409 whose body code is `exact_retry_outcome_unknown`; a caller so answered MUST learn what applied by reading current state before sending a replacement write under a new request ID. A handler serving an exact retry under `RERUN` MUST be told it is a retry. A route MUST be `RERUN` only where its domain recognises the retry as already applied, so that a re-run after any later write changes nothing and its answer tells the caller what happened; an absolute setter or a delete MUST NOT be `RERUN`. Each `RERUN` mutation MUST be proven by a test that dispatches a request, then a later write to the same resource, then the request's exact retry, and finds the later write intact.

#### Scenario: A read is retried exactly

- **WHEN** a caller repeats an exact authenticated read after losing its response
- **THEN** the route runs again under current authorization and answers the current state
- **AND** no response body was recorded for either attempt

#### Scenario: A convergent mutation is retried exactly

- **WHEN** a caller repeats an exact credits consume carrying its idempotency key after losing its acknowledgement
- **THEN** the handler runs again, the balance is charged once, and the answer is the consume's outcome

#### Scenario: A non-convergent mutation is retried exactly

- **WHEN** a buyer repeats an exact `negotiate_new` request after losing its acknowledgement, within the retention
- **THEN** the authority answers the recorded outcome under a fresh response signature and no second negotiation is created

#### Scenario: A delayed retry of an absolute setter follows a later write

- **WHEN** a storefront publishes a listing and loses the acknowledgement, an operator then sets a status override on it, and the storefront's exact retry of the publish arrives within the retention
- **THEN** the registry answers the publish's recorded outcome and the operator's override remains

#### Scenario: A route declares no resolution

- **WHEN** an authority is composed with an authenticated route whose contract declares no exact-retry resolution
- **THEN** the authority refuses to start, naming the route

#### Scenario: A route authenticating inside its handler carries no declaration

- **WHEN** the registry is composed with a route that neither admits requests through the admission core with a declaration nor is marked unauthenticated
- **THEN** the registry refuses to start, naming the route

#### Scenario: An exact retry arrives while the first attempt runs

- **WHEN** an exact retry arrives while the first attempt's lease is held
- **THEN** it is refused as in progress without dispatching a second operation

#### Scenario: A recorded route's attempt is lost after its domain write

- **WHEN** the API-credits service stops after a `credits_key_adjust` request's adjustment commits and before its outcome is recorded, and the request's exact retry arrives after the lease has ended
- **THEN** the service answers a signed 409 whose body code is `exact_retry_outcome_unknown` and does not dispatch the adjustment again
- **AND** the balance reflects the adjustment once

#### Scenario: A recorded route's handler runs longer than its lease period

- **WHEN** a `RECORDED` request's handler is still running after its initial lease period and its exact retry arrives
- **THEN** the lease has been renewed and the retry is refused as in progress without a second dispatch
- **AND** once the handler returns and its outcome is recorded, a later exact retry receives that outcome

#### Scenario: A caller reads state after an attempt ends unrecorded

- **WHEN** the API-credits service stops while a `RECORDED` `credits_key_adjust` attempt runs, its exact retry is answered `exact_retry_outcome_unknown`, and the caller then reads the key
- **THEN** the read shows the key's final state, and no later commit of that attempt changes it

#### Scenario: A recorded route raises after its domain write commits

- **WHEN** a `credits_key_adjust` request's adjustment commits and the route then raises before it answers
- **THEN** the caller receives a signed 500 with a fixed detail, recorded as the request's outcome
- **AND** its exact retry receives the same signed 500 without the adjustment running again, and the balance reflects the adjustment once

#### Scenario: A signed time-setting route in the inventory

- **WHEN** the API-credits service, whose time-setting route is signed, and the registry, whose time route sits behind its API key, are each composed under injected time
- **THEN** the API-credits route carries a `RERUN` declaration and is admitted through the core, exempt only from request freshness, the registry's is marked unauthenticated, and each authority starts

### Requirement: Replay state is bounded by the request

Every reservation MUST carry an expiry on the authority's process time source: the later of its lease deadline and a bound computed from the request alone — for a `RERUN` route, its origin plus twice the configured skew; for a `RECORDED` route, its origin plus the greater of the retention plus the skew and twice the skew — raised whenever its lease is reclaimed or renewed. An expired reservation MUST affect no answer: it is treated as absent, and a reservation under its key replaces it. An authority MUST delete expired reservations by a periodic sweep, run when it starts and then at an interval, so that each is deleted within one interval of its expiry, and MUST NOT keep replay state indefinitely or only in process memory. The retention of recorded outcomes and the sweep's interval MUST each be operator-configurable per authority and MUST default to 24 hours when unset.

On a `RERUN` route a request whose reservation has expired MUST be dispatched as its route declares. On a `RECORDED` route a first use MUST carry an origin within the skew of the authority's instant, and an exact retry whose origin is older than the retention, or whose reservation is gone within it, MUST be answered with a signed `410 Gone` whose body code is `exact_retry_expired`.

#### Scenario: A reservation passes its expiry

- **WHEN** a `RERUN` route's reservation's expiry has passed and the authority's sweep runs
- **THEN** the expired reservation is deleted

#### Scenario: An expired reservation awaits the sweep

- **WHEN** a `RERUN` route's reservation has expired but no sweep has run since, and a request under the same principal and request ID with changed content arrives
- **THEN** the request is reserved and dispatched as a first use, not refused as a replay conflict

#### Scenario: An old-origin request is still running when expired rows are swept

- **WHEN** a `RERUN` request whose origin is older than twice the skew holds its lease, the sweep runs, and its exact retry arrives
- **THEN** its reservation survives the sweep and the retry is refused as in progress without dispatching a second operation

#### Scenario: The sweep's interval is not configured

- **WHEN** an authority starts with no sweep interval configured
- **THEN** it sweeps expired reservations at startup and every 24 hours

#### Scenario: A recorded outcome expires

- **WHEN** an exact retry of a `credits_key_adjust` request arrives with an origin older than the authority's retention
- **THEN** the authority answers a signed 410 whose body code is `exact_retry_expired` and applies no adjustment

#### Scenario: A notification is retried after its reservation expired

- **WHEN** a provisioner resends a capacity-released notification hours after its first attempt, under the same request identity and origin, re-signed
- **THEN** the storefront dispatches it again, it converges, and the answer is signed

#### Scenario: The retention is not configured

- **WHEN** an authority starts with no recorded-outcome retention configured
- **THEN** it keeps recorded outcomes for 24 hours

#### Scenario: An authority restarts

- **WHEN** the API-credits service restarts between a `credits_key_adjust` request's completion and its exact retry inside the retention
- **THEN** the retry is answered with the recorded outcome and no second adjustment is applied, because its reservation was durable
- **AND** a reuse of the same request identity with changed content is refused as a replay conflict

### Requirement: A secret is never recorded for replay

A response carrying a secret — access material, an API-key secret, a password, a private or staged key, or a token — MUST NOT be recorded as a replay outcome. Its route MUST be `RERUN`, and only where running again supersedes the secret the lost answer held; an authority MUST NOT serve a secret-bearing route whose secret a re-run cannot supersede. A secret carried only in the request MUST NOT be recorded either, and does not constrain the route's declaration: the replay state holds the request's hash, never its body.

#### Scenario: A relay token rotation is retried after a later rotation

- **WHEN** an operator rotates a relay's token to one value and loses the acknowledgement, rotates it again to another, and the first rotation's exact retry arrives within the retention
- **THEN** the provisioning service answers the first rotation's recorded outcome, a relay view holding no token, and the relay keeps the later token

#### Scenario: An issuance answer is lost

- **WHEN** a storefront repeats an exact credits issuance whose answer carried a new key's secret and was lost
- **THEN** the issuance runs again, the unused key's secret is rotated, and the first secret no longer authenticates
- **AND** no secret is held in the replay store
