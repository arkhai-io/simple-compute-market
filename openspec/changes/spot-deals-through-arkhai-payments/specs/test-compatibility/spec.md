## ADDED Requirements

### Requirement: Rate-part qualification names contract and authority evidence
SCM's rate-part qualification MUST distinguish published-vector conformance, proposed-contract lane-double qualification, and hosted-target qualification. It MUST record revision/content hashes, mode and target class, and MUST NOT present double-backed scenarios as proof of the external authority's ledger, payouts or mechanical rulings.

#### Scenario: The lane runs against a proposed contract
- **WHEN** rate mechanics pass against the in-lane payment and mediation doubles
- **THEN** the result is labelled qualification against a proposed contract
- **AND** it makes no hosted readiness or live authority claim

#### Scenario: Required authority vectors are absent
- **WHEN** signed pre-start/post-start snapshot or partial reversal traces are unavailable
- **THEN** the corresponding authority-conformance claim is recorded as unproven
- **AND** double-generated traces are not relabelled published vectors

#### Scenario: The adapter is tested without lane services
- **WHEN** kit rate integration tests run
- **THEN** they exercise the contract fake and verified vector fixtures without starting lane HTTP tooling

#### Scenario: Consumer behavior is not yet composed
- **WHEN** adapter or notice first use succeeds before rate continuation is installed
- **THEN** evidence claims only command/authority mechanics and delivery fails closed without the rate hook
- **AND** no both-lane release or hosted qualification is claimed
