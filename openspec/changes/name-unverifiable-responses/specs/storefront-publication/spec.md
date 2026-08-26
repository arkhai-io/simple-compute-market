## MODIFIED Requirements

### Requirement: Storefront clients verify signed authority responses

A storefront client MUST verify the shared version 2 response signature, configured authority principal, request identity, status, timestamp, and body before accepting a mutation acknowledgement. Unsigned responses, signatures from another principal, body mutations, stale responses, and request-ID mismatches MUST fail closed.

A refusal for failing authentication MUST identify what was refused. The client
MUST report the HTTP status it received and whether the response carried response
authentication at all,
because a response with no authentication headers is indistinguishable by shape
from an ordinary error answer and the two demand different repairs. The response
body, its headers' values, and any credential MUST NOT appear in that report.

#### Scenario: An authority acknowledges a mutation

- **WHEN** the configured authority returns a valid signed response
- **THEN** the client accepts the response only after every bound field and the exact authority principal verify

#### Scenario: A different authority signs the response

- **WHEN** a valid signer that is not the configured authority signs the same response body
- **THEN** the client rejects the response

#### Scenario: An error answer carries no response authentication

- **WHEN** the client receives a `404`, `403`, or other error answer that carries no response authentication headers
- **THEN** it fails closed and reports the status it received and that the response was unauthenticated, rather than reporting only that the authentication was malformed

#### Scenario: A refusal is reported

- **WHEN** any response is refused for failing authentication
- **THEN** the report names the status and the absence or presence of authentication and contains no part of the response body, no header value, and no credential
