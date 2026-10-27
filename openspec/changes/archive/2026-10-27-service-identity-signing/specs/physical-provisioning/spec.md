## ADDED Requirements

### Requirement: Service calls use the shared version 2 identity contract

A provisioning authority MUST authenticate each inbound service request with
the shared `arkhai.market-request-signature.v2` contract and MUST sign each
mutation response with the shared response contract. Verification MUST use the
complete counterparty principal selected by route and authority state, bind the
canonical request or response body, enforce bounded freshness, classify replay
durably, and run locally without a chain or external identity call. Only the
version 2 request and response contracts authenticate the service boundary;
shared credentials, caller-selected expected identities, and unsigned mutation
responses MUST NOT do so.

The authority MUST durably reserve `(principal, request_id)` with the canonical
request digest before dispatch. An exact completed retry MUST return the
recorded status and body under a freshly signed response without repeating the
operation. One caller MAY reclaim an exact unfinished request after its
dispatch lease expires; an in-progress exact retry or reuse with changed signed
content MUST NOT dispatch a second operation.

#### Scenario: An inbound request is authenticated

- **WHEN** a storefront calls a provisioning authority with a correctly signed
  version 2 request
- **THEN** the authority verifies its role, exact registered principal, method,
  semantic operation and resource, request identity, timestamp, and body before
  dispatch

#### Scenario: Request content is changed

- **WHEN** any bound request field or body content is changed after signing
- **THEN** verification fails before the authority performs the operation

#### Scenario: A mutation response is returned

- **WHEN** the authority acknowledges a state-changing request
- **THEN** it signs the status, request identity, authority principal,
  timestamp, and canonical response body, and the caller verifies that exact
  authority before accepting the acknowledgement

#### Scenario: An exact completed request is retried

- **WHEN** a caller repeats the same canonical request with the same principal
  and request identity after losing the acknowledgement
- **THEN** the authority returns the recorded outcome under a fresh signed
  response without dispatching the operation again

#### Scenario: An unfinished request is retried

- **WHEN** an exact retry arrives while the original dispatch lease remains
  active
- **THEN** the authority rejects it as still in progress without dispatching a
  second operation

#### Scenario: A request identity is replayed

- **WHEN** a previously reserved request identity is reused with changed
  content, operation, role, or principal
- **THEN** the authority rejects it as a replay conflict rather than dispatching
  the operation

#### Scenario: Verification runs without external dependencies

- **WHEN** an Ed25519 or EIP-191 signature is verified
- **THEN** verification completes locally without a chain node, RPC endpoint,
  or external identity service

### Requirement: Provisioning role principals are exact and durably registered

The provisioning authority MUST resolve the active complete scheme-tagged
principal set for each required `seller` or `admin` role through its durable
principal-authority registry. Initial configuration MAY seed a role only when
the registry has no binding and MUST NOT overwrite persisted authority state.
The route-selected role and registry-selected principal set MUST determine
authorization; a body field, bare address, URL, provider identifier, or private
credential MUST NOT select or imply authority.

Provisioning clients MUST receive the endpoint and exact expected service
authority principal from registry or composition context independently of
request content. A cryptographically valid response from any other principal
MUST fail verification.

#### Scenario: A configured role seeds an empty registry

- **WHEN** the authority starts without a persisted binding for a supported
  caller role
- **THEN** it records that role's configured complete principal as the first
  authority generation

#### Scenario: Configuration differs from durable authority state

- **WHEN** a persisted role binding already exists and bootstrap configuration
  names another principal
- **THEN** the persisted registry remains authoritative

#### Scenario: A valid unregistered principal calls a route

- **WHEN** a cryptographically valid principal is absent from the active set
  for the route's required role
- **THEN** authorization fails before the handler or any external effect runs

#### Scenario: A different service principal signs a response

- **WHEN** a valid principal other than the client registry's expected
  provisioning authority signs the response
- **THEN** the client rejects the acknowledgement

### Requirement: Provisioning identity credentials and package boundaries are isolated

The provisioning service MUST construct its signer from private credential
material supplied through an approved secret boundary, require that signer to
match its configured public principal, and keep the service signer independent
from storefront and administrator trust principals and optional chain-wallet
credentials. Ordinary configuration, durable authority and replay records,
request and response bodies, logs, manifests, and diagnostics MUST contain only
public principals, trust pins, proofs, and operation metadata, never private
signing material.

Compute provisioning service and client packages MUST consume the shared
identity package's scheme-tagged principals, signer and verifier contracts,
canonical request and response models, replay primitives, and rotation models.
They MUST NOT derive addresses, inspect raw private keys, branch on signature
encoding, or define a second service-signature protocol.

#### Scenario: A wallet-free authority is configured

- **WHEN** the service and its counterparty use Ed25519 principals
- **THEN** authenticated provisioning requests, responses, replay recovery, and
  rotation run without an EVM wallet, RPC endpoint, chain ID, or EVM private key

#### Scenario: EIP-191 is explicitly configured

- **WHEN** a provisioning role uses an EIP-191 principal
- **THEN** the same canonical request and response coverage applies and proof
  verification remains local

#### Scenario: The service credential is loaded

- **WHEN** composition constructs the provisioning authority signer
- **THEN** it consumes the secret-injected credential, verifies that the
  resulting public principal matches configuration, and exposes only the
  signer operation and public principal to orchestration

#### Scenario: Provisioning package boundaries are inspected

- **WHEN** service and client identity dependencies are checked
- **THEN** protocol canonicalization, cryptographic scheme dispatch, replay
  classification, and rotation proof validation resolve from the shared
  identity package rather than provisioning-specific copies

### Requirement: Counterparty principals rotate with dual proof

A provisioning authority MUST rotate a durable role binding only when the
active and replacement principals both sign the same bounded rotation
statement for that stable role subject and authority. It MUST record the
replacement as a new generation, accept both principals only during the
recorded overlap, retire the old principal when the overlap closes, and retain
the rotation audit. Disablement MUST remain distinct from rotation and MUST
remove authority without assigning it to another principal.

#### Scenario: A counterparty rotates its principal

- **WHEN** valid old-principal and replacement-principal proofs authorize a
  bounded overlap
- **THEN** either principal authenticates the same counterparty role until the
  overlap expires or the old principal is explicitly retired

#### Scenario: Replacement proof is absent

- **WHEN** a rotation request names a replacement principal without its proof
  over the same rotation statement
- **THEN** the authority does not bind or promote that principal

#### Scenario: A retired principal is used

- **WHEN** a counterparty signs with a principal whose overlap has ended
- **THEN** the call is rejected

#### Scenario: A counterparty is disabled

- **WHEN** an operator disables a counterparty binding
- **THEN** no principal retains authority, the audit history remains, and the
  operation does not transfer that authority to another principal
