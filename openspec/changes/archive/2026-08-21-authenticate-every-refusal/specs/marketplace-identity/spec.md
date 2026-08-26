## MODIFIED Requirements

### Requirement: Body-bound authenticated request and response version

Every authenticated state-changing request MUST use `arkhai.market-request-signature.v2`. Its proof MUST cover one domain-separated, length-delimited canonical sequence containing the protocol version, caller role, complete principal, HTTP method, semantic operation, resource identity, request ID, timestamp, and SHA-256 of canonical JSON or the empty body. Authentication headers MUST carry the version, principal scheme and identifier, role, request ID, timestamp, and proof. Behavior-affecting query values MUST be represented in the signed semantic body, and the route boundary MUST supply the expected semantic operation and resource independently of proxy path spelling.

The receiving authority MUST reserve `(principal, request_id)` before dispatch, enforce configured clock skew on first use, and reject changed reuse, missing fields, unsupported versions, or invalid proofs. An exact reuse of the same canonical request MUST resolve to the recorded operation outcome rather than execute a conflicting mutation.

Every response an authority returns on an authenticated route MUST use the shared version 2 response contract to bind its domain, status, originating request identity, authority principal, timestamp, and canonical response body hash. This MUST hold for refusals as well as acknowledgements, and for a refusal raised while authenticating the request as well as one raised after. A caller MUST verify the proof, body, request identity, and exact expected authority before accepting any of them.

An authority MUST NOT withhold response authentication because trust has not been established: the operation and resource it binds are the ones the route derived from the request, and the request identity is the one the caller sent, neither of which depends on the caller being trusted. An answer MAY be unauthenticated only when it cannot be bound to a caller at all — the request carried no request identity, or the route recognized no authenticated contract — and an authority MUST NOT invent either in order to sign.

A refusal body MUST NOT disclose anything the caller has not already proven it holds. Naming which bound field disagreed is disclosure of the authority's expectation, not of a secret, and is permitted.

#### Scenario: Signed body is changed

- **WHEN** a valid proof is replayed with any body, role, principal, operation, resource, request ID, or timestamp change
- **THEN** authentication fails and no handler, database mutation, or external effect runs

#### Scenario: Exact retry follows uncertain acknowledgement

- **WHEN** a client repeats the exact request with the same principal and request ID after losing the response
- **THEN** the authority returns or resumes the recorded operation outcome without executing a conflicting mutation

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
