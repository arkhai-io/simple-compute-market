## MODIFIED Requirements

### Requirement: Stripe test-mode activation fails closed

Protected hosted startup MUST prove the exact marketplace consumer commit and
hosted release identity, a test-mode secret (`sk_test` or least-privilege
`rk_test`), non-live returned objects,
Stripe API connectivity, expected allowlisted test-account ownership and
capabilities, loopback-only webhook delivery to the exact authority endpoint,
and browser availability. A mismatch or unavailable prerequisite MUST stop
before the relevant publication, acceptance, Checkout, transfer, or refund
mutation. Local focused evidence MUST NOT replace a failed prerequisite.

The prerequisites divide by what they protect, and the two MUST NOT be
conflated. Safety prerequisites — test-mode-only credentials, refusal of live
provider objects, loopback-only webhook delivery, connected-account readiness,
and browser availability — MUST hold in every run of the hosted scenario body,
under every release mode, and MUST fail closed before any provider mutation.
Provenance prerequisites — the attested marketplace release manifest, equality
of the observed working-tree commit with the trusted release commit, pinned
image and wheel digests, and the producer workflow run identity — MUST determine
what a completed run's evidence may claim, and MUST NOT be the reason the body
cannot execute.

#### Scenario: Live credential is supplied

- **WHEN** protected hosted E2E receives a live-mode Stripe credential or observes a live provider object
- **THEN** preflight fails before creating any payment, transfer, refund, or marketplace settlement mutation and redacts the credential

#### Scenario: Connected account is unready

- **WHEN** the selected test connected account lacks the expected ownership binding, charge/transfer capability, or readiness required by the scenario
- **THEN** preflight reports an account-readiness failure before publication of a Stripe option or payment creation

#### Scenario: Release identity is incomplete

- **WHEN** a protected run cannot bind its manifest digest, client wheel hash, service image digest, signed release repository/workflow reference/source commit, or separate protected producer workflow run identity
- **THEN** startup fails before Compose creates the authority or marketplace services and no partial identity is reported as system evidence

#### Scenario: A safety prerequisite fails in a development run

- **WHEN** a development run of the same body receives a live credential, an unready connected account, or a webhook destination that is not loopback
- **THEN** it fails closed exactly as a protected run does, before any provider mutation

## ADDED Requirements

### Requirement: A hosted run declares its release mode

Every run of the hosted scenario body MUST record an explicit release mode in its
evidence. A run whose provenance prerequisites are all satisfied MUST be recorded
as attested; any other run MUST be recorded as a development run. Evidence MUST
NOT be capable of omitting the mode or of claiming attestation that its inputs do
not support, and no option, flag, or configuration MUST allow a development run to
be recorded as attested.

Development-run evidence MUST NOT satisfy a verification task that requires
protected evidence, and any report that aggregates runs MUST keep the two
distinguishable.

#### Scenario: A development run completes successfully

- **WHEN** the body runs to a successful funding and collection against a locally built stack, on a working tree that is not the trusted release commit
- **THEN** its evidence records a development release mode, and the qualification tasks that require protected evidence remain unsatisfied by it

#### Scenario: An attested run completes successfully

- **WHEN** the body runs with an attested marketplace release manifest, an observed commit equal to the trusted release commit, and every pinned digest and producer run identity bound
- **THEN** its evidence records an attested release mode and carries the same complete release identity it carries today

#### Scenario: A development run is presented as protected evidence

- **WHEN** a report or task cites evidence whose recorded release mode is a development run in place of protected evidence
- **THEN** the citation is rejected on the recorded mode alone, without needing to re-inspect the run's inputs

### Requirement: A development run needs no release infrastructure

Running the hosted scenario body for development MUST NOT require an attested
release artifact, a published image digest, a credential-broker service, or a
self-hosted runner. Its provider credentials and identity material MUST be
assemblable from local operator-supplied configuration, and that assembly MUST
produce the same shape a credential broker returns, so that a broker
implementation later substitutes for it without changing the body.

#### Scenario: A developer runs the body on their own branch

- **WHEN** an operator supplies test-mode provider credentials and a locally built stack on a working tree that is not a released commit
- **THEN** the body runs its scenario end to end without an attestation, a broker, or a self-hosted runner, and reports a development run

#### Scenario: The broker is implemented later

- **WHEN** a credential-broker service is introduced that returns the documented payload
- **THEN** it substitutes for local assembly with no change to the scenario body or its gates
