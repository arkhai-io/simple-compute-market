## ADDED Requirements

### Requirement: Storefronts hold an exact principal per site authority

A storefront MUST resolve each site authority's site identifier, URL, and
scheme-tagged principal through a registry interface. It MUST verify
authority-originated version 2 requests and responses against the exact
principal selected by site and route context. The registry MUST NOT use an
address-only field, derive a principal from private material, or accept a
caller-selected expected principal.

#### Scenario: An authority-originated request arrives

- **WHEN** a site authority calls a storefront
- **THEN** the storefront verifies the body-bound request against that site's
  registered role and principal before route dispatch

#### Scenario: A storefront uses several sites

- **WHEN** a storefront aggregates several site authorities
- **THEN** each site has a separate principal and a principal registered for one
  site does not authenticate another

#### Scenario: The registry source changes

- **WHEN** site records move from configuration to durable storage
- **THEN** consumers of the registry are unchanged

#### Scenario: A wallet-free site is configured

- **WHEN** a site authority uses an Ed25519 principal
- **THEN** the storefront authenticates it without a wallet, RPC endpoint,
  chain ID, or EVM private key

### Requirement: Storefront clients verify signed authority responses

A storefront client MUST verify the shared version 2 response signature,
configured authority principal, request identity, status, timestamp, and body
before accepting a mutation acknowledgement. Unsigned responses, signatures
from another principal, body mutations, stale responses, and request-ID
mismatches MUST fail closed.

#### Scenario: An authority acknowledges a mutation

- **WHEN** the configured authority returns a valid signed response
- **THEN** the client accepts the response only after every bound field and the
  exact authority principal verify

#### Scenario: A different authority signs the response

- **WHEN** a valid signer that is not the configured authority signs the same
  response body
- **THEN** the client rejects the response

### Requirement: Site authority principals rotate with bounded overlap

A storefront MUST require proofs from both the active and replacement
principals over the same bounded rotation statement. It MUST accept both only
during the recorded overlap and MUST reject the old principal after expiry or
explicit retirement.

#### Scenario: Rotation overlap is active

- **WHEN** both principal proofs are valid and the overlap has not ended
- **THEN** either principal authenticates that site authority

#### Scenario: Rotation overlap has ended

- **WHEN** the old principal signs after overlap expiry or retirement
- **THEN** the storefront rejects it
