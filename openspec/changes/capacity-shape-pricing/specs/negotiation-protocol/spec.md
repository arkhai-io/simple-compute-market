## ADDED Requirements

### Requirement: Rate-multiplier negotiation

Where a domain's offering carries a resolvable rate structure, the quantity negotiated
between the parties MUST be a multiplier over the offering's advertised minimum rate
structure rather than an absolute amount for one shape. A round's concession MUST
remain comparable to the previous round's when the requested capacity shape differs
between them. A seller's commercial floor MUST be expressible once, as a bound on the
multiplier, and apply to every admissible shape without per-shape restatement.

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

### Requirement: Seller feasibility precedes pricing

Before pricing a requested capacity shape, a seller policy MUST evaluate that shape
against every dimension it constrains, quantitatively as well as categorically. A
policy MUST NOT price a shape it has already determined it will not serve.

#### Scenario: Requested shape exceeds a quantitative constraint

- **WHEN** a requested shape exceeds a seller constraint on a quantitative dimension
- **THEN** the seller declines on that basis rather than quoting a price for it

#### Scenario: Requested shape fails a categorical constraint

- **WHEN** a requested shape names a categorical attribute the seller does not offer
- **THEN** the seller declines without pricing, as it does today
