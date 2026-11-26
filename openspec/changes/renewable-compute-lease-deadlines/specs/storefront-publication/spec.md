## ADDED Requirements

### Requirement: A clause deadline a pool's value replaces is reported

Where the composition's pool port gives a delivery deadline for a candidate and the candidate's payments clause configures a different `delivery_deadline_seconds`, publication MUST report it through its diagnostics, naming the clause, the value it configures and the value published. The option MUST publish with the pool's value, as "A compute option's delivery deadline is its pool's, else its clause's" states.

#### Scenario: A clause and its pool differ

- **WHEN** the pool port returns 900 and the clause configures 1200
- **THEN** the option publishes 900 and publication reports that the clause's 1200 was replaced

#### Scenario: A pool gives none

- **WHEN** the pool port returns none and the clause configures 1200
- **THEN** the option publishes 1200 and nothing is reported
