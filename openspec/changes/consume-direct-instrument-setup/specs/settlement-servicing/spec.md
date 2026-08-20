## MODIFIED Requirements

### Requirement: Hosted client owns hosted identity wire

The hosted settlement adapter and payer/authorization consumer MUST pass the selected or recorded persistent marketplace signer through the exact manifest-pinned hosted client identity interface and MUST NOT duplicate hosted canonicalization, headers, scheme implementations, response verification, payer/profile models, authorization encoding, setup/confirmation behavior, setup verification behavior, or provider models.

Where the marketplace consumes a hosted operation the pinned client does not expose, it MUST NOT reach the authority by another route. Constructing the request, signing it, or verifying its response outside the pinned client's own interface MUST be refused, and the operation MUST be reported as unavailable under the bound release.

#### Scenario: Hosted release lacks the required identity capability

- **WHEN** buyer/storefront startup or publication preflight sees a hosted manifest that does not advertise the configured principal, payer, authorization, and funding-profile contract versions
- **THEN** hosted settlement remains unavailable and no fiat option or funding authorization is created

#### Scenario: A hosted operation is absent from the pinned client

- **WHEN** the marketplace needs a hosted operation that the pinned client interface does not expose
- **THEN** the operation is reported as unavailable under the bound release, and no hand-built request, signature, or response verification is used in its place
