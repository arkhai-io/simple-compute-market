## ADDED Requirements

### Requirement: Campaign projection is deterministic
Projecting a recorded event corpus into a result MUST be a pure function of that
corpus. The projection MUST NOT depend on ambient time, on wall-clock ordering
where causal ordering is available, or on identifiers that vary between
projections. Projecting one corpus twice MUST produce identical results.

#### Scenario: A corpus is projected twice
- **WHEN** the same recorded corpus is projected on two occasions
- **THEN** the two results are identical, so a reviewer can re-derive a result
  rather than trust it

#### Scenario: Events arrive in a different order
- **WHEN** a corpus is projected with its events reordered, where causal
  ordering determines the outcome
- **THEN** the result is unchanged

### Requirement: Measurements are attributed, not derived
Offered demand, served capacity, and load-generator limit MUST be separate
measurements, each derived from its own evidence. None MAY be computed as the
residual of the others. A quantity that cannot be attributed to exactly one of
them MUST be reported as unattributed, carrying the observations that made it
ambiguous, and MUST NOT be reported as any of the three.

#### Scenario: An actor never reached its release
- **WHEN** an actor failed to start, missed its release, or was still preparing
  when the barrier fired
- **THEN** the shortfall is attributed to load-generator limit, and served
  capacity is not reduced on its account

#### Scenario: A shortfall cannot be attributed
- **WHEN** the recorded observations do not establish whether a shortfall was
  the product's or the harness's
- **THEN** it is reported as unattributed with those observations, rather than
  assigned to either

### Requirement: Underivable metrics are absent with a reason
A metric the recorded evidence does not support MUST be recorded as absent
together with the reason it is absent. It MUST NOT be defaulted to zero, and it
MUST NOT be omitted, so that "not measured" stays distinguishable from "measured
as none" and from "not applicable".

#### Scenario: A collector did not run
- **WHEN** the evidence for a metric was never collected
- **THEN** the metric is absent with that reason, and is not reported as zero

### Requirement: Evidence class bounds the claim
Every result MUST carry the class of claim its evidence supports. A result
produced from mock, dry-run, fixture, or rehearsal evidence MUST NOT carry a
live, capacity, or production claim. A claim the result's class does not admit
MUST be refused rather than attached with a qualifier.

#### Scenario: A mock-sourced result would carry a capacity claim
- **WHEN** a result derived from mock evidence would assert a capacity outcome
- **THEN** the claim is refused, and the result records the class that refused it

#### Scenario: A result is read out of context
- **WHEN** a result is consumed without its surrounding narrative
- **THEN** its evidence class travels with it, so the bound on its claims does
  not depend on the reader

### Requirement: The existing issue engine is the only issue lifecycle
Findings MUST flow through the existing issue engine. A refusal matching a
declared expectation MUST be suppressed at projection so it never becomes a
candidate, while remaining counted in the result. Filing readiness MUST be gated
on cleanup, and a cleanup failure MUST be its own finding rather than an
annotation on another. A recurrence of a known fingerprint MUST update or reopen
the existing issue rather than file a second one. The engine MUST NOT create a
comment, a branch, a pull request, or a merge.

#### Scenario: A declared refusal occurs as expected
- **WHEN** a refusal matches the signature its scenario declared
- **THEN** no candidate is generated for it, and the result still reports that
  it occurred

#### Scenario: A scenario declared refusals that did not occur
- **WHEN** a scenario declared refusals and none were observed
- **THEN** the discrepancy is visible in the result, because expected refusals
  are counted rather than merely suppressed

#### Scenario: A run leaves residue behind
- **WHEN** a run's cleanup did not complete
- **THEN** its findings are not filing-ready, and the cleanup failure is
  recorded as a finding in its own right

#### Scenario: A known defect recurs after its issue was closed
- **WHEN** a fingerprint matching a closed issue is observed again
- **THEN** the existing issue is reopened with the recurrence and the product
  revision observed, and no second issue is filed

#### Scenario: The engine's surface is inspected for mutation paths
- **WHEN** the issue engine's reachable surface is examined
- **THEN** it exposes no path that creates a comment, a branch, a pull request,
  or a merge
