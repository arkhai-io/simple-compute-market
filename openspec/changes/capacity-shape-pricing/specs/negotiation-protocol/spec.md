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
- **THEN** the seller declines without pricing, as it does today
