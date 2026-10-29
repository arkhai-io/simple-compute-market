## ADDED Requirements

### Requirement: Rate servicing is a composition capability

The composition MUST declare whether it services rate parts and which contract it
implements. Publication, acceptance and materialization MUST read that one
declaration. A proposed contract MUST be usable only in an explicitly opted-in test
lane. Disabling new offers MUST NOT disable servicing of accepted recurring deals.

#### Scenario: Proposed contract outside a lane

- **WHEN** a non-lane composition declares only proposed rate servicing
- **THEN** recurring publication, acceptance and materialization are refused

### Requirement: Materialization and startup cannot strand recurring deals

Rate mandate materialization MUST refuse undeclared compatible servicing even
following acceptance and restart. A storefront with accepted recurring deals MUST
refuse startup without their continuation composed. Retained-deal servicing MUST
be independent of enabling new offers.

#### Scenario: Restart between acceptance and materialization

- **WHEN** a recurring Agreement was accepted but materialization's composition no longer declares servicing
- **THEN** no rate mandate is derived

#### Scenario: New offers disabled with accepted deals

- **WHEN** a storefront disables new recurring offers while retaining accepted recurring deals
- **THEN** startup requires their continuation and that continuation keeps servicing them
