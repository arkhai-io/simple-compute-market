## ADDED Requirements

### Requirement: An introduction completes a deal

Under the `contact-exchange.v1` mechanism, a deal MUST complete with no payment and no
provisioning: the accepted plan carries one non-financial obligation whose
materialization is immediately ready, and the deal MUST reach a terminal settled state
once the reveal is available to both parties, independent of whether either party has
read it.

#### Scenario: A contact-exchange deal settles

- **WHEN** a negotiation under the contact-exchange mechanism is accepted
- **THEN** the deal reaches a terminal settled state without an escrow, a funding
  authorization, a chain client, or a fulfillment capability being involved

### Requirement: Contact is revealed only after acceptance, only to the counterparty

Contact payloads MUST NOT appear in listings, options, or discovery responses. After
acceptance, each party MUST be able to read the counterparty's contact payload and the
agreed context through the authenticated introductions surface, the read MUST be
idempotent, and no other principal may read either payload.

#### Scenario: Counterparty reads the introduction

- **WHEN** an authenticated party to an accepted contact-exchange deal requests its
  introduction
- **THEN** it receives the counterparty's contact payload and the agreed negotiated
  context, and an identical repeat request returns the same result

#### Scenario: A non-party requests the introduction

- **WHEN** a principal that is not a party to the deal requests the reveal
- **THEN** the request is refused and no contact data is returned

### Requirement: The agreed context is durable

The accepted plan's `service_terms` and both contact payloads MUST be persisted at or
before completion and MUST NOT be re-derived from mutable negotiation state. The
reveal MUST serve the persisted artifacts.

#### Scenario: Reveal after restart

- **WHEN** the storefront restarts between acceptance and a party's first
  introduction read
- **THEN** the read serves the identical persisted introduction package
