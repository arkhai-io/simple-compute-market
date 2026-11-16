## ADDED Requirements

### Requirement: Signing and verification read the process time source

Every request and response signer and verifier MUST take its timestamps and its freshness reference from the process time source, so two parties at the same injected instant agree within the skew.

#### Scenario: Two injected parties exchange a signed request

- **WHEN** a harness and a storefront are both injected at 1794822300 and the harness sends a signed request
- **THEN** the request carries timestamp 1794822300 and passes the storefront's freshness check

### Requirement: The time-setting operation is exempt from request freshness

A service's time-setting operation, mounted only under injected time, MUST verify its request's signature, administrator principal, operation, method, resource and request-id reservation as every request's, and MUST NOT refuse it for timestamp skew. No other operation MAY be exempt from request freshness. The response MUST be signed at the service's instant after the set.

#### Scenario: The harness advances past the skew

- **WHEN** the harness, already at 1794823200, sends a time-setting request signed at 1794823200 to a storefront at 1794822300
- **THEN** the storefront verifies the signature and principal, moves to 1794823200, and answers signed at 1794823200

#### Scenario: Another operation arrives skewed

- **WHEN** any other administrator request reaches that storefront signed 900 s from its instant
- **THEN** it is refused for timestamp skew
