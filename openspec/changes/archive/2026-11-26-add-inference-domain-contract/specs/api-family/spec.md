## ADDED Requirements

### Requirement: The purchase shape admits two key dispositions and an exact quantity

The family vocabulary's purchase shape MUST admit exactly two key dispositions:
a new key naming no `key_id`, and an existing key naming a non-blank `key_id`.
Its `quantity` MUST be a strict integer of at least one, and constructing a
purchase MUST NOT convert or truncate the quantity it is given. Every domain that
binds the shape inherits these refusals unchanged.

#### Scenario: A malformed key disposition is received

- **WHEN** provision terms under any bound kind carry a new key with a `key_id`,
  or an existing key whose `key_id` is empty or whitespace
- **THEN** validation refuses the terms

#### Scenario: A quantity is not an exact integer

- **WHEN** provision terms carry a quantity of `true`, `"5"`, `1.0`, or `1.5`,
  or a purchase is constructed with a quantity of `1.5`
- **THEN** validation refuses it rather than coercing or truncating it
