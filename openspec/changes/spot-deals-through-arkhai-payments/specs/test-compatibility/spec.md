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

### Requirement: Both compute lanes qualify rate stops through the consumer
SCM MUST exercise cross-service rate behavior in both compute lanes after rate continuation is composed: buyer stop, seller notice surviving storefront outage, earlier buyer stop during notice, exhaustion, maximum term and on-demand exceptional end. Each scenario MUST observe authority records and actual domain release; hosted runs MUST check readiness before execution.

#### Scenario: A spot seller disappears after notice
- **GIVEN** an accepted pending stop and a stopped storefront process
- **WHEN** the lane clock passes its effective time
- **THEN** payment read shows the authority-applied stop without a second seller command
- **AND** after storefront recovery the continuation ends domain access/capacity and corrects the incomplete seller-started period while held

#### Scenario: Hosted prerequisites are missing
- **WHEN** the hosted revision, accounts, credentials or required hardware are unavailable
- **THEN** the scenario reports the exact unmet prerequisite before driving the deal
- **AND** it reports no successful hosted qualification or mechanism fallback
