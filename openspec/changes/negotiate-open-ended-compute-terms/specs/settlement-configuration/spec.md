## ADDED Requirements

### Requirement: Rate servicing is a composition capability

The composition MUST declare whether it services rate parts and which contract it
implements. Publication and acceptance MUST read that one declaration; materialization and
continuation consumers MUST receive the same declaration contract, not an option-local copy. A proposed contract MUST be usable only in an explicitly opted-in test
lane. Continuation execution remains the servicing consumer's responsibility.

#### Scenario: Proposed contract outside a lane

- **WHEN** a non-lane composition declares only proposed rate servicing
- **THEN** recurring publication and acceptance are refused

### Requirement: Terms expose servicing declaration without enabling rate execution

Terms publication and acceptance MUST expose one composition-owned declaration contract
for rate materialization and continuation to consume. Terms alone MUST NOT enable recurring
execution; its qualification MUST remain distinct from consumer materialization/startup evidence.

#### Scenario: Terms are qualified before rate consumers

- **WHEN** declaration, publication and acceptance fixtures pass but rate continuation is not composed
- **THEN** terms can qualify those fixtures without claiming materialization/startup readiness or enabling deployed rate offers
