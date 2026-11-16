## ADDED Requirements

### Requirement: Every party in a lane shares one lane time the scenario sets

Each Compose lane MUST run every party on injected time: every storefront, provisioning service, registry, the API-credits service and the sample app's middleware where the lane runs them, both doubles, and the buyer, with the harness's own signing clients reading its process source. One harness fixture MUST set every party at the session's start to the wall instant at that moment, and its set MUST move, in order, the harness's own source, each service, both doubles, the chain and the buyer's lane-time file to one instant, then read every party's status and fail naming any that does not report it. Lane time MUST only move forward and MUST never be reset; a stage MAY set any forward instant, and a backward set MUST fail naming the party and both instants. A party the run's profile names but cannot reach MUST fail the setup rather than skip.

#### Scenario: Funds run out without waiting

- **WHEN** a rate deal's funding reaches its boundary at 1794823200 and a stage sets lane time to 1794823200, then steps the storefront's servicing and the lease watchdog
- **THEN** the storefront records the exhaustion stop, the site ends the lease at 1794823200, and teardown follows, with no wait on wall time

#### Scenario: A party misses a set

- **WHEN** a lane-time set leaves one registry at its previous instant
- **THEN** the fixture fails naming that registry and the instant it reports

#### Scenario: A module follows an advanced one

- **WHEN** a module ends with lane time at 1794830000
- **THEN** the next module starts at 1794830000 or later, with every party reporting the same instant

### Requirement: The chain follows lane time

At the session's start and at every lane-time set, the fixture MUST set the lane chain's next block timestamp to the lane instant and mine a block, and MUST freeze the chain's block time between sets where the chain supports it.

#### Scenario: An escrow created after an advance

- **WHEN** lane time is set 3600 s forward and a buyer creates an escrow expiring one hour after the lane instant
- **THEN** the chain accepts it as unexpired

### Requirement: A run uses one time source throughout

A run MUST be injected or wall time throughout, and the session fixture MUST fail naming a mix. External-topology runs and runs against the local Helm release MUST run on wall time: there the lane-time helper MUST reach only an instant the Agreement fixes, by waiting for it, and a stage needing any other instant MUST be a blocked skip naming the wall-time target. Shared stages MUST reach instants only through that helper.

#### Scenario: A time-driven module against a hosted target

- **WHEN** a module that sets lane time to a funding boundary runs against hosted authorities
- **THEN** its stage is a blocked skip naming the wall-time target, never a wait

### Requirement: Each lane double reads injected time the scenario sets

Each double MUST read time from the shared time component's injected source, set through `POST /test/time` with `{"now": <Unix seconds>}` behind its control bearer token, answering `{"source": "injected", "now": …}` and refusing an earlier instant with `time_moves_forward`; each double's status MUST report its source and now. Due authority state MUST become visible at the next read, with no background work. A lane's time MUST live only in that lane's parties.

#### Scenario: A once part's hold is passed

- **WHEN** a scenario sets lane time past a once part's release instant
- **THEN** the next read shows the part paid out, and a case the buyer files afterwards reports that part `not_held` with `paid_out` and is dismissed with nothing held

#### Scenario: Lanes run side by side

- **WHEN** two lanes run at once, in separate Compose projects or separate Helm validation namespaces, and one sets its lane time
- **THEN** the other lane's parties still report their own instant

## REMOVED Requirements

### Requirement: Each lane double reads a perceived clock the scenario advances

**Reason**: Lane time spans every party, frozen at an instant the scenario sets and never reset; the doubles' offset clock, advanced alone and reset per module, is replaced.

**Migration**: "Each lane double reads injected time the scenario sets" and "Every party in a lane shares one lane time the scenario sets" replace it; scenarios set lane time through the lane-time fixture instead of `lane_double_clock`.
