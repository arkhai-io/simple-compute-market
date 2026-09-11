## ADDED Requirements

### Requirement: Compute listings publish their capacity backing

A compute listing MUST publish whether an admission authority stands behind it.
The value is part of the compute listing shape rather than an optional annotation,
because a buyer cannot otherwise tell a listing they can reserve capacity against
from one where reservation is a no-op and any number of buyers may settle against
the same supply.

This value describes what the marketplace will do with the listing, not how far a
buyer should trust it. Every field a listing publishes is a seller assertion, and
no requirement in this capability verifies any of them for either kind of
listing.

A registry filter on backing MUST match exactly and MUST exclude a listing that
does not publish the field. A permissive match would return listings a buyer
specifically excluded: a listing predating the field would satisfy a query for
unbacked supply while being backed.

Listings published before this field existed MUST be republished carrying an
explicit capacity-backed value. They are semantically known to be backed and MUST
NOT depend on an absent field to be classified.

#### Scenario: A buyer queries for unbacked supply

- **WHEN** a buyer filters for listings with no admission authority behind them
- **THEN** only listings publishing that value are returned

#### Scenario: A listing does not publish backing

- **WHEN** a listing publishes no backing value and a buyer filters on backing
- **THEN** that listing is excluded from the result rather than matching either value

#### Scenario: Backed and unbacked listings share one catalogue

- **WHEN** a buyer queries without filtering on backing
- **THEN** both capacity-backed and unbacked listings are returned together, each carrying its published backing value
