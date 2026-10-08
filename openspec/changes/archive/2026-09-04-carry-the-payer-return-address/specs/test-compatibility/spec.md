## MODIFIED Requirements

### Requirement: Stripe-backed hosted settlement system evidence

The marketplace-owner wallet-free VM lifecycle against Stripe test mode MUST verify one exact signed hosted release at the producer boundary and one exact marketplace consumer release, then exercise ordinary marketplace publication, discovery, negotiation, accepted funding authorization, hosted materialization, buyer action, authoritative funding, VM fulfillment evidence, condition evaluation, collection or eligible reclaim, status, restart, and recovery for each selected exact profile. The report MUST record marketplace source/commit separately from hosted manifest, client wheel, service image, contract/schema, migrations, provenance, release repository/workflow/ref/source, capability set, and protected workflow run. Every provider assertion MUST derive from the selected profile's supported Stripe test-mode behavior; unavailable external prerequisites MUST remain explicit and MUST NOT be replaced by local simulation.

How a saved instrument becomes ready MUST follow the bound release rather than the harness. Where the bound release declares direct payer instrument setup, a bank-funded saved-instrument lane MUST complete its setup by submitting the payer's own verification evidence and MUST NOT require a browser. Where it does not, the existing interactive setup path MUST stand unchanged. A profile for which the bound release offers no saved-instrument path at all MUST be reported as an unavailable prerequisite, not as a failure of the lane.

#### Scenario: Successful `card.v1` purchase

- **WHEN** Chromium completes required card interaction and hosted retrieval proves accepted funding and transfer outcomes
- **THEN** the report records one signed marketplace-to-storefront-to-hosted lifecycle with exact artifact identities and sanitized payment/transfer evidence

#### Scenario: Successful `us_bank_transfer.v1` purchase

- **WHEN** the test uses issued instructions and attributable test funds through the configured supported Stripe test path
- **THEN** the report records awaiting-payment, authoritative funding, fulfillment, and collection boundaries without storing bank instructions or provider IDs

#### Scenario: Successful `us_ach_debit.v1` purchase

- **WHEN** the exact test debit crosses mandate/confirmation and availability gates
- **THEN** the report records delayed state, authoritative funding, fulfillment, and collection or declared return/reclaim boundary without claiming card behavior

#### Scenario: A bank-funded saved instrument is set up without a browser

- **WHEN** the bound release declares direct payer instrument setup and a saved-instrument lane selects a bank-funded profile
- **THEN** the lane submits the payer's own verification evidence, the instrument becomes ready without a browser session, and the report records the setup boundary without the submitted evidence or any provider identifier

#### Scenario: The bound release predates direct setup

- **WHEN** a saved-instrument lane runs against a bound release that does not declare direct payer instrument setup
- **THEN** the interactive setup path runs exactly as it does today, and the lane's recorded evidence is unchanged

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

#### Scenario: A bank-transfer reclaim supplies a payer return address

- **WHEN** a `us_bank_transfer.v1` obligation funded in test mode reaches eligible pre-transfer reclaim and the bound release declares payer return instructions
- **THEN** the buyer's reclaim supplies a return address the run is entitled to use, the authority accepts the return as in flight, and the report records the reclaim boundary without the address or any provider identifier

#### Scenario: A bank-transfer reclaim without an address is reported as refused

- **WHEN** a `us_bank_transfer.v1` reclaim lane supplies no return address
- **THEN** the run reports the authority's own refusal naming the missing input, and does not consume a retry deadline or report a convergence timeout
