## ADDED Requirements

### Requirement: Bare-metal demand is exact and buyer-bounded

A version-1 bare-metal buyer demand MUST contain exactly lease duration, one access
method supported by the advertised listing, and the method-specific buyer input; SSH
MUST require one syntactically valid public key and MUST reject private-key material.
The buyer MUST NOT submit an `access_ref`, site, Resource Pool, Physical Resource,
physical host, executor machine or provider, seller or claimant, price, condition, or
deadline override, and MUST reject any listing, response, configuration value, or
argument that attempts to make a provisioning URL, site credential, provider
identifier, or direct executor operation authoritative.

#### Scenario: Buyer requests SSH access

- **WHEN** the selected listing supports SSH and the buyer supplies a positive duration within the listing bounds and a valid SSH public key
- **THEN** the buyer emits the canonical `bare_metal.v1` provision envelope with no seller-owned routing or resource fields

#### Scenario: Buyer tries to select a physical host

- **WHEN** buyer input names or changes a site, Physical Resource, physical host, machine, executor, or buyer-issued access reference, or supplies private-key material
- **THEN** demand construction fails before negotiation and no run event or remote mutation records that invalid demand

#### Scenario: Provisioning route is offered to the buyer

- **WHEN** a listing, response, configuration value, or command argument attempts to make a provisioning URL, site credential, provider identifier, or direct executor operation authoritative
- **THEN** the buyer rejects it and uses only the accepted storefront authority and agreement references recorded by the core run

### Requirement: Bare-metal result and evidence decode strictly

The buyer MUST accept only an authority-authenticated, versioned, allowlisted lease
result and portable evidence projection from the recorded storefront. Public result and
evidence MUST NOT contain connection endpoints, usernames, SSH private material,
passwords, bearer tokens, provider or executor details, or raw result payloads, and the
buyer MUST reject a projection carrying any such field or an unrecognized property
rather than display or persist it. Access data returned without a valid response proof
from the exact storefront authority recorded by the run MUST be rejected and neither
revealed, cached, nor used.

#### Scenario: Public evidence contains a credential

- **WHEN** signed evidence includes a password, bearer token, private key, connection endpoint, raw executor result, provider field, or unrecognized property
- **THEN** the buyer rejects the evidence rather than displaying or persisting it

#### Scenario: Access response is signed by another authority

- **WHEN** access data is returned without a valid response proof from the exact storefront authority recorded by the run
- **THEN** the buyer rejects it and does not reveal, cache, or use the data

### Requirement: Buyer teardown is authenticated and idempotent

`market bare-metal teardown --from <run_id>` MUST request teardown from the recorded
storefront for the recorded agreement and exact buyer principal; it MUST NOT invoke
provisioning directly or represent request acceptance as access revocation. Exact
retries MUST return or resume the same teardown operation, and the site MUST release
the Physical Resource's capacity exactly once. Status MUST distinguish requested,
running, complete, failed or operator-action, and lease-already-expired outcomes, and
completion MUST be based on authoritative revocation state. Physical teardown remains
independent from financial reclaim and MUST NOT alter a completed collection.

#### Scenario: Response is lost after teardown acceptance

- **WHEN** the storefront accepts a teardown request but the buyer loses the response
- **THEN** repeating the command for the same run resumes or returns the same operation without issuing a second physical teardown, and capacity is released once

#### Scenario: Teardown is still running

- **WHEN** the physical authority has accepted but not completed revocation
- **THEN** the buyer reports a nonterminal teardown state and does not claim that access is revoked or that capacity is available

#### Scenario: Buyer attempts teardown for another agreement

- **WHEN** the run principal or recorded agreement does not authorize the requested teardown
- **THEN** the storefront response is rejected or authorization fails and the buyer does not retry through another authority
