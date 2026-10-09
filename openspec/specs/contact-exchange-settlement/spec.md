# contact-exchange-settlement Specification

## Purpose
Define settlement by introduction: the `contact-exchange.v1` mechanism completes a deal by
putting buyer and seller durably in authenticated contact, with no payment, no escrow, and
no provisioning, and governs when contact is revealed and how long it is kept.

## Requirements

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

### Requirement: Accepted introductions survive publication disablement

Introduction start and read MUST resolve the persisted accepted Agreement and plan
through its declared seller stage. Current publication enablement MUST NOT gate
accepted reveal or re-read; disabling contact for new work MUST continue to refuse
fresh contact admission.

#### Scenario: Contact is disabled after acceptance

- **WHEN** contact is disabled for new publication after a contact Agreement is
  accepted, with its seller stage and reveal inputs retained
- **THEN** the buyer can start or retry that introduction and both parties can
  re-read its persisted reveal under the same obligation reference, including
  after restart, while new contact negotiation is refused

### Requirement: The agreed context is durable

The accepted plan's `service_terms` and both contact payloads MUST be persisted at or
before completion and MUST NOT be re-derived from mutable negotiation state. The
reveal MUST serve the persisted artifacts.

#### Scenario: Reveal after restart

- **WHEN** the storefront restarts between acceptance and a party's first
  introduction read
- **THEN** the read serves the identical persisted introduction package

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at every ingress (configuration and the
introduction start), MUST be persisted only for deals whose introduction has been
started, and MUST be deletable as part of the deal lifecycle without disturbing the
settled obligation record. A deal that never starts its introduction MUST persist no
contact data.

Deletion MUST remove both parties' contact payloads for one introduction while leaving
the settled obligation record, the deal's terminal state, and the resolvability of its
`obligation_ref` intact. `obligation_ref` is the universal deal-settlement identity
that cross-mechanism status and tooling correlate by, so removing the record to remove
contact data would erase a deal that legitimately happened rather than the personal
details it carried.

#### Scenario: Unstarted deals hold no contact data

- **WHEN** a contact-exchange deal is accepted but neither party starts the
  introduction
- **THEN** no contact payload is persisted for that deal

#### Scenario: Introduction teardown removes the payloads

- **WHEN** an operator removes a revealed introduction at the end of its retention
  window
- **THEN** both contact payloads are deleted while the settled obligation record
  remains

#### Scenario: A deleted deal remains correlatable

- **WHEN** a deal's contact payloads have been deleted
- **THEN** its settled obligation record and terminal state remain
- **AND** the deal still resolves and correlates by its `obligation_ref`

### Requirement: Deleting contact payloads leaves a tombstone

Deleting an introduction's contact payloads MUST redact them in place rather than
remove the introduction: the persisted introduction MUST record when its payloads were
deleted, MUST hold neither party's contact payload afterwards, and MUST keep the agreed
introduction context. Redaction MUST be atomic, so a concurrent read observes either
the complete introduction or the redacted one and never a partial record.

The fact that an introduction was revealed is what prevents it being revealed again,
so a revealed introduction's persisted record MUST NOT be removed while its payloads
are present. A revealed introduction MUST be changed at most once after it is
persisted, and only by that redaction; redaction MUST NOT be reversible. A storefront
MUST enforce both in its persistence rather than relying on callers.

Redaction MUST be idempotent. Redacting an already-redacted introduction, or a deal
that never started its introduction, MUST converge rather than fail.

After redaction, a storefront MUST NOT return either party's contact payload for that
introduction from its introduction record:

- an authenticated read MUST answer with a stable deleted outcome that states when the
  payloads were deleted;
- an introduction start that finds the payloads deleted, whether when it reads the
  introduction or when it persists one, MUST still drive the deal's obligation to its
  terminal state, then answer the same deleted outcome, and MUST NOT persist contact
  data or deliver the introduction;
- the reveal projection MUST refuse to render a redacted introduction.

An introduction is revealed when it is persisted, and a reveal and a deletion are
ordered by that moment. A start that persisted, or found persisted, the complete
introduction before a deletion committed is a reveal that preceded the deletion: it
MAY complete, answer the reveal, and deliver it, even if the deletion commits while it
is still in progress. Deletion bounds what the storefront holds from the moment it
commits; it does not recall a reveal already made, just as it does not recall copies
already delivered to either side's sinks.

#### Scenario: Deletion is repeated

- **WHEN** deletion is invoked for an introduction whose payloads are already deleted,
  or for a deal that never started its introduction
- **THEN** the operation converges without failing

#### Scenario: A read arrives after deletion

- **WHEN** an authenticated party reads an introduction whose payloads have been
  deleted, including where the read interleaves with the deletion
- **THEN** it receives either the complete introduction or the deleted outcome, and
  never a partially populated introduction

#### Scenario: A buyer starts a deleted introduction again

- **WHEN** a buyer sends an introduction start, under a new request identity, for a
  deal whose payloads have been deleted
- **THEN** the storefront answers the deleted outcome
- **AND** no contact payload is persisted and the seller receives no delivery

#### Scenario: A deletion overlaps a start that has already revealed

- **WHEN** an introduction start has persisted the complete introduction and is still
  completing the deal's obligation when a deletion of its payloads commits
- **THEN** the start completes and answers the reveal, and delivers it if it is the
  first reveal
- **AND** every later read or start answers the deleted outcome

#### Scenario: A deleted introduction cannot be restored or removed

- **WHEN** any code path attempts to restore a redacted introduction's payloads, or to
  remove an unredacted introduction's record
- **THEN** the storefront's persistence refuses the change

### Requirement: Contact payloads are retained for a configured window

The contact-exchange mechanism's seller configuration MUST carry a retention window,
defaulting to 30 days. The window MUST be either a positive duration or an explicit
`indefinite`, which MUST cause no deletion; a zero window MUST be refused. An operator
wanting unbounded retention therefore says so rather than relying on an absent policy.

The window MUST be applied as an aggregate policy over the storefront's holdings,
read from the running configuration wherever it is used. It MUST NOT be recorded per
introduction and enforced from the recorded value: retention is not a term agreed with
a counterparty, and a pinned window would exempt exactly the introductions an operator
shortening the policy most needs to remove. Configuring a finite window is the
operator's consent to delete existing payloads past it.

An introduction MUST become eligible for deletion when the time since it was revealed
reaches the window.

Deletion MUST be reachable both through a scheduled sweep over eligible introductions
and through an operator-invoked deletion of one introduction, and both MUST invoke one
shared deletion operation. The scheduled sweep MUST be a storefront lifecycle loop that
the lifecycle pause holds and an operator can step, and an operator MUST be able to
preview what its next cycle would delete without deleting anything.

A preview reports the introductions eligible when it is taken. Eligibility only grows
with time, so the next cycle MUST delete every previewed introduction whose payloads
are still present, and MAY also delete introductions that became eligible after the
preview. A cycle bounded to a batch MUST select the longest-revealed introductions
first, so a previewed introduction is never displaced by one that became eligible
later.

Every storefront that composes the mechanism MUST run the sweep, MUST serve the
operator-invoked deletion, and MUST serve both disclosures this capability requires.

#### Scenario: The window is shortened after a reveal

- **WHEN** an operator restarts a storefront with a retention window shorter than the
  age of an already-revealed introduction
- **THEN** the next sweep deletes that introduction's payloads
- **AND** no window recorded at reveal exempts it

#### Scenario: The window is indefinite

- **WHEN** a storefront's retention window is `indefinite`
- **THEN** payloads are retained and the sweep deletes nothing

#### Scenario: A zero window is configured

- **WHEN** a storefront is configured with a zero retention window
- **THEN** the configuration is refused

#### Scenario: Both invocation paths share one operation

- **WHEN** an operator deletes one introduction and the scheduled sweep deletes another
- **THEN** both remove the payloads through the same deletion operation

#### Scenario: An operator previews and steps the sweep

- **WHEN** the lifecycle loops are held and an operator previews the retention sweep,
  then runs one cycle of it
- **THEN** the preview reports the eligible introductions without deleting them
- **AND** the cycle deletes the payloads of every previewed introduction not deleted
  in the meantime, together with any that became eligible after the preview

#### Scenario: A storefront composes the mechanism

- **WHEN** a storefront composes `contact-exchange.v1`
- **THEN** it runs the retention sweep and serves the operator deletion and both
  disclosures

### Requirement: The retention window is disclosed before commitment and at reveal

The effective window MUST be readable from the storefront's public readiness
projection, without authentication, before a buyer commits contact data. The buyer's
payload accompanies the introduction start, so a window disclosed only at reveal is
disclosed after the point a party could decline. The window MUST additionally be
disclosed in the projection that carries the reveal. Both disclosures MUST read the
same running configuration, so they cannot disagree, and MUST be present only when the
mechanism is enabled.

Both disclosures MUST carry the window as a machine-readable value, stating an
`indefinite` window explicitly, and MUST state that it is current storefront policy
rather than a commitment, and that it governs the storefront's introduction record.
The operator may change the window or remove a payload at any time, and copies each
side delivered to its own configured sinks, or holds in its own tooling, are outside
what the introduction record governs. A disclosure MUST NOT state or imply that it
covers any copy other than the introduction record; one that did would be a false
claim about where the data is and who controls it.

#### Scenario: A buyer reads the window before negotiating

- **WHEN** a buyer queries a storefront's readiness projection before starting an
  introduction
- **THEN** the effective retention window is readable without authentication
- **AND** it is the same value the reveal projection discloses

#### Scenario: The window is disclosed at reveal

- **WHEN** a party reads a revealed introduction
- **THEN** the projection carrying the reveal also carries the effective retention
  window
- **AND** the disclosure states current storefront policy rather than a commitment
- **AND** it is scoped to the introduction record and does not state or imply that
  any other copy, including one already delivered to a configured sink, is covered

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
