## ADDED Requirements

### Requirement: Rate mechanics qualification consumes the shared lane contract
Rate mechanics qualification MUST follow "Lane qualification identifies readiness and evidence class". It MUST retain kit/vector and re-anchoring evidence production, while convergence owns rate-lane time and consuming scenarios. It MUST NOT redefine evidence classes or claim live behavior from a double.

#### Scenario: Mechanics run against a proposed contract
- **WHEN** rate adapter mechanics pass against contract fakes or lane doubles of proposed bytes
- **THEN** evidence identifies the proposed revision and makes no hosted-readiness or live-authority claim

#### Scenario: Required authority vectors are absent
- **WHEN** producer-published signed pre-start/post-start snapshot, start, setup-trigger/fallback or partial reversal vectors are unavailable
- **THEN** the corresponding authority-conformance claim remains unproven
- **AND** double-generated traces do not replace producer evidence

#### Scenario: The adapter is tested without lane services
- **WHEN** kit rate integration tests run
- **THEN** they exercise the shared clock-injected payments authority engine and verified vector fixtures without starting lane HTTP tooling

#### Scenario: Interim fixtures disclose non-default policy
- **WHEN** a spot or on-demand command fixture offers started_period on an entitlement or term end rejected by default buyer policy
- **THEN** its committed setup explicitly configures buyer acceptance for every affected term
- **AND** focused fixture validation records default-policy refusal separately

#### Scenario: Command first use precedes continuation
- **WHEN** adapter or notice first use succeeds before rate continuation is installed
- **THEN** evidence claims only command/authority mechanics and delivery refuses without the rate hook
- **AND** no both-lane release, due-work completion or hosted qualification is claimed
