## ADDED Requirements

### Requirement: Consumer-owned hosted settlement system evidence

The marketplace repository MUST own the scenario code that proves a released hosted authority composes with marketplace publication, negotiation, buyer orchestration, VM fulfillment, settlement servicing, and recovery. The scenario MUST exercise the authority through its released client and network contracts and MUST NOT import, mount, or package hosted service source.

#### Scenario: Hosted lifecycle suite is assembled locally

- **WHEN** an authorized developer supplies compatible signed hosted E2E artifacts and starts the hosted system suite
- **THEN** marketplace-owned stages drive the registry, storefront, buyer, provisioning, and settlement boundaries against the locally composed authority without a remote Arkhai deployment or checkout-relative service import

#### Scenario: Hosted repository verifies its own release

- **WHEN** the hosted producer runs service/client conformance
- **THEN** no hosted package or lasting hosted test imports a marketplace or market-domain package

### Requirement: Deterministic hermetic lifecycle coverage

The selected hermetic hosted suite MUST control financial outcomes and time through the versioned private E2E contract, wait on observable state rather than sleeps, and assert stable operation identities and exactly-once provider effects across duplicate delivery, uncertain acknowledgement, process restart, and reconciliation. It MUST cover successful collection, eligible pre-transfer reclaim, lost and duplicate webhook recovery, and accepted-mechanism recovery without claiming Stripe compatibility.

#### Scenario: Transfer acknowledgement is lost

- **WHEN** the simulator records a transfer but returns an unknown acknowledgement and the authority worker restarts
- **THEN** marketplace recovery retains the accepted `fiat.stripe.v1` obligation and stable operation reference, the authority converges to collected, and effect inspection reports exactly one transfer

#### Scenario: Paid escrow reaches expiry before transfer

- **WHEN** the condition remains unsatisfied and the harness advances its controlled clock beyond the accepted expiry
- **THEN** reclaim converges through the ordinary marketplace and authority recovery paths with exactly one refund and no transfer

### Requirement: Explicit staged state and failure attribution

Hosted system stages MUST name every produced and consumed state field, fail at the boundary whose observable contract is violated, and report unavailable private artifacts, incompatible manifests, failed readiness, missing buyer action, and absent provider effects distinctly. A user who explicitly selects the hosted suite MUST receive a prerequisite failure rather than a silent skip when private inputs are absent.

#### Scenario: Private simulator artifact is unavailable

- **WHEN** a developer explicitly invokes the hermetic hosted target without its signed simulator image or manifest
- **THEN** setup fails before marketplace startup with the missing artifact identity and acquisition prerequisite, while the default public test selection remains unaffected

#### Scenario: Authority reports the wrong manifest

- **WHEN** the local authority ready response does not match the supplied signed release
- **THEN** the composition stage fails before publication or payment creation and no floating image tag is accepted

### Requirement: Separate real-provider compatibility evidence

A protected, opt-in real-provider lane MUST run the local marketplace topology against Stripe test mode, real Checkout, verified webhook delivery, connected-account readiness, and authoritative provider retrieval. Its result MUST be reported separately from hermetic evidence, and unavailable credentials or external endpoints MUST be disclosed rather than simulated.

#### Scenario: Real Stripe collection succeeds

- **WHEN** protected CI or an authorized developer completes a test-mode Checkout and the VM fulfillment condition becomes satisfied
- **THEN** the ordinary worker converges to collected and evidence identifies one matching Checkout, one destination transfer, the expected amount/currency, transfer group, source transaction, and marketplace operation identity

#### Scenario: Fork pull request runs public checks

- **WHEN** untrusted pull-request code executes repository CI
- **THEN** no private registry, simulator, release-signing, connected-account, webhook, or Stripe credential is provided and the ordinary public suite completes without hosted artifacts

### Requirement: Condition profiles remain independent

Wallet-free hosted system evidence MUST use portable non-EVM conditions without constructing a wallet, RPC client, chain signer, or EAS deployment. Local EAS/arbiter conformance MUST be a separately selectable profile so financial lifecycle and EVM condition failures remain attributable to their owning boundary.

#### Scenario: Wallet-free hosted suite runs

- **WHEN** the hermetic or real-Stripe hosted profile selects a portable condition
- **THEN** publication, negotiation, funding, fulfillment, and terminal settlement complete with wallet and chain configuration absent
