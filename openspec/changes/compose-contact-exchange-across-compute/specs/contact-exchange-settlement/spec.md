## ADDED Requirements

### Requirement: Accepted-state interpretation has one implementation

Interpreting a domain's accepted state for this mechanism MUST have exactly one
implementation, shared by every composing domain. That interpretation covers
loading the negotiation thread, requiring its terminal state to be success,
validating that the accepted settlement plan carries exactly one obligation,
checking that obligation's mechanism, re-deriving `obligation_ref` from the
agreement and the canonical obligation content and comparing it against the
requested reference, and driving the obligation through its register, materialize,
bind, check, and collect sequence.

Every one of those steps is a statement about the mechanism's own invariants rather
than about any domain, and the `obligation_ref` re-derivation is a security check:
it is what prevents a reveal against an obligation the accepted plan does not
contain. A security check with several implementations has several behaviours.

A composing domain MUST supply persistence and configured values only, and MUST NOT
carry a copy of that lifecycle logic. Persistence MUST remain injected through the
callback contract rather than imported, so the mechanism kit acquires no
persistence, framework, or delivery dependency.

A requested reveal whose re-derived `obligation_ref` does not equal the requested
one MUST be refused, and no contact payload may be returned.

#### Scenario: A second domain composes the mechanism

- **WHEN** a further compute-family storefront composes settlement by introduction
- **THEN** it supplies its persistence client and configured values
- **AND** it carries no domain-local implementation of accepted-state interpretation
  or the obligation drive sequence

#### Scenario: A reveal is requested against a mismatched obligation

- **WHEN** a reveal is requested for an obligation reference that does not equal the
  reference re-derived from the agreement and the accepted obligation content
- **THEN** the request is refused and no contact payload is returned

#### Scenario: The mechanism kit's boundary is unchanged

- **WHEN** the mechanism kit's package boundary is checked after composition
- **THEN** it imports no persistence, web framework, HTTP client, or delivery
  package

### Requirement: The seller's contact payload is resolved from a listing's origin

The seller's contact payload MUST be resolved from the origin of the listing the
deal was negotiated against, not from one static storefront-wide value. A single
storefront may publish listings originating at several seller sites, and a
storefront-wide payload in that deployment does not degrade gracefully: it reveals
one seller's contact details for another seller's listing, which is a disclosure of
the wrong party's personal information rather than a missing feature.

The origin is already recorded on the durable listing binding and copied to the
negotiation thread, so resolution MUST use that recorded value and MUST NOT require
a new lookup at acceptance. A deployment with one origin MUST resolve to the value
it configures today.

Where a listing's origin has no configured payload, acceptance MUST be refused
rather than falling back to another origin's payload or to a storefront-wide
default.

Composition MUST remain independent of whether a listing is capacity-backed, in
both directions: a capacity-backed listing MAY settle by introduction, and a
listing with no admission authority behind it is not required to. No pool-level or
listing-level field may name a settlement mechanism.

#### Scenario: Two origins publish through one storefront

- **WHEN** deals are accepted against listings originating at two different seller
  sites behind one storefront
- **THEN** each reveal carries the payload configured for that listing's origin
- **AND** neither reveal carries the other origin's payload

#### Scenario: An origin has no configured payload

- **WHEN** a deal is accepted against a listing whose origin has no configured
  contact payload
- **THEN** acceptance is refused rather than revealing a fallback payload

#### Scenario: A single-origin deployment is unchanged

- **WHEN** a storefront publishes listings from one origin only
- **THEN** resolution yields the payload that deployment already configures

#### Scenario: A capacity-backed listing settles by introduction

- **WHEN** a listing with an admission authority behind it advertises and accepts a
  contact-exchange option
- **THEN** the deal settles by introduction without requiring the listing to be
  unbacked
