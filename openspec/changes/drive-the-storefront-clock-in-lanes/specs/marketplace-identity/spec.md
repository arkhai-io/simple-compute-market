## ADDED Requirements

### Requirement: Signing and verification read the process time source

Every request and response signer and verifier MUST take its timestamps and its freshness reference from the process time source, so two parties at the same injected instant agree within the skew.

#### Scenario: Two injected parties exchange a signed request

- **WHEN** a harness and a storefront are both injected at 1794822300 and the harness sends a signed request
- **THEN** the request carries timestamp 1794822300 and passes the storefront's freshness check

### Requirement: The time-setting operation is exempt from request freshness

The time-setting operation of a service whose administrator requests are signed, mounted only under injected time, MUST verify its request's signature, administrator principal, operation, method, resource and request-id reservation as every request's, and MUST NOT refuse it for timestamp skew. No other operation MAY be exempt from request freshness. The response MUST be signed at the service's instant after the set.

#### Scenario: The harness advances past the skew

- **WHEN** the harness, already at 1794823200, sends a time-setting request signed at 1794823200 to a storefront at 1794822300
- **THEN** the storefront verifies the signature and principal, moves to 1794823200, and answers signed at 1794823200

#### Scenario: Another operation arrives skewed

- **WHEN** any other administrator request reaches that storefront signed 900 s from its instant
- **THEN** it is refused for timestamp skew

## MODIFIED Requirements

### Requirement: Body-bound authenticated request and response version

Every authenticated state-changing request MUST use `arkhai.market-request-signature.v2`. Its proof MUST cover one domain-separated, length-delimited canonical sequence containing the protocol version, caller role, complete principal, HTTP method, semantic operation, resource identity, request ID, timestamp, and SHA-256 of canonical JSON or the empty body. Authentication headers MUST carry the version, principal scheme and identifier, role, request ID, timestamp, and proof. Behavior-affecting query values MUST be represented in the signed semantic body, and the route boundary MUST supply the expected semantic operation and resource independently of proxy path spelling.

The receiving authority MUST reserve `(principal, request_id)` before dispatch, enforce configured clock skew on first use — on every operation but a time-setting operation mounted under injected time, which "The time-setting operation is exempt from request freshness" governs — and reject changed reuse, missing fields, unsupported versions, or invalid proofs. An exact reuse of the same canonical request MUST resolve to the recorded operation outcome rather than execute a conflicting mutation, except on a route declared credential-capable: such a route MUST record its outcome without access material, and an exact reuse MUST run its read again under current authorization and MAY be refused, while a mutation it carries MUST resume the same domain operation rather than repeat it.

Every response an authority returns on an authenticated route MUST use the shared version 2 response contract to bind its domain, status, originating request identity, authority principal, timestamp, and canonical response body hash. This MUST hold for refusals as well as acknowledgements, and for a refusal raised while authenticating the request as well as one raised after. A caller MUST verify the proof, body, request identity, and exact expected authority before accepting any of them.

An authority MUST NOT withhold response authentication because trust has not been established: the operation and resource it binds are the ones the route derived from the request, and the request identity is the one the caller sent, neither of which depends on the caller being trusted. An answer MAY be unauthenticated only when it cannot be bound to a caller at all — the request carried no request identity, or the route recognized no authenticated contract — and an authority MUST NOT invent either in order to sign.

A refusal body MUST NOT disclose anything the caller has not already proven it holds. Naming which bound field disagreed is disclosure of the authority's expectation, not of a secret, and is permitted.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, request ID, or timestamp change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal and request ID after losing the response
- **THEN** the authority returns or resumes the recorded operation outcome without executing a conflicting mutation

#### Scenario: A credential-capable route is retried after delivery ends

- **WHEN** a buyer repeats an exact request to a credential-capable compute route after the deal's end was admitted
- **THEN** the route runs its read again and refuses disclosure with a response-authenticated refusal
- **AND** the request's reservation stays in force and no earlier response body is returned

#### Scenario: A credential-capable outcome is recorded

- **WHEN** a credential-capable route returns access material
- **THEN** the recorded outcome holds its status and no access material

#### Scenario: An authority returns a mutation acknowledgement

- **WHEN** an authority returns a mutation response for an authenticated request
- **THEN** the caller accepts it only after the status, originating request identity, exact authority principal, timestamp, body, and response proof verify

#### Scenario: An authenticated route refuses a caller

- **WHEN** an authority refuses a request on an authenticated route, whether the refusal is raised while authenticating it or after
- **THEN** the refusal carries response authentication bound to the route's operation and resource, the caller's request identity, the refusal status, and the refusal body, and the caller reads the refusal after verifying it

#### Scenario: A refusal cannot be bound to a caller

- **WHEN** a request carries no request identity, or names no authenticated route contract
- **THEN** the refusal is returned unauthenticated rather than signed against an invented identity or contract

#### Scenario: A valid but unexpected authority signs a response

- **WHEN** another valid principal signs the same response body
- **THEN** verification fails because route and configuration context select a different expected authority

#### Scenario: A supported proof scheme is verified

- **WHEN** the verifier checks an Ed25519 or EIP-191 request or response proof
- **THEN** verification completes locally without a chain node, RPC endpoint, or external identity service

#### Scenario: A request arrives outside the skew

- **WHEN** a signed request on any operation but a time-setting one reaches an authority with a timestamp outside its configured skew
- **THEN** it is refused for timestamp skew before dispatch
