## MODIFIED Requirements

### Requirement: Body-bound authenticated request and response version

Every authenticated request MUST use the `arkhai.market-request.v3` profile of RFC 9421 HTTP Message Signatures, with RFC 9530 `Content-Digest` over the request body bytes. Its signature MUST cover the HTTP method, the content digest, and the covered fields `Market-Role`, `Market-Operation`, `Market-Resource`, `Market-Audience`, `Market-Request-ID` and `Market-Request-Origin`; its `keyid` MUST be the complete principal, its `created` parameter the signing instant, and its `tag` the profile. Behavior-affecting query values MUST be represented in the signed semantic body. The route boundary MUST derive the expected operation and resource from the request independently of proxy path spelling, and the authority MUST refuse a request whose stated operation or resource differs from what the route derives.

`Market-Request-Origin` MUST be the request's first signing instant, unchanged on every retry under the same request ID while each re-signing carries a fresh `created`; it MUST NOT be later than the authority's instant plus the configured skew. `Market-Audience` MUST list the principals the caller would accept the answer from, and an authority MUST accept a request only when its own signing principal is listed. A signed delivery to an endpoint that is not a marketplace authority MUST cover `@target-uri` in place of `Market-Audience`.

The receiving authority MUST reserve `(principal, request_id)` with the request's hash, origin included, before dispatch, enforce configured clock skew on `created` — on every operation but a time-setting operation mounted under injected time, which "The time-setting operation is exempt from request freshness" governs — and reject changed reuse, missing fields, unsupported protocols, or invalid proofs. An exact reuse of the same canonical request MUST resolve as its route declares under "Each route declares how an exact retry is resolved", and MUST NOT execute a conflicting mutation.

Every response an authority returns on an authenticated route MUST use the `arkhai.market-response.v3` profile, covering its status and content digest and, from the request, its method, operation, resource and request ID. This MUST hold for refusals as well as acknowledgements, and for a refusal raised while authenticating the request as well as one raised after, including a request no route serves, signed over the operation, resource and request ID the request states. A caller MUST verify the proof, body, request binding, and exact expected authority before accepting any of them.

An authority MUST NOT withhold response authentication because trust has not been established. An answer MAY be unauthenticated only when the request carried no request identity, and an authority MUST NOT invent one in order to sign.

A refusal body MUST NOT disclose anything the caller has not already proven it holds. Naming which bound field disagreed is disclosure of the authority's expectation, not of a secret, and is permitted; a refusal MUST NOT list the operations an authority serves.

An authority MUST refuse a request under `arkhai.market-request-signature.v2` as an unsupported protocol. Version 2 signed requests and responses retained as evidence MUST remain verifiable.

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

#### Scenario: The route binds another operation

- **WHEN** the route a request reaches derives an operation or resource different from the one the request states
- **THEN** the authority answers a signed 400 whose body code is `operation_mismatch` and names the stated and bound values

#### Scenario: A version 2 request arrives

- **WHEN** a request signed under `arkhai.market-request-signature.v2` reaches an authority
- **THEN** it is refused with a 400 whose body code is `unsupported_protocol` and lists `arkhai.market-request.v3`, signed wherever the request carries a request identity

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

- **WHEN** a signed request on any operation but a time-setting one reaches an authority with a `created` outside its configured skew
- **THEN** it is refused for timestamp skew before dispatch

#### Scenario: A signed webhook delivery is replayed to another receiver

- **WHEN** a signed delivery covering one endpoint's `@target-uri` is sent to a different endpoint
- **THEN** the receiver's verification fails because the covered target is not its own

## ADDED Requirements

### Requirement: Each route declares how an exact retry is resolved

Every authenticated route MUST declare its exact-retry resolution in its route contract: `RERUN`, under which an exact retry runs the handler again and no response body is recorded; `RECORDED`, under which the outcome is kept for the authority's retention and an exact retry is answered with it; or `REFUSE`, under which an exact retry is refused and nothing is recorded. An authority MUST refuse to start when an authenticated route declares none. A concurrent exact retry while the first attempt holds its lease MUST be refused as in progress whatever the route declares, and one attempt MAY reclaim an expired lease. A handler serving an exact retry under `RERUN` MUST be told it is a retry. A route MUST be `RERUN` only where its domain converges, so that a second run changes nothing the first did not and its answer tells the caller what happened; each such mutation MUST be proven by a test that dispatches the same request twice.

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

#### Scenario: A route declares no resolution

- **WHEN** an authority is composed with an authenticated route whose contract declares no exact-retry resolution
- **THEN** the authority refuses to start, naming the route

#### Scenario: An exact retry arrives while the first attempt runs

- **WHEN** an exact retry arrives while the first attempt's lease is held
- **THEN** it is refused as in progress without dispatching a second operation

### Requirement: Replay state is bounded by the request

Every reservation MUST carry an expiry computed from the request alone on the authority's process time source: for a `RERUN` route, its origin plus twice the configured skew; for a `RECORDED` route, its origin plus the greater of the retention plus the skew and twice the skew. An authority MUST delete expired reservations, and MUST NOT keep replay state indefinitely or only in process memory. The retention of recorded outcomes MUST be operator-configurable per authority and MUST default to 24 hours when unset.

On a `RERUN` route a request whose reservation has expired MUST be dispatched as its route declares. On a `RECORDED` route a first use MUST carry an origin within the skew of the authority's instant, and an exact retry whose origin is older than the retention, or whose reservation is gone within it, MUST be answered with a signed `410 Gone` whose body code is `exact_retry_expired`.

#### Scenario: A reservation passes its expiry

- **WHEN** a `RERUN` route's reservation is older than its origin plus twice the skew and another request is reserved
- **THEN** the expired reservation is deleted

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

- **WHEN** an authority restarts between a request and its replay inside the skew
- **THEN** the replay is refused, because its reservation was durable

### Requirement: A secret is never recorded for replay

A response carrying a secret — access material, an API-key secret, a password, a private or staged key, or a token — MUST NOT be recorded as a replay outcome. Its route MUST be `RERUN` where running again supersedes the secret the lost answer held, and `REFUSE` otherwise.

#### Scenario: An issuance answer is lost

- **WHEN** a storefront repeats an exact credits issuance whose answer carried a new key's secret and was lost
- **THEN** the issuance runs again, the unused key's secret is rotated, and the first secret no longer authenticates
- **AND** no secret is held in the replay store
