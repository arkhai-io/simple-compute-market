## ADDED Requirements

### Requirement: A regression declares what it cannot prove
A generated regression MUST carry an evidence class recording which layer
authored it and what its evidence cannot establish. The class MUST travel with
the artifact rather than existing only in documentation about regressions. A
generated regression MUST NOT carry a concurrency or capacity claim, and such a
claim MUST be refused rather than qualified.

#### Scenario: A regression suite passes
- **WHEN** a suite of generated regressions runs green
- **THEN** nothing in it supports a claim about behaviour under concurrency or
  about capacity, because each regression records that it cannot establish them

#### Scenario: A regression would assert a concurrency outcome
- **WHEN** a generated regression would claim an outcome that depends on
  concurrent arrival against a real dependency
- **THEN** the claim is refused, because a hermetic replay cannot exercise it

#### Scenario: A regression is read without its surrounding documentation
- **WHEN** a regression is examined on its own
- **THEN** its evidence class is present in the artifact

### Requirement: A regression is separated from its execution adapter
A regression MUST declare normalized actions and expected outcomes independently
of how they are executed. It MUST NOT encode model prose, hidden reasoning,
incidental command ordering, timestamps, or temporary identifiers. It MUST be
re-runnable under a different adapter without being rewritten.

#### Scenario: A regression is re-run under a higher-fidelity adapter
- **WHEN** there is reason to doubt that a hermetic result still holds
- **THEN** the same regression can be executed against a controlled integration
  environment without changing its declared actions or outcomes

#### Scenario: An incidental detail changes
- **WHEN** command ordering, a timestamp, or a temporary identifier differs
  between runs
- **THEN** the regression is unaffected, because none of them is part of its
  declaration

### Requirement: A defect regression demonstrates failure without its fix
A regression protecting a corrected defect MUST carry evidence that it fails
when the protected behaviour is absent — by fail-before/pass-after or by
mutation sensitivity. Where neither is practical, another focused demonstration
MAY be accepted and the substitution MUST be recorded. A regression generated
from a run that passed MUST carry a distinct evidence class recording that it
was never observed failing.

#### Scenario: A regression is generated from a corrected defect
- **WHEN** a regression protects behaviour that was previously defective
- **THEN** it carries evidence that it fails without the fix, so that a captured
  fix is distinguishable from a captured defect

#### Scenario: Neither standard method is practical
- **WHEN** fail-before/pass-after and mutation sensitivity are both impractical
- **THEN** the accepted alternative demonstration is recorded, because an
  unrecorded substitution is indistinguishable from an unexamined one

#### Scenario: A regression is generated from a passing run
- **WHEN** a regression is generated from a journey that did not fail
- **THEN** its evidence class records that it was never observed failing

### Requirement: A regression derived from agent evidence is sanitized before it is committed
A regression whose content derives from agent execution evidence MUST pass the
same allowlist projection as any other artifact crossing from private execution
into this repository. It MUST NOT receive a lighter projection on the grounds
that it is test data.

#### Scenario: A private identifier appears in a recorded action
- **WHEN** a private path, host, account, or credential appears within a
  recorded action's payload
- **THEN** the containing field is withheld, and the regression is not committed
  carrying it

#### Scenario: A fixture is reviewed after the fact
- **WHEN** a committed regression is examined
- **THEN** it contains no private identifier, because a fixture is committed
  once and read rarely and would otherwise carry one unnoticed

### Requirement: A generated regression enters the level that owns its behaviour
A generated regression MUST be placed at the verification level that owns the
behaviour it protects, alongside the tests already covering that behaviour, and
MUST be owned by that level thereafter. It MUST NOT be placed in a separate
level or in a directory segregating generated tests.

#### Scenario: A regression protects behaviour an existing level covers
- **WHEN** a regression is generated for behaviour a verification level already
  owns
- **THEN** it is placed at that level, alongside the tests covering that
  behaviour

#### Scenario: A generated regression fails for an unrelated reason
- **WHEN** an unrelated change causes a generated regression to fail
- **THEN** the level owning it is responsible for it, and it is not treated as
  stale on the grounds that a tool generated it
