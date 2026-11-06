## ADDED Requirements

### Requirement: Lanes run payment scenarios against an in-lane payments double

The VM, bare-metal and API-credit lanes MUST each run a payments double that wraps the payments kit's `PaymentsAuthority` engine and mirrors the payments service's HTTP API: its routes, bearer authentication, approval admission, read authorization, idempotency and error codes. The double MUST always sign `livemode: false`, MUST be reached over HTTPS under a lane CA the lane's callers trust through their payments configuration's CA bundle path, and MUST hold only labelled public development fixtures. Its suite and documentation MUST claim only the once-only surface; passing against it MUST NOT be reported as hosted-ledger, funding or live evidence.

#### Scenario: A lane's once-only payment scenario runs

- **WHEN** the bare-metal or API-credit lane runs its payment scenario
- **THEN** the scenario approves, receives a verified receipt and is refunded through the double, and does not skip

#### Scenario: The VM payment scenario's once-only stages run

- **WHEN** the VM lane runs its payment scenario's once-only stages
- **THEN** they approve, receive a verified receipt, deliver, replay the commit and reach servicing through the double without skipping, and the held payment stays in the double until the lane ends

#### Scenario: An approval is retried after its mandate expires

- **WHEN** a payer repeats an approval the double has already made, after the mandate's expiry
- **THEN** the double returns the original receipt rather than refusing the mandate as expired

#### Scenario: The double mirrors a refusal

- **WHEN** a caller approves a mandate it is not the payer of, or reads a transaction or balance it may not read
- **THEN** the double refuses it with the payments service's status and error code

#### Scenario: The pinned dispute authority cannot answer

- **WHEN** a lane's registries recommend the lane's dispute authority
- **THEN** its origin is under `.invalid`, its record key has no usable private half, and its account has no bearer token at the double

#### Scenario: A result against the double is reported

- **WHEN** a lane's payment scenario passes against the double
- **THEN** the result establishes SCM's use of the payments boundary, not the payments service's ledger, funding or availability

### Requirement: The VM payment scenario's case stages need a mediation target

The VM payment scenario's stages that need a dispute authority to accept a filed case MUST report a blocked skip naming the missing mediation target when none is configured, while its once-only stages run against the configured payments target. The VM lane's storefront MUST hold an identity-bound dispute credential for the pinned dispute authority, a labelled public development value, so that servicing reports the deal `running` while that authority cannot be reached.

#### Scenario: The VM lane has no mediation target

- **WHEN** the VM lane runs its payment scenario with the lane's payments double and no mediation target
- **THEN** the commit, delivery, replay and servicing stages run, servicing reporting the deal `running`, and the operator-end case and refund stages report a blocked skip naming the mediation target

### Requirement: A lane's runner reads committed lane profiles

Each lane MUST run its test runner under committed profiles: a shared payments profile holding the lane double's target, accounts, CA bundle path and buyer credentials, then a profile of the lane's own holding only what differs by lane, selected by the lane target's choice of profiles. The runner's environment MUST carry no payments setting or credential. The buyer's payments token MUST reach the buyer process under the variable the payments settings name, written by the harness from its resolved settings. Every value a lane profile restates from a fixture or identity file MUST be held to it by a test.

#### Scenario: A lane runs its payment scenario

- **WHEN** a lane target runs its markers against its stack
- **THEN** the runner loads the shared payments profile and the lane's own profile, and the payment scenario reaches the double with the configured CA and the buyer's token

#### Scenario: A run selects no lane profile

- **WHEN** the runner runs with no lane profile selected
- **THEN** it has no payments target, and the payment scenarios report their blocked prerequisite

#### Scenario: A restated value drifts from its fixture

- **WHEN** a lane profile states a token, account or key that differs from the fixture or identity file it restates
- **THEN** a repository test fails naming both

## MODIFIED Requirements

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision and check readiness before mutations. Unavailable external prerequisites MUST report blocked/unrun; a configured lane missing required settings, or a lane-owned payments target failing readiness, MUST fail setup by name before scenarios. Neither MUST substitute another mechanism.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: A configured payments run lacks a buyer credential

- **WHEN** a payments target is configured but the buyer's marketplace credential is not
- **THEN** the payment scenario fails naming the missing setting, before mutations rather than disguising a configured-target setup failure as an unavailable external prerequisite

#### Scenario: A lane-owned payments target is not ready

- **WHEN** a lane's settings mark its payments target as the lane's own and the target, or a storefront's authenticated payments check, is not ready
- **THEN** lane setup or the scenario fails naming the target, rather than reporting a blocked skip

#### Scenario: An external payments target is not ready

- **WHEN** a configured external payments target does not report itself ready
- **THEN** the payment scenario reports a blocked skip naming the target and makes no purchase

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target configured, the bare-metal lane MUST qualify one fixed-term whole-host purchase settled through `arkhai.payments.v1`: discovery, negotiation, payment approval, receipt-gated mock delivery, re-drive of the original run's settlement, seller refund, and physical teardown, with the refund and the teardown as separate operations. In the bare-metal lane the target is the lane's payments double, whose result is never hosted-ledger evidence. Mock access is evidence of composition, never of real SSH access or revocation. The scenario MUST leave no payment hold, allocated host, mock rule, or held loop behind, whether it passes or fails, except a payment it cannot refund, which it MUST report by its negotiation and transaction together with any host its seller may still deliver for it, and a host whose fulfillment it cannot read or tear down, which it MUST report as a failed cleanup step. Without a configured target, or with an unready external one, it MUST report a named blocked prerequisite; an unready lane-owned target MUST fail setup by name. It MUST never fall back to Alkahest or count an unrun purchase as qualification.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** three ordered calls discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, repeats the
  canonical lifecycle commit for the same negotiation, and requires the original
  transaction, fulfillment identity, and durable result
- **AND** the pinned seller refunds the held payment and the buyer separately
  requests physical teardown, converging mock reclaim and selected-site capacity release

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
