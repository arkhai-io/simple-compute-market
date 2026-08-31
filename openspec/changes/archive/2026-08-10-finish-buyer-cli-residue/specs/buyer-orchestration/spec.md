## ADDED Requirements

### Requirement: Policy-constrained settlement preference

Buyer orchestration MUST apply buyer-policy preference only to settlement candidates that already satisfy compatibility and active chain/token constraints. A policy MUST NOT select or introduce a candidate outside that set, and invalid policy output MUST fall back or fail actionably without bypassing compatibility.

#### Scenario: Several compatible candidates remain

- **WHEN** noninteractive orchestration has several compatible settlement candidates and policy returns a valid preference
- **THEN** orchestration selects according to that preference before balance-based or deterministic default fallback

#### Scenario: Policy returns an unknown candidate

- **WHEN** policy output references a settlement tuple not present in the constrained input set
- **THEN** orchestration rejects that output and does not submit settlement using the unknown tuple

#### Scenario: Interactive choice is requested

- **WHEN** the buyer explicitly requests interactive selection among compatible candidates
- **THEN** the user's valid choice remains authoritative rather than being silently replaced by policy preference

#### Scenario: Zero or one candidate remains

- **WHEN** compatibility filtering leaves zero or one candidate
- **THEN** orchestration respectively reports no valid settlement choice or uses the sole candidate without requiring a preference decision
