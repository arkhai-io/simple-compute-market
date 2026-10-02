## ADDED Requirements

### Requirement: Accepted-state interpretation has one implementation

Interpreting a domain's accepted state for this mechanism MUST have exactly one
implementation, shared by every composing domain. That interpretation covers
loading the negotiation thread, requiring its terminal state to be success,
validating that the accepted settlement plan carries exactly one obligation,
checking that obligation's mechanism, re-deriving `obligation_ref` from the
agreement and the canonical obligation content and comparing it against the
requested reference, resolving the agreement's origin, and driving the obligation
through its register, materialize, bind, check, and collect sequence. The read an
operator's re-delivery takes MUST apply the same interpretation.

Every one of those steps is a statement about the mechanism's own invariants rather
than about any domain, and the `obligation_ref` re-derivation is a security check:
it is what prevents a reveal against an obligation the accepted plan does not
contain. A security check with several implementations has several behaviours.

A composing domain MUST supply persistence, configuration, and route bindings only,
and MUST NOT carry a copy of that lifecycle logic. Persistence MUST remain injected
through declared callables rather than imported, so the mechanism kit acquires no
web framework, HTTP client, delivery, or foreign-mechanism dependency.

A requested reveal whose re-derived `obligation_ref` does not equal the requested
one MUST be refused, and no contact payload may be returned.

#### Scenario: A second domain composes the mechanism

- **WHEN** a further compute-family storefront composes settlement by introduction
- **THEN** it supplies its persistence reads, configuration, and route bindings
- **AND** it carries no domain-local implementation of accepted-state interpretation,
  origin resolution, or the obligation drive sequence

#### Scenario: A reveal is requested against a mismatched obligation

- **WHEN** a reveal is requested for an obligation reference that does not equal the
  reference re-derived from the agreement and the accepted obligation content
- **THEN** the request is refused and no contact payload is returned

#### Scenario: The mechanism kit's boundary is unchanged

- **WHEN** the mechanism kit's package boundary is checked after composition
- **THEN** it imports no web framework, HTTP client, delivery, or foreign-mechanism
  package

### Requirement: The seller's contact payload is resolved from a listing's origin

The seller's contact payload MUST be resolved from the origin of the listing the
deal was negotiated against, not from one value applied to every origin. A single
storefront may publish listings originating at several seller sites, and a payload
applied to all of them reveals one seller's contact details for another seller's
listing, which is a disclosure of the wrong party's personal information rather
than a missing feature.

The mechanism MUST treat an origin as an opaque identifier it neither parses nor
interprets. A composing domain MUST supply the origin of an agreement from the value
recorded on the negotiation's durable binding, which the negotiation inherits from
its listing, and MUST supply the set of origins it is configured with. Resolution
MUST NOT require a lookup beyond that recorded value.

The seller configuration MUST accept exactly one of two forms: contacts keyed by
origin, or one contact for a storefront configured with exactly one origin. A
storefront MUST refuse to start when both forms are configured, when the single form
is configured while more than one origin is configured, or when a keyed contact
names an origin the storefront is not configured with. A configured origin with no
contact is permitted, and a deployment configured with one origin and the single
form MUST resolve to the value it configures. Every keyed contact MUST be bounded as
the single form is and MUST carry a non-empty payload, and the number of keyed
origins MUST be bounded.

The mechanism's readiness MUST remain storefront-wide. It MUST be unready when no
profiles are configured or when neither form configures any contact, and otherwise
ready: a configured origin without a contact MUST NOT make the mechanism unready.
The public readiness projection MUST NOT disclose which origins have contacts.

A listing whose origin resolves no contact MUST NOT publish a contact-exchange
option. Where contacts are keyed by origin and publication supplies no origin, the
option MUST be refused rather than built. The origin a storefront supplies to
publication MUST be the origin recorded on that listing's durable binding — the
value its negotiation inherits and its reveal resolves — and MUST NOT be derived any
other way, so an option is never advertised under one origin and revealed under
another.

An introduction start whose agreement's origin resolves no contact under the running
configuration MUST be refused with a stable code before any contact payload is
persisted, the obligation is driven, or anything is delivered. It MUST NOT fall back
to another origin's contact or to a storefront-wide value.

Composition MUST remain independent of whether a listing is capacity-backed, in
both directions: a capacity-backed listing MAY settle by introduction, and a
listing with no admission authority behind it is not required to. No pool-level or
listing-level field may name a settlement mechanism.

#### Scenario: Two origins publish through one storefront

- **WHEN** deals are revealed for listings originating at two different seller sites
  behind one storefront, each with its own keyed contact
- **THEN** each reveal carries the contact configured for that listing's origin
- **AND** neither reveal carries the other origin's contact

#### Scenario: A single-origin deployment is unchanged

- **WHEN** a storefront configured with one origin configures the single contact form
- **THEN** resolution yields the contact that deployment already configures

#### Scenario: A single contact is configured for several origins

- **WHEN** a storefront configured with two origins configures the single contact
  form
- **THEN** the storefront refuses to start and names the configured origins

#### Scenario: A keyed contact names an unknown origin

- **WHEN** a keyed contact names an origin the storefront is not configured with
- **THEN** the storefront refuses to start and names the unknown origin

#### Scenario: One origin has a contact and another does not

- **WHEN** contacts are keyed by origin, one configured origin has a contact, and
  another has none
- **THEN** the mechanism reports ready
- **AND** listings from the origin with no contact publish no contact-exchange option

#### Scenario: No contact is configured in either form

- **WHEN** contact exchange is enabled with profiles but no contact in either form
- **THEN** the mechanism reports unready with a stable blocker code

#### Scenario: One origin governs publication, negotiation, and reveal

- **WHEN** a listing is published with a contact-exchange option, negotiated to
  acceptance, and revealed
- **THEN** publication eligibility, the negotiation's binding, and the revealed
  contact all use the origin recorded on the listing's durable binding

#### Scenario: An origin's pools offer an introduction it has no contact for

- **WHEN** a listing's publication clauses select contact exchange and its origin
  resolves no contact
- **THEN** the listing publishes no contact-exchange option

#### Scenario: An origin loses its contact after acceptance

- **WHEN** an introduction start arrives for an accepted deal whose origin no longer
  resolves a contact
- **THEN** the start is refused with a stable code
- **AND** no contact payload is persisted, the obligation is not driven, and nothing
  is delivered

#### Scenario: A capacity-backed listing settles by introduction

- **WHEN** a listing with an admission authority behind it advertises and accepts a
  contact-exchange option
- **THEN** the deal settles by introduction without requiring the listing to be
  unbacked

### Requirement: The mechanism owns the buyer's introduction commands

Starting an introduction from an accepted run, re-reading it, and re-delivering it to
the buyer's own sinks MUST have one implementation, owned by the mechanism as a buyer
command group that every domain buyer whose listings can settle by introduction
mounts. A domain buyer MUST supply only the transport, its run-recovery hook — how a
recorded run is reloaded under that domain's configuration and registry trust — and
its buyer sinks, and MUST NOT carry a copy of the start, read, deleted-outcome, or
delivery handling. The mechanism MUST NOT depend on a core role package or the
delivery capability to provide these commands; both arrive injected.

Negotiating an introduction option opens a negotiation in the domain's own terms, so
each such domain buyer MUST also expose a command that negotiates exactly one
advertised rateless introduction option and records the accepted run in the shared
run log, from which the mechanism's commands recover it.

#### Scenario: A domain buyer mounts the introduction commands

- **WHEN** a domain buyer whose listings can settle by introduction is installed
- **THEN** its command surface offers negotiating an introduction option, starting
  the introduction, and re-reading it with optional re-delivery
- **AND** the start, read, and re-delivery behaviour is the mechanism's implementation

#### Scenario: The storefront deleted the introduction's payloads

- **WHEN** a buyer starts or re-reads an introduction whose payloads the storefront
  deleted, through any domain buyer
- **THEN** the command reports the deleted outcome and exits successfully
- **AND** nothing is delivered

### Requirement: Contact details are public configuration that is never published

A seller's contact payload, in either configuration form, MUST be accepted from any
configuration layer, including a deployment's public configuration, and MUST NOT be
required to arrive through a secret channel. It MUST nonetheless never appear in a
listing, a settlement option, a readiness projection, an obligation, or a log.

#### Scenario: A contact is configured publicly

- **WHEN** an operator configures a seller contact in the storefront's public
  configuration
- **THEN** the storefront accepts it and reveals it only through an authorized
  introduction read
- **AND** no published or public surface contains it
