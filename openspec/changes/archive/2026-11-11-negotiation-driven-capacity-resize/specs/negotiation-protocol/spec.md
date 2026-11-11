## ADDED Requirements

### Requirement: Seller feasibility precedes pricing

Before pricing a requested capacity shape, a seller policy MUST evaluate that shape
against every dimension it constrains, quantitatively as well as categorically. A
policy MUST NOT price a shape it has already determined it will not serve.

#### Scenario: Requested shape exceeds a quantitative constraint

- **WHEN** a requested shape exceeds a seller constraint on a quantitative dimension
- **THEN** the seller declines on that basis rather than quoting a price for it

#### Scenario: Requested shape fails a categorical constraint

- **WHEN** a requested shape names a categorical attribute the seller does not offer
- **THEN** the seller declines without pricing

### Requirement: Rate-multiplier negotiation

Where a domain's offering carries a resolvable rate structure, the quantity negotiated
between the parties MUST be a multiplier over the offering's advertised minimum rate
structure rather than an absolute amount for one shape. The multiplier MUST be carried
as an integer in basis points (10,000 is the advertised minimum), and the storefront
MUST record it as the negotiation's negotiated scalar, never under a name that reads
as a price or an amount. The quote for a shape MUST be the selected settlement
option's advertised rate scaled by the ratio of the requested shape's composed price
to the advertised shape's, so the family rates set only that ratio, and then by the
multiplier. Every amount derived from it MUST be computed in exact integer or decimal
arithmetic, rounded upward to the asset's base unit once, and refused rather than
truncated when it exceeds the asset's amount type. A round's concession MUST remain
comparable to the previous round's when the requested capacity shape differs between
them. A seller's commercial floor MUST be expressible once, as a bound on the
multiplier of at most 10,000, and apply to every admissible shape without per-shape
restatement. The quote for a round is derived by each party from the advertised rate
structure and the round's shape and multiplier; it is not carried on the wire.

A buyer reads the rate structure from the registry's listing, authenticated by the
seller's publication. The seller MUST price and pin a negotiation from its most
recent successful registry publication, the rates the buyer read, not from its own
stored listing record. At opening, the seller MUST persist the digest of that rate
structure. A later round or acceptance MUST be refused with the distinct reason
`rate_structure_changed_reopen` if the published structure changed, even when the
advertised shape's composed total is unchanged; a thread with no pin MUST be refused
the same way. A republication no registry accepted changes nothing a negotiation
reads. Where the seller's registries last accepted different rate structures, the
seller MUST refuse openings, rounds and acceptances distinctly until they converge,
and a shape-priced listing no registry has accepted a publication of MUST take no
opening. A registry holding a publication record of a shape-priced listing but
no retained accepted payload counts as holding a different rate structure while
another registry's is known. The buyer may still exit the negotiation.

A buyer MUST refuse an acceptance whose derived payment exceeds its own monetary
ceiling. A price the buyer derives rather than states MUST price the shape it opens
with, not the listing's advertised shape. Settlement MUST read money only from the
Agreement and its bound mandate, never from the negotiated scalar.

#### Scenario: Family rates change without changing the advertised total

- **WHEN** family rates change after opening so the listing's own total is unchanged
  but a revised shape would have a different price
- **THEN** a continuation or acceptance is refused as `rate_structure_changed_reopen`
  and the buyer must reopen against the new listing

#### Scenario: Requested shape changes between rounds

- **WHEN** a counterparty changes the requested capacity shape between two rounds
- **THEN** the negotiated multiplier remains the axis of comparison, and prior
  concessions are not discarded or re-anchored because the shape changed

#### Scenario: Seller floor applies to an unanticipated shape

- **WHEN** a shape the seller never explicitly priced is requested
- **THEN** the seller's multiplier floor applies to it without a per-shape floor being
  configured

#### Scenario: Agreed terms are recorded

- **WHEN** a negotiation concludes successfully
- **THEN** the recorded terms determine one price, derivable from the agreed multiplier,
  the agreed shape, and the advertised rate structure

#### Scenario: A quote exceeds the asset's amount type

- **WHEN** evaluating a shape at a multiplier would produce an amount the settlement
  asset cannot represent
- **THEN** the round is refused with that reason and no truncated amount is proposed

#### Scenario: A smaller shape is quoted by the composed-price ratio

- **WHEN** a selected option advertises a rate for the listing's shape and the
  requested shape's composed price is half the advertised shape's
- **THEN** the quote at 10,000 basis points is half what the option's rate charges for
  the same duration, rounded upward once

#### Scenario: A seller configures a floor above the advertised rates

- **WHEN** a seller configures a multiplier floor above 10,000
- **THEN** the storefront refuses the configuration at load

#### Scenario: A republication fails during a negotiation

- **WHEN** a seller's republication of a listing fails at every registry after a
  negotiation opened
- **THEN** the negotiation continues against the rates last published successfully

#### Scenario: Registries hold different rates

- **WHEN** one of a seller's registries accepted a republication with new rates and
  another refused it
- **THEN** the seller refuses openings, rounds and acceptances on the listing with a
  distinct reason until its resend brings the registries to the same rates

#### Scenario: A registry's accepted rates are unknown

- **WHEN** after an upgrade from a release that kept no published payload, one of a
  seller's registries accepts a republication of a shape-priced listing and another
  that held the listing refuses it
- **THEN** the seller refuses openings, rounds and acceptances on the listing with
  the divergence reason until the other registry accepts a publication

#### Scenario: A buyer's acceptance would exceed its ceiling

- **WHEN** the payment derived from a seller's offer — its multiplier, the agreed
  shape and duration, and the published rates — exceeds the buyer's monetary ceiling
- **THEN** the buyer refuses to accept it

#### Scenario: A buyer opening with a smaller shape derives its prices for that shape

- **WHEN** a buyer opens with a shape smaller than the listing's and states no price
- **THEN** its derived opening and ceiling prices are the selected option's rate
  scaled by the opening shape's composed-price ratio and rounded up to a whole base
  unit, so it opens at the advertised minimum for what it asks, not above it by the
  inverse of that ratio

#### Scenario: The negotiated scalar is not money

- **WHEN** a shape-priced negotiation is accepted
- **THEN** the storefront records the agreed multiplier as the negotiation's negotiated
  scalar, and the Agreement, its mandate, and settlement carry the derived payment

### Requirement: A round may revise the capacity shape

A negotiation round after the first MAY carry a revised capacity shape as a child of
`proposal.provision_terms`, in the domain's versioned provision envelope, expressed in the
family-grouped capability shape the domain's schema validates. A round that carries
no revised shape is evaluated against the shape most recently agreed. Effective
provision terms MUST be durably recorded with each seller quote, and continuation
and acceptance MUST resume that quote's terms without mutating the opening. Before pricing
a revised shape the seller MUST evaluate, where its composition provides them,
admissibility, authoritative feasibility, and commercial feasibility, and MUST report
each refusal distinctly. A domain that composes no admissibility or feasibility check
MUST state so in its composition rather than silently evaluating on price alone.
Until a seller composes an authoritative feasibility check, it MUST refuse, with a
distinct reason and before pricing, a requested shape exceeding the listing's
advertised shape on any quantity. A first-round shape that differs from the listing's
is evaluated the same way rather than refused.

#### Scenario: A buyer proposes a smaller shape

- **WHEN** a buyer's counter carries a revised shape within the seller's constraints
- **THEN** the seller evaluates and prices that shape, and the next round's terms
  refer to it

#### Scenario: A revised shape is refused for admissibility

- **WHEN** a revised shape is outside what the seller will consider
- **THEN** the refusal names admissibility, distinct from a feasibility or commercial
  refusal

#### Scenario: A revised shape exceeds the advertised shape

- **WHEN** a seller composes no authoritative feasibility check and a revised shape
  asks for more of any quantity than the listing advertises
- **THEN** the seller refuses it with a reason distinct from admissibility and
  commercial refusals, without pricing it

#### Scenario: A revised shape is unreadable

- **WHEN** a revised shape does not validate against the domain's capability schema
- **THEN** the round is refused at the boundary before any evaluation

#### Scenario: A first-round shape differs from the listing

- **WHEN** a negotiation opens with a shape differing from the listing's advertised
  shape
- **THEN** the seller evaluates it as a proposal rather than refusing it outright
