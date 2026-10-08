## ADDED Requirements

### Requirement: Expanded hosted consumer behavior is tested at owned boundaries

Credential-free tests MUST cover exact funding-profile config/option identity, independent readiness/publication, local persistent payer binding, direct payer and exact authorization calls, bounded automation policy, storefront mediation, transient actions, delayed funding, immutable runtime journals, legacy card recovery, fulfillment gates, reclaim races, and sanitized evidence. They MUST use the exact released client models with deterministic hosted-port outcomes and MUST NOT claim external Stripe behavior.

Protected integration MUST attribute only the external assertions actually exercised for `card.v1`, `us_bank_transfer.v1`, `us_ach_debit.v1`, and off-session `requires_action`. Each scenario MUST identify marketplace and hosted releases independently and MUST mark unavailable provider prerequisites rather than simulate or substitute them.

#### Scenario: Contributor runs default marketplace checks

- **WHEN** no hosted service, Stripe credential, browser, or provider prerequisite is configured
- **THEN** config, adapter, buyer, storefront, runtime, packaging, typing, redaction, and deterministic recovery tests complete without external calls or silent omissions

#### Scenario: Protected ACH prerequisite is absent

- **WHEN** the selected connected account cannot exercise an ACH availability/return boundary
- **THEN** the protected report marks only those ACH assertions unavailable and does not attribute card, simulated provider, or credential-free outcomes to them

### Requirement: Consumer fault cases preserve exact identity

Deterministic integration tests MUST inject acknowledgement loss, timeout, restart, duplicate request, changed request conflict, delayed visibility, readiness loss, expiry race, and operator-required outcome around direct authorization and mediated escrow boundaries. Assertions MUST prove one buyer profile owner, one funding authorization, one marketplace operation, one hosted escrow/financial operation, and no cross-profile or cross-mechanism fallback. Test clocks and event controls MUST be injected directly rather than selected through runtime configuration.

#### Scenario: Authorization succeeds before timeout

- **WHEN** the deterministic authority applies an exact authorization but the buyer loses acknowledgement and restarts
- **THEN** retry returns the same authorization reference and storefront start creates at most one hosted obligation

#### Scenario: Profile readiness changes during recovery

- **WHEN** a pending bank obligation resumes after that profile is disabled for new purchases
- **THEN** recovery uses the accepted profile and identities rather than switching to card or Alkahest

## MODIFIED Requirements

### Requirement: Stripe-backed hosted settlement system evidence

The marketplace-owner wallet-free VM lifecycle against Stripe test mode MUST verify one exact signed hosted release at the producer boundary and one exact marketplace consumer release, then exercise ordinary marketplace publication, discovery, negotiation, accepted funding authorization, hosted materialization, buyer action, authoritative funding, VM fulfillment evidence, condition evaluation, collection or eligible reclaim, status, restart, and recovery for each selected exact profile. The report MUST record marketplace source/commit separately from hosted manifest, client wheel, service image, contract/schema, migrations, provenance, release repository/workflow/ref/source, capability set, and protected workflow run. Every provider assertion MUST derive from authoritative Stripe retrieval through the hosted service and MUST be attributed only to the rail actually exercised.

#### Scenario: Successful `card.v1` purchase

- **WHEN** Chromium completes required card interaction and hosted retrieval proves accepted funding and transfer outcomes
- **THEN** the report records one signed marketplace-to-storefront-to-hosted lifecycle with exact artifact identities and sanitized payment/transfer evidence

#### Scenario: Successful `us_bank_transfer.v1` purchase

- **WHEN** the test uses issued instructions and attributable test funds through the configured supported Stripe test path
- **THEN** the report records awaiting-payment, authoritative funding, fulfillment, and collection boundaries without storing bank instructions or provider IDs

#### Scenario: Successful `us_ach_debit.v1` purchase

- **WHEN** the exact test debit crosses mandate/confirmation and availability gates
- **THEN** the report records delayed state, authoritative funding, fulfillment, and collection or declared return/reclaim boundary without claiming card behavior

#### Scenario: Off-session action fallback

- **WHEN** a bounded automated card purchase returns `requires_action`
- **THEN** the same accepted obligation/authorization/operation continues interactively and the report proves no profile, instrument, amount, destination, or identity substitution

#### Scenario: Real Stripe collection succeeds

- **WHEN** an authorized protected run completes the selected profile's real Stripe test-mode funding path, delivers or reconciles authoritative provider state, and satisfies the accepted fulfillment condition
- **THEN** the ordinary authority worker converges to collected and authoritative retrieval identifies exactly one related funding operation and destination transfer with the expected amount, currency, destination, transfer group or normalized relation, stable idempotency identity, and marketplace operation identity

#### Scenario: Real Stripe reclaim succeeds

- **WHEN** a distinct funded test-mode obligation remains unfulfilled until its profile-specific pre-transfer reclaim is eligible
- **THEN** buyer-authorized reclaim converges to exactly one related return, cancellation, or refund, recovery under the original operation identity creates no second reversal, and no transfer exists for that obligation

#### Scenario: Missed webhook is reconciled

- **WHEN** real profile funding completes while webhook forwarding or the reconciliation worker is stopped and ordinary processes later restart against preserved authority state
- **THEN** authoritative Stripe retrieval converges the accepted obligation without recreating funding and any transfer or reversal uses the original operation identity exactly once

### Requirement: Public and protected hosted checks remain distinct

Public/default checks MUST cover deterministic provider-neutral hosted client/adapter/payer/authorization behavior, state-machine integration, configuration, package contents, typing, release verification, browser action dispatch, consumer redaction, and evidence-schema validation without credentials. The marketplace MUST verify signed producer conformance evidence for producer-owned webhook-inbox recovery rather than importing, simulating, or claiming that internal behavior. Protected Stripe checks MUST require explicit role-scoped test credentials, exact signed release inputs, selected profile prerequisites, and fail-closed enablement.

#### Scenario: Contributor runs public checks

- **WHEN** no Stripe credential or protected hosted release access is present
- **THEN** default collection and execution succeed without probing provider controls or attempting hosted financial E2E, while all required credential-free consumer tests still run

#### Scenario: Protected profile selection is incomplete

- **WHEN** the protected lane requests a funding profile but lacks its exact account capability, test instrument/funding path, browser action, or release contract
- **THEN** preflight stops before publication/funding mutation and records the exact unavailable prerequisite

#### Scenario: Explicit protected run lacks a prerequisite

- **WHEN** an operator selects hosted Stripe system E2E without one required release, credential, network, webhook, browser, account, or selected-profile prerequisite
- **THEN** preflight reports the exact unmet prerequisite before payment creation and does not cite focused or simulated output as Stripe evidence

### Requirement: Protected hosted evidence is attributable and sanitized

Every protected marketplace-hosted run MUST produce a schema-validated report signed by the marketplace repository's designated evidence signer. It MUST record exact independent consumer and producer release identities, selected profile/currency, public lifecycle stages, normalized outcomes, attempts, timestamps, workflow/run identity, and permitted hashed opaque correlations. It MUST exclude credentials, provider/customer/payment-method/mandate/bank/card identifiers or data, raw actions/URLs, provider payloads/events/requests, source-bearing local paths, and unrestricted logs.

#### Scenario: Sensitive provider data reaches a report field

- **WHEN** schema validation or recursive canary scanning finds credential, provider/customer/payment-method/mandate/bank/card data, raw action, payload, URL, or source-bearing path
- **THEN** the report is rejected before signing or publication

#### Scenario: Consumer and producer releases differ

- **WHEN** the protected run uses marketplace and hosted artifacts from distinct repositories or commits
- **THEN** the report records both exact identity sets without collapsing them into one source claim

#### Scenario: Protected assertion is unavailable

- **WHEN** a rail, return, confirmation, account capability, browser, or external system is unavailable
- **THEN** the report records the assertion and missing prerequisite as unavailable and does not replace it with simulated or local evidence

#### Scenario: Report is altered after signing

- **WHEN** a reviewer verifies a modified report
- **THEN** signature verification fails

#### Scenario: Stripe is unavailable during setup

- **WHEN** a protected run cannot reach Stripe before any marketplace or financial mutation
- **THEN** it reports an `environment` failure with separately identified consumer and hosted release coordinates and records no secret or provider payload

#### Scenario: Connected account is not ready

- **WHEN** the allowlisted test connected account fails its ownership, capability, or readiness checks
- **THEN** preflight reports an `account` failure before publishing the hosted option or creating payment state

#### Scenario: Terminal state violates the contract

- **WHEN** prerequisites are valid and the observed signature, state, amount, relation, cardinality, or marketplace transition contradicts the accepted scenario
- **THEN** the run reports a `product` failure with bounded sanitized evidence and does not hide it behind an environment or timeout classification

#### Scenario: A valid observation does not converge

- **WHEN** prerequisites remain valid but a named observable state does not arrive within its declared bound
- **THEN** the run reports a `timeout` failure under the original operation identity without issuing a replacement mutation
