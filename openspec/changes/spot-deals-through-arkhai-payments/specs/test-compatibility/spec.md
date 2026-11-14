## ADDED Requirements

### Requirement: Rate mechanics qualification consumes the shared lane contract
Rate mechanics qualification MUST follow "External payment qualification names its target" and label each result lane-double evidence or live evidence, as "The in-lane payments double mirrors the service and proves its engine's surface" does. It MUST retain kit/vector and re-anchoring evidence production, while convergence owns rate-lane time and consuming scenarios. It MUST NOT add an evidence label or claim live behavior from a double.

#### Scenario: Mechanics run against the lane double
- **WHEN** rate adapter mechanics pass against contract fakes or the lane double
- **THEN** evidence is labelled lane-double evidence with the installed contract hashes and makes no hosted-readiness or live-authority claim

#### Scenario: Required authority vectors are absent
- **WHEN** producer-published signed pre-start/post-start snapshot, start or partial reversal vectors are unavailable
- **THEN** the corresponding authority-conformance claim remains unproven
- **AND** double-generated traces do not replace producer evidence

#### Scenario: The adapter is tested without lane services
- **WHEN** kit rate integration tests run
- **THEN** they exercise the shared clock-injected payments authority engine and verified vector fixtures without starting lane HTTP tooling

#### Scenario: Fixtures use the shipped presets with default buyers
- **WHEN** a spot or on-demand command fixture is prepared
- **THEN** it uses the shipped presets under a lane declaration listing returned, with a default buyer
- **AND** a charged variant is a separate observation whose buyer waives each charged term through its per-term waiver

### Requirement: A recurring purchase runs end to end in each compute lane
Each compute lane MUST run one recurring-purchase scenario from a lane-only servicing declaration listing charged and returned, through approval against the payments double, labelled lane-double evidence.

#### Scenario: A buyer approves a recurring option
- **WHEN** a buyer selects a seller's recurring option in a compute lane and approves its mandate
- **THEN** the scenario asserts the published per-period price, the buyer's pre-approval display of per-period charge, setup, initial reserve and maximum term, and the approved mandate's single rate part charging one period's price
- **AND** it asserts delivery is refused without the rate continuation

#### Scenario: Command first use precedes continuation
- **WHEN** adapter or notice first use succeeds before rate continuation is installed
- **THEN** evidence claims only command/authority mechanics and delivery refuses without the rate hook
- **AND** no both-lane release, due-work completion or hosted qualification is claimed

## MODIFIED Requirements

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target configured, the bare-metal lane MUST qualify one fixed-term whole-host purchase settled through `arkhai.payments.v1`: discovery, negotiation, payment approval, receipt-gated mock delivery, re-drive of the original run's settlement, the buyer's physical teardown through `market bare-metal end`, and seller refund, with the teardown and the refund as separate operations. Its discovery, purchase, correlation, delivery and teardown steps MUST be the shared buyer-purchase stages, and its re-drive and refund its own inserted stages. In the bare-metal lane the target is the lane's payments double, whose result is never hosted-ledger evidence. Mock access is evidence of composition, never of real SSH access or revocation. The scenario MUST leave no payment hold, allocated host, mock rule, or held loop behind, whether it passes or fails, except a payment it cannot refund, which it MUST report by its negotiation and transaction together with any host its seller may still deliver for it, and a host whose fulfillment it cannot read or tear down, which it MUST report as a failed cleanup step. Without a configured target, or with an unready external one, it MUST report a named blocked prerequisite; an unready lane-owned target MUST fail setup by name. It MUST never fall back to Alkahest or count an unrun purchase as qualification.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** the shared purchase stages discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, repeats the
  canonical lifecycle commit for the same negotiation, and requires the original
  transaction, fulfillment identity, and durable result
- **AND** the buyer requests physical teardown through `market bare-metal end`,
  converging mock reclaim, then the pinned seller separately refunds the payment, still
  held, before selected-site capacity release is confirmed

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup refunds the deal's payment if it is not already refunded,
  then reads the deal's fulfillment and tears down a host it finds not yet torn down,
  reading the deal's identifiers from the original run when the purchase command failed
- **AND** a host delivered while the refund was being requested is found and torn down,
  and one whose fulfillment cannot be read or torn down is reported as a failed step
- **AND** a refund the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  refund that still fails fails the scenario naming the negotiation and transaction
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal payment scenario runs with no payments target configured, or an unready external one
- **THEN** it reports a named blocked prerequisite and makes no purchase

#### Scenario: The lane's own payments target is unready

- **WHEN** the bare-metal lane's payments double is not ready
- **THEN** lane setup fails naming it, before any purchase

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane against the lane doubles

The VM and bare-metal lanes MUST each run a buyer purchase that discovers, negotiates and
pays through the shipped buyer CLI (`market buy`, `market bare-metal buy`) in
`arkhai.payments.v1` against the lane's payments double, delivers through mock
provisioning, and ends: the VM lease through back-dating and a stepped lease-watchdog
cycle, the bare-metal lease through the buyer's `market bare-metal end`. The
purchase stages MUST be defined once and shared by every scenario that buys this way,
and each stage MUST log the identifiers it reads. The bare-metal lane's purchase is its
qualified payment purchase, which runs the shared stages and inserts its own; the VM
lane's purchase lists a resource of its own on a registered host, since a listing's
binding to its resource outlives the listing.

#### Scenario: A VM lane purchase completes

- **WHEN** the VM lane runs its buyer purchase
- **THEN** `market buy` approves the payment, the seller delivers after a verified
  receipt, and back-dating the lease and stepping one watchdog cycle tears the guest down
  and releases its capacity

#### Scenario: A bare-metal lane purchase ends by the buyer

- **WHEN** the bare-metal lane runs its buyer purchase and the buyer runs
  `market bare-metal end`
- **THEN** the reclaim runs and the whole host's capacity is restored

#### Scenario: The bare-metal purchase's steps change

- **WHEN** a discovery, purchase, correlation, delivery or buyer-teardown step of the
  bare-metal lane's purchase changes
- **THEN** it changes in the shared stage, and the observation 4 and 5 module runs the
  changed stage without an edit of its own

#### Scenario: A purchase is checked against its payment records

- **WHEN** a buyer purchase completes
- **THEN** each transaction is bound to its Agreement, its receipt covers that mandate,
  its snapshot names the configured payer and payee with gross equal to the Agreement's
  price, and the payer's available balance fell by exactly the scenario's own debits

#### Scenario: The buyer's delivery-end filing reaches the mediation double

- **WHEN** the bare-metal buyer's end files a delivery-end case with the lane's
  mediation double and no rule matches it
- **THEN** the case is filed and each part reported held or not held, nothing is ruled,
  and the scenario does not read the filing as a ruling or refund
