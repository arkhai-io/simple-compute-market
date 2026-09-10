## ADDED Requirements

### Requirement: A mechanism builds the accepted obligation it advertised

A mechanism whose options can be exactly selected MUST supply the accepted
obligation builder for its own registration; a domain MUST NOT construct an
obligation for a mechanism it composed, and a selection naming a mechanism with
no builder MUST be refused before any negotiation, obligation or capacity record
is written.

The builder MUST derive the obligation through the same materialization the
counterparty re-derives it from, so the funded payload is one derivation rather
than two implementations that can drift. Acceptance inputs the option cannot
carry — the counterparty-chosen expiry, the negotiated duration, the domain's own
option parameters and the seller's published demands — are supplied by the domain
as acceptance context, and the seller's injected settlement resources travel with
it so a mechanism that materializes against a chain accepts using the same
address book and payout wallet it published from. The domain MUST NOT read the
resulting mechanism parameters.

The mechanism codec MUST also own decoding of its accepted obligation into the
typed terms used for funding and verification. For an accepted Alkahest scalar
token obligation, that decoder MUST preserve the exact obligation data and
expiry, reject disagreement between the top-level and funded amount or between
the asset and funded token, and reject malformed chain, contract, arbiter,
demand or unsupported declared-condition carriers before an external read or
write. This projection is an in-process view of the existing accepted
obligation; it MUST NOT introduce another accepted-plan or wire representation.

#### Scenario: An advertised on-chain option is exactly selected

- **WHEN** a buyer selects an option advertising an accepted escrow and no expiry,
  supplying its own expiry and the lease duration
- **THEN** the mechanism scales the advertised rate by that duration and returns one
  obligation whose nested materialized payload equals what the buyer re-derives
  from the same advertised entry

#### Scenario: A selected mechanism builds no accepted obligation

- **WHEN** a selection names a composed mechanism that supplies no accepted
  obligation builder
- **THEN** the request is refused and no negotiation, obligation or capacity record
  is written

#### Scenario: An accepted Alkahest amount carrier disagrees

- **WHEN** an accepted Alkahest obligation's top-level amount or asset differs
  from the amount or token in its funded obligation data
- **THEN** mechanism decoding fails before funding, chain verification or
  settlement persistence

### Requirement: An exactly selected agreement settles against its accepted obligation

Settlement of an exactly selected agreement MUST verify the funded mechanism
state against the immutable accepted obligation that agreement committed, never
against the listing's current advertised terms: a listing may be republished
under the same identity, so its advertised terms are not the financial authority
for an agreement already accepted. The accepted obligation MUST NOT be rebuilt at
settlement, and no accepted record may be rewritten to make verification pass.

The accepted plan is that authority only while it still agrees with the rest of
the committed record. For a bare-metal agreement settled through the Alkahest
escrow rail — the path this contract is written for, and the only one that
implements it — settlement MUST refuse, before any mechanism read or any write,
an agreement whose plan does not carry exactly one Alkahest obligation, whose
declared parties, obligation roles or principals differ from the negotiation's,
whose amount, asset or mechanism payload disagrees with the committed agreement,
whose declared conditions the mechanism does not verify, whose selected option is
not the one the plan settles, or whose physical facts — provision terms and the
binding restating them — differ from the committed domain terms artifact and
listing. A value an opaque mechanism carrier holds in an unreadable form MUST be
refused the same way rather than raised as a fault. Other domains and mechanisms
keep their own plan shapes, including plans carrying several obligations; this
requirement places no restriction on them.

Where a mechanism verifies against an external system, the accepted obligation
MUST be carried into that verification whole, including the accepted expiry that
fixes the collect-versus-reclaim boundary. A verification interface that accepts
an expected payload without its expiry leaves that boundary unpinned, and an
otherwise matching state with a different deadline MUST NOT settle.

An Alkahest seller MUST obtain the verifier proposal, exact obligation data and
expiry from the mechanism-owned accepted-term projection. Domain validation of
parties, roles, selection identity and physical terms remains mandatory and
MUST run before chain access. A later listing refresh MUST NOT replace any of
those accepted payment inputs.

#### Scenario: A funded escrow carries a different deadline

- **WHEN** the funded escrow matches the accepted obligation payload but its
  expiry is not the accepted one, earlier or later and still in the future
- **THEN** verification fails and nothing is adopted or recorded

#### Scenario: An accepted bare-metal record disagrees with itself

- **WHEN** a bare-metal Alkahest plan's parties, roles, amount, asset, conditions,
  selected option, physical binding or physical terms differ from the committed
  thread and domain artifacts, or an opaque carrier holds an unreadable value
- **THEN** settlement is refused with a settlement error before any mechanism read
  or write

### Requirement: A domain buyer drives every rail its seller publishes

A seller composition that installs several mechanism registrations publishes an
option per ready mechanism from one publication round. The buyer for that domain
SHALL resolve the rail from the option the buyer selected, and SHALL NOT assume
one mechanism's option shape when reading another's.

Mechanism-specific acceptance validation remains mechanism-specific. A buyer that
supplies `validate_advertised_plan` to the shared negotiation client replaces the
shared `params`/`conditions` equality check for that agreement, so the callback
SHALL verify the financial and collection semantics it displaced — at minimum the
escrow target, chain, funded asset, and collection conditions — against the
buyer's own proposal. It SHALL NOT restate the principal, amount, expiry, asset
or mechanism checks the shared client already performs.

#### Scenario: A published option is selectable on either rail
- **WHEN** one publication advertises both an on-chain and a hosted option
- **THEN** the selected `option_id` decides which rail the buyer drives
- **AND** an option naming a mechanism the buyer cannot drive is refused by name

#### Scenario: An advertised escrow entry carries no expiry
- **WHEN** a buyer selects an on-chain option
- **THEN** the escrow expiry is the buyer's own chosen instant
- **AND** it is not read from the advertised entry, which does not carry one

#### Scenario: A substituted plan is refused before funding
- **WHEN** an accepted plan differs in any part of its funded obligation from
  the one the buyer's proposal derives
- **THEN** acceptance fails and no escrow is created

The comparison SHALL be against the mechanism's own canonical materialization of
the buyer's proposal, not an enumerated list of fields. A mechanism that encodes
terms inside a funded payload — an arbiter or payee within the obligation data —
would otherwise pass a top-level check while funding different terms.

For Alkahest, payout decoding and whole-obligation re-materialization SHALL be
owned by the Alkahest codec and shared by acceptance and funding consumers. The
buyer SHALL fund the exact accepted obligation data and expiry returned by that
codec; it SHALL NOT reconstruct a second mechanism payload in domain code.

Where the buyer cannot derive a value from its own proposal, such as the address
the seller will be paid at when the listing advertises none, the specification
SHALL record that as an unpinned input rather than implying it is verified.

The value re-derived from SHALL be the accepted obligation's negotiated absolute
total, which the shared client has already required to equal the negotiated
amount before delegating. An advertised rate is per unit and is not that total
for any rental of a different length; a mechanism callback SHALL NOT validate
against the advertised rate, and SHALL NOT introduce its own scaling or rounding
of it.

#### Scenario: A rental shorter than one rate unit
- **WHEN** an hourly option is accepted for a fraction of an hour
- **THEN** the accepted plan settles at the scaled negotiated total
- **AND** an accepted plan carrying the unscaled hourly rate is refused

### Requirement: Negotiation is not purchase

An accepted agreement SHALL NOT be treated as a completed purchase. For an
on-chain rail the buyer SHALL create the accepted obligation's escrow, obtain the
seller's authoritative verification of it, and begin fulfillment, before any
capacity is reserved or any delivery view is read.

The escrow's identity SHALL be recorded before verification is requested, so that
an escrow which exists on chain but was never verified remains reclaimable.

#### Scenario: A resumed run adopts its escrow
- **WHEN** a settlement run is repeated with an already-funded escrow reference
- **THEN** that escrow is verified and begun
- **AND** no second escrow is created

A domain buy command records its run in the shared run log: the run's opening
inputs, the accepted agreement, and the run's end. The opening record carries the
registry the listing was read from, that registry's authority, the listing, its
storefront, and the publisher principals the listing was signed under, so the
purchased agreement is bound to an authenticated discovery. A consumer of that
log SHALL assert the events the command emits; it SHALL NOT depend on names no
producer writes.

Beginning fulfillment is not delivery. The buyer-visible physical projection
reports its own state, and the delivery and access views are meaningful only once
that state is active, so a consumer SHALL wait on the projection rather than read
those views when the settlement command returns.

#### Scenario: The purchased listing came from the configured registry
- **WHEN** a run's opening record names another registry, another authority, or
  carries no publisher principals
- **THEN** the run is not accepted as evidence of authenticated discovery
