## MODIFIED Requirements

### Requirement: Public and protected hosted checks remain distinct

Public/default checks MUST cover deterministic provider-neutral hosted client/adapter/payer/authorization behavior, state-machine integration, configuration, package contents, typing, release verification, browser action dispatch, consumer redaction, and evidence-schema validation without credentials. The marketplace MUST verify signed producer conformance evidence for producer-owned webhook-inbox recovery rather than importing, simulating, or claiming that internal behavior. Protected Stripe checks MUST require explicit role-scoped test credentials, exact signed release inputs, selected profile prerequisites, and fail-closed enablement.

A public check MUST NOT require a signed producer release in order to obtain a producer artifact it compiles against. Where the artifact it needs belongs to a version that has one, it MUST use it and verify it. Where the version has none, the check MAY obtain the artifact from an access-controlled internal channel instead, and MUST treat what it obtained as unattested: it MUST NOT verify, claim, or record provenance for it, and it MUST NOT thereby satisfy anything reserved to a check with signed release inputs.

Which of the two applies MUST follow from the version the consumer pins and the version the trusted release names, and MUST NOT be selected by a separate switch. A check that cannot reach the channel it needs MUST report the version and the channel as the unavailable prerequisite, rather than failing as though the artifact did not exist.

#### Scenario: Contributor runs public checks

- **WHEN** no Stripe credential or protected hosted release access is present
- **THEN** default collection and execution succeed without probing provider controls or attempting hosted financial E2E, while all required credential-free consumer tests still run

#### Scenario: Protected profile selection is incomplete

- **WHEN** the protected lane requests a funding profile but lacks its exact account capability, test instrument/funding path, browser action, or release contract
- **THEN** preflight stops before publication/funding mutation and records the exact unavailable prerequisite

#### Scenario: Explicit protected run lacks a prerequisite

- **WHEN** an operator selects hosted Stripe system E2E without one required release, credential, network, webhook, browser, account, or selected-profile prerequisite
- **THEN** preflight reports the exact unmet prerequisite before payment creation and does not cite focused or simulated output as Stripe evidence

#### Scenario: A public check compiles against an unreleased producer version

- **WHEN** the consumer pins a producer version that the trusted release does not name
- **THEN** the public check obtains that version's artifact from the internal channel, runs its suites against it, and neither verifies nor records provenance for it

#### Scenario: A public check compiles against a released producer version

- **WHEN** the pinned version and the version the trusted release names are the same
- **THEN** the public check obtains the signed release assets and verifies them exactly as it does today

#### Scenario: The internal channel is unreachable

- **WHEN** a public check needs an unreleased producer artifact and cannot authenticate to the internal channel
- **THEN** it reports the version and the channel as the unavailable prerequisite, and does not report the artifact as missing or the suite as broken
