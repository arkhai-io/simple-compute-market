## ADDED Requirements

### Requirement: Frozen accepted context is rendered as inert readable fields

An explicit-policy contact delivery MUST render only its recipient's frozen counterparty contact and accepted introduction package. Nested context MUST be readable without interpreting domain objects, HTML or templates. Scalar text MUST remain verbatim. Routes MUST NOT enter the shared content unless independently authored as contact text.

#### Scenario: Whole blurbs and accepted declaration reach both recipients

- **WHEN** a buyer reviews and finalizes an accepted context-eligible introduction
- **THEN** the buyer copy contains the seller's whole authored blurb and the seller copy contains the buyer's whole reviewed blurb
- **AND** both contain the frozen listing identity, machine details and accepted terms
- **AND** neither includes the other party's own routing address merely because it is configured

#### Scenario: Settings and listing changes cannot rewrite captured delivery

- **WHEN** settings or listing data change after finalization and delivery resumes after restart
- **THEN** the exact persisted contact and accepted context are rendered with the captured recipient routes
- **AND** no additional exchange or recipient intent is created
