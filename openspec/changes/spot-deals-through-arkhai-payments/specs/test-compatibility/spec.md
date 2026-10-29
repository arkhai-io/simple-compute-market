## ADDED Requirements

### Requirement: Rate-part qualification names contract and authority evidence
SCM's rate-part qualification MUST use the lane-double-owned classes Qualification against the published contract, Qualification against a proposed contract, and Live evidence. It MUST record revision/content hashes, mode and target class, and MUST NOT present double-backed scenarios as proof of the external authority's ledger, payouts or mechanical rulings.

#### Scenario: The lane runs against a proposed contract
- **WHEN** rate mechanics pass against the in-lane payment and mediation doubles
- **THEN** the result is labelled qualification against a proposed contract
- **AND** it makes no hosted readiness or live authority claim

#### Scenario: Required authority vectors are absent
- **WHEN** producer-published signed pre-start/post-start snapshot, start or partial reversal vectors are unavailable
- **THEN** the corresponding authority-conformance claim is recorded as unproven
- **AND** activation lists these as blockers to published qualification rather than relabelling double-generated traces as published vectors

#### Scenario: Notice or term work becomes due in a lane
- **WHEN** a rate scenario waits for notice or maximum-term effects
- **THEN** it uses wall time and tooling-owned typed due-work barriers with per-authority progress, pending effects and blocked dependencies
- **AND** future work remains pending and blocked effects do not count as completion
- **AND** injected or advanced clocks are limited to isolated tooling state-machine tests

#### Scenario: The adapter is tested without lane services
- **WHEN** kit rate integration tests run
- **THEN** they exercise the contract fake and verified vector fixtures without starting lane HTTP tooling

#### Scenario: Consumer behavior is not yet composed
- **WHEN** adapter or notice first use succeeds before rate continuation is installed
- **THEN** evidence claims only command/authority mechanics and delivery fails closed without the rate hook
- **AND** no both-lane release or hosted qualification is claimed
