## ADDED Requirements

### Requirement: A VM listing discloses its resolved shape bounds

A published VM listing SHALL disclose the storefront's resolved shape bounds for its pool
and offering mode, in a form that translates exactly to a declaration the admissibility
kit evaluates. It SHALL NOT disclose which tier supplied a bound. A disclosed bound SHALL
be advisory to the buyer: the storefront SHALL judge a proposed shape against the bounds
in force when it agrees, not against the published copy.

#### Scenario: A buyer reads a listing's bounds

- **WHEN** a buyer retrieves a VM listing whose pool resolves shape bounds
- **THEN** it can evaluate a candidate shape against them through the admissibility kit
  before proposing it

#### Scenario: Bounds change after publication

- **WHEN** a buyer proposes a shape admissible under a stale published copy but not under
  the bounds now in force
- **THEN** the storefront refuses it for admissibility
