## ADDED Requirements

### Requirement: Complete bare-metal seller lifecycle

A bare-metal storefront MUST interpret bare-metal listings, messages, agreed terms, settlement materialization, receipts, and access results only through its injected domain contract. It MUST translate an accepted agreement into scheduling and fulfillment at the provisioning site selected by the Capacity Reservation and MUST reclaim through the recorded fulfillment and executor identity.

#### Scenario: Bare-metal agreement is fulfilled

- **WHEN** a buyer and bare-metal storefront accept valid terms and settlement is verified
- **THEN** the storefront schedules exclusive capacity at the reservation's selected site, starts bare-metal fulfillment, and exposes a normalized bare-metal receipt and result without using VM models

#### Scenario: Bare-metal request fails domain validation

- **WHEN** a listing, message, terms payload, or result violates the bare-metal domain schema
- **THEN** the storefront rejects that payload without coercing it through VM semantics or a generic fallback

#### Scenario: Bare-metal agreement is torn down

- **WHEN** an operator or lifecycle transition ends a fulfilled bare-metal agreement
- **THEN** the storefront requests teardown through the recorded fulfillment and bare-metal executor identity and does not release capacity until authoritative teardown policy permits it

### Requirement: Trusted selected-site routing

A bare-metal storefront MUST bind each configured `site_id` to an operator-trusted provisioning connection. Reservation, fulfillment, result polling, and teardown MUST use the site selected before reservation rather than a process-global default or routing data supplied by a buyer.

#### Scenario: One storefront uses several provisioning sites

- **WHEN** configured placement reserves bare-metal capacity at one of several eligible sites
- **THEN** every state-changing lifecycle call for that agreement routes to the selected site's trusted connection

#### Scenario: Agreement payload contains routing material

- **WHEN** buyer-controlled or opaque agreement data contains a provisioning URL, credential, or conflicting site assertion
- **THEN** the storefront ignores it for authority selection and uses its configured site binding
