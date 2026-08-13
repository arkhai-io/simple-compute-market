## ADDED Requirements

### Requirement: Domain-neutral publication hint keys

Resource Pool policy metadata MUST support stable domain-neutral keys for `listing_mode` and `max_reservation_hold_seconds` without defining domain-specific listing-mode values in the shared Resource Pool capability. Unknown policy tags MUST remain forward-compatible opaque metadata.

#### Scenario: Domain interprets listing mode

- **WHEN** VM, bare-metal, or API-credit publication reads a Resource Pool's `listing_mode`
- **THEN** the selected domain validates and interprets the value without adding its enum or default rule to the shared Resource Pool package

#### Scenario: Consumer does not support a hint

- **WHEN** a storefront version does not recognize one projected policy tag
- **THEN** it ignores that tag without rejecting the Resource Pool or changing authoritative admission

### Requirement: Reservation hold preference validation

A Resource Pool management surface that accepts `max_reservation_hold_seconds` MUST require a nonnegative integer and MUST expose the normalized value as advisory metadata rather than an admission rule. This applies to every surface capable of persisting a Resource Pool's `policy_tags`, individually or in bulk — an operator MUST NOT be able to bypass validation by using one surface instead of another.

#### Scenario: Operator supplies an invalid hold preference

- **WHEN** an operator submits a negative, fractional, or nonnumeric hold preference
- **THEN** Resource Pool validation rejects the update without changing the stored policy metadata

#### Scenario: Invalid hold preference submitted through the individual pool admin API

- **WHEN** an operator creates or replaces one Resource Pool through its individual admin endpoint with an invalid `max_reservation_hold_seconds`
- **THEN** the same validation rejects it as the bulk pool-document import path applies, using one shared validator rather than two independently maintained checks
