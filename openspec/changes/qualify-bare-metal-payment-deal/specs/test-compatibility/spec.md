## ADDED Requirements

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target configured, the bare-metal lane MUST qualify one fixed-term whole-host purchase settled through `arkhai.payments.v1`: discovery, negotiation, payment approval, receipt-gated mock delivery, re-drive of the original run's settlement, seller refund, and physical teardown, with the refund and the teardown as separate operations. Mock access is evidence of composition, never of real SSH access or revocation. The scenario MUST leave no payment hold, allocated host, mock rule, or held loop behind, whether it passes or fails, except a payment it cannot refund, which it MUST report by its negotiation and transaction. Without a configured, ready target it MUST report a named blocked prerequisite, never fall back to Alkahest or count as qualification.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** three ordered calls discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, re-drives
  the same negotiation through `SyncStorefrontClient.settle_agreement`, and requires
  the original transaction, fulfillment identity, and durable result
- **AND** the pinned seller refunds the held payment and the buyer separately
  requests physical teardown, converging mock reclaim and selected-site capacity release

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup refunds the deal's payment if it is not already refunded
  and tears down its fulfillment if one exists and is not already torn down, reading the
  deal's identifiers from the original run when the purchase command failed
- **AND** a refund the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  refund that still fails fails the scenario naming the negotiation and transaction
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal payment scenario runs with no payments target configured, or an unready one
- **THEN** it reports a named blocked prerequisite and makes no purchase
