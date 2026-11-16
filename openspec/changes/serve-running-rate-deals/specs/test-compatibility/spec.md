## MODIFIED Requirements

### Requirement: Rate mechanics qualification consumes the shared lane contract
Rate mechanics qualification MUST follow "External payment qualification names its target" and label each result lane-double evidence or live evidence, as "The in-lane payments double mirrors the service and proves its engine's surface" does. It MUST retain kit/vector evidence production, while the rate lane rows consume the lane's shared lane time. It MUST NOT add an evidence label or claim live behavior from a double.

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

## REMOVED Requirements

### Requirement: A recurring purchase runs end to end in each compute lane

**Reason**: Its scenarios of a commit refused by end service and a refused deal ended by the buyer's stop, and its first-use scenario claiming end service refuses a rate deal, end with this change: the recurring purchase is now delivered.

**Migration**: "A recurring purchase is delivered end to end in each compute lane" keeps the approval scenario and the lane's clean-up rule, and runs the purchase to a delivered deal ended by the buyer's own stop on lane time.

## ADDED Requirements

### Requirement: A recurring purchase is delivered end to end in each compute lane
Each compute lane MUST run one recurring-purchase scenario from a lane-only servicing declaration listing charged and returned, through the shipped buyer's approval and commit against the payments double, to a delivered deal the buyer ends by its own stop, labelled lane-double evidence. It MUST reach each instant by setting lane time and MUST leave no payment hold, mock rule or held loop behind.

#### Scenario: A buyer approves a recurring option
- **WHEN** a buyer selects a seller's recurring option in a compute lane and approves its mandate
- **THEN** the scenario asserts the published per-period price, the accepted Agreement's per-period charge, setup, initial reserve and maximum term as the buyer displays them, and the approved mandate's single rate part charging one period's price
- **AND** that the buyer displays them before its settlement stage approves is proved by each buyer's own application tests, not by the lane scenario

#### Scenario: The deal is delivered and billing starts
- **WHEN** the scenario sets lane time to the Agreement's start and steps delivery recovery
- **THEN** the site activates the lease, the payments double records the rate part's start after that activation, and the deal becomes available to the buyer

#### Scenario: The buyer's stop ends the delivered deal
- **WHEN** the scenario's buyer ends the delivered deal through its canonical `end` and the scenario steps `deal-servicing`
- **THEN** the payer's stop is accepted at the payments double, the started period is charged, the storefront records the buyer's entitled stop and tears the deal down, and the seller's list shows the deal `ended` once the release is proven

### Requirement: Rate deals are qualified in both compute lanes on lane time
Each compute lane MUST run, each on its own deal, under the shipped presets with a default buyer and a lane declaration listing charged and returned: funds running out, where the rate part's `terms` stop ends delivery at its effective time and is classified exhaustion; a spot seller's preemption, where the payments double holds the pending stop and the deal ends when it takes effect with the unstarted period returned; and the maximum term, where the rate part ends at the Agreement's end with `returned` and is classified the term end. Each row MUST reach its instants by setting lane time, never by waiting, and MUST be labelled lane-double evidence.

#### Scenario: Funds run out
- **GIVEN** a delivered on-demand deal whose payer balance funds two periods
- **WHEN** the scenario sets lane time past the second period's end and steps `deal-servicing`
- **THEN** the payments double records a `terms` stop at the funded boundary, the storefront classifies it exhaustion and tears the deal down at that instant, and the buyer's read says a top-up cannot revive it

#### Scenario: A spot seller preempts with notice
- **GIVEN** a delivered spot deal
- **WHEN** the seller runs `deals preempt`, the scenario sets lane time to the request's time plus the Agreement's seller notice and steps `deal-servicing`
- **THEN** the payments double held the pending stop until then, the storefront records the seller's entitled stop at its effective time and tears the deal down, and the unstarted period is returned

#### Scenario: The maximum term ends
- **GIVEN** a delivered on-demand deal
- **WHEN** the scenario sets lane time to the Agreement's end and steps `deal-servicing`
- **THEN** the rate part ends with `returned`, the storefront classifies the end as the term end, not exhaustion, and tears the deal down

### Requirement: The buyer's watchdog is qualified against a delivered deal
Each compute lane MUST run the buyer's watchdog against a delivered rate deal on lane time: the shipped `buy` with the opt-in monitoring from `available`; the disclosed endpoint ceasing to accept connections while the storefront is stopped, which yields one buyer stop; a killed command whose read shows `unmonitored` once lane time passes its last probe's staleness bound; and the resumed run whose read shows `monitored`. Each case MUST be labelled lane-double evidence.

#### Scenario: Access is lost while the storefront is stopped
- **GIVEN** a delivered rate deal whose `buy` runs with the watchdog opted in
- **WHEN** the storefront is stopped and the disclosed endpoint stops accepting connections for the threshold of probes
- **THEN** the watchdog sends one payer stop, which the payments double accepts, and exits

#### Scenario: A killed command goes stale and resumes
- **GIVEN** a delivered rate deal whose opted-in `buy` command was killed after a passing probe
- **WHEN** the scenario sets lane time past one interval, the probe timeout and the grace after that probe, and the buyer reads the deal
- **THEN** the read shows `unmonitored`
- **AND** after the buyer resumes the run and it records a probe, the read shows `monitored`
