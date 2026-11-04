## ADDED Requirements

### Requirement: A registry may recommend dispute authorities

A registry's descriptor MAY list recommended dispute authorities in preference order, each with its `interface`, `origin`, `account`, `record_key`, `params` and a copy of its advertisement. The list MUST be operator-authored configuration, like the display name, and MUST NOT be built into registry code. A descriptor without the list MUST remain valid.

#### Scenario: An operator recommends an authority

- **WHEN** a registry operator configures one recommended dispute authority
- **THEN** the signed descriptor lists it with its identity and advertisement

#### Scenario: A registry recommends none

- **WHEN** a registry operator configures no recommended authority
- **THEN** the descriptor omits the list and stays valid
