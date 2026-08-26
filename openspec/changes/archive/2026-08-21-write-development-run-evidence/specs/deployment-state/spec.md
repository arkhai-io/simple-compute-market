## MODIFIED Requirements

### Requirement: A development run needs no release infrastructure

Running the hosted scenario body for development MUST NOT require an attested
release artifact, a published image digest, a credential-broker service, or a
self-hosted runner. Its provider credentials and identity material MUST be
assemblable from local operator-supplied configuration, and that assembly MUST
produce the same shape a credential broker returns, so that a broker
implementation later substitutes for it without changing the body.

This MUST hold for both halves of the stack. Neither the marketplace consumer nor
the hosted settlement authority MUST require a published release in order to be
run; either MUST be satisfiable by an image the operator built, named explicitly
by the run. Where a released half supplies its verified coordinates from a signed
manifest, a locally built half MUST supply the same coordinates from the artifacts
that build generated, so the Compose environment a development run renders has the
same shape and the same key set as an attested one. An operator MUST be able to run
one half locally and the other from a release, in either combination.

A run in which any half is locally built MUST be recorded as a development run.

This MUST include recording the run. A locally built half MUST record, in place
of each released coordinate it has none of, the same self-describing marker the
binding gate assigned it, and MUST record the coordinates it does have: the
image the run named and the build the authority reported. Evidence MUST NOT be
refused for lacking coordinates the run was admitted without, and MUST NOT be
accepted when a half is partly released and partly local — the rule that admits
the run and the rule that records it MUST be the same rule.

#### Scenario: A development run records what it ran

- **WHEN** a run against a locally built half completes its scenario, whatever the outcome
- **THEN** its evidence is written, records the development release mode, records the marker in place of each coordinate that half has none of, and names the image and the reported build

#### Scenario: A recorded half is partly released and partly local

- **WHEN** evidence for one half carries some exact released coordinates and some markers
- **THEN** it is refused, because no admitted run produces that combination

#### Scenario: A developer runs the body on their own branch

- **WHEN** an operator supplies test-mode provider credentials and a locally built stack on a working tree that is not a released commit
- **THEN** the body runs its scenario end to end without an attestation, a broker, or a self-hosted runner, and reports a development run

#### Scenario: The settlement authority under test has no published release

- **WHEN** an operator names a locally built hosted settlement image and its generated contract artifacts, and no published release of that version exists
- **THEN** the body runs its scenario end to end against that image, and the run is recorded as a development run

#### Scenario: One half is released and the other is local

- **WHEN** a run binds a published release for one half of the stack and a locally built image for the other
- **THEN** the run is admitted, the released half is bound by its signed coordinates exactly as it is today, and the run is recorded as a development run

#### Scenario: A local half is named without its contract artifacts

- **WHEN** a run names a locally built image but cannot read the generated contract artifacts describing what that image serves
- **THEN** the run fails closed before Compose creates any service, and reports the missing artifacts rather than substituting the coordinates of a different release

#### Scenario: The broker is implemented later

- **WHEN** a credential-broker service is introduced that returns the documented payload
- **THEN** it substitutes for local assembly with no change to the scenario body or its gates
