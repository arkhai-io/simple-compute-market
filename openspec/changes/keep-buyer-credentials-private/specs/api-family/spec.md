## ADDED Requirements

### Requirement: The buying library keeps a delivered credential private

The api family's buying library MUST write every run-log event of its buy, negotiate, and settle flows through a log that removes a delivered credential's secret wherever it appears, MUST save a delivered secret through the credential store its settlement composition holds, and MUST register the command that retrieves a run's credential in every domain's command group. A mechanism stage MUST NOT write or print a delivered secret.

#### Scenario: A mechanism stage records a seller status

- **WHEN** a mechanism stage records a seller status body that carries the delivered credential
- **THEN** the run log holds the body without the secret

#### Scenario: A domain registers its buyer commands

- **WHEN** a buyer plugin registers the buying library's command group
- **THEN** the group carries the `credentials show` command
