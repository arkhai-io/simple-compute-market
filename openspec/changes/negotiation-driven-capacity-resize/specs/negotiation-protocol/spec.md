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
as an integer in basis points (10,000 is the advertised minimum), and every amount
derived from it MUST be computed in exact integer or decimal arithmetic, rounded
upward to the asset's base unit, and refused rather than truncated when it exceeds the
asset's amount type. A round's concession MUST remain comparable to the previous
round's when the requested capacity shape differs between them. A seller's commercial
floor MUST be expressible once, as a bound on the multiplier, and apply to every
admissible shape without per-shape restatement. The quote for a round is derived by
each party from the advertised rate structure and the round's shape and multiplier;
it is not carried on the wire. At opening, the seller MUST persist the digest of
the seller-authenticated rate structure. A later round or acceptance MUST be refused
with the distinct reason `rate_structure_changed_reopen` if the structure changed,
even when the advertised shape's composed total is unchanged. The buyer may still
exit the negotiation.

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
MUST state so in its composition rather than silently evaluating on price alone. A
first-round shape that differs from the listing's is evaluated the same way rather
than refused.

#### Scenario: A buyer proposes a smaller shape

- **WHEN** a buyer's counter carries a revised shape within the seller's constraints
- **THEN** the seller evaluates and prices that shape, and the next round's terms
  refer to it

#### Scenario: A revised shape is refused for admissibility

- **WHEN** a revised shape is outside what the seller will consider
- **THEN** the refusal names admissibility, distinct from a feasibility or commercial
  refusal

#### Scenario: A revised shape is unreadable

- **WHEN** a revised shape does not validate against the domain's capability schema
- **THEN** the round is refused at the boundary before any evaluation

#### Scenario: A first-round shape differs from the listing

- **WHEN** a negotiation opens with a shape differing from the listing's advertised
  shape
- **THEN** the seller evaluates it as a proposal rather than refusing it outright
