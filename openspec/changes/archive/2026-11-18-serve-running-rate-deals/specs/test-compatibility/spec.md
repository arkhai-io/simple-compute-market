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

### Requirement: Lane double controls are typed deterministic steps

Both doubles MUST offer controls through one typed contract and client, shared with the end-to-end harness: when→then rules with refusals and transport faults, the mediation double's filing overrides, rulings, effects gate, operator decisions, closes and case listing, the payments double's funding, receipt-signer rotation and rate-part reservation, and rule listings. Controls MUST be lane-private, authenticated by a fixture token, and each MUST act only when the scenario advances it. The payments double MUST reserve a started rate part's further periods only when its reservation control is called, never on its own: the control reserves each of the transaction's running rate parts — started and not stopped — through the instant the scenario names, as far as the part's end and the payer's balance allow, and answers, for each such part, the instant it is then reserved through. The control MUST refuse a transaction with no running rate part with a typed code and change nothing. Transport faults MUST apply only to the contract's API routes, never to the control routes. Every rule MUST state its `match`, and an unavailable rule MUST state `match: {}` and covers every contract API route. A control MUST refuse an unknown or malformed target with a typed code and install nothing. Each control the VM controls scenarios do not exercise — funding, signer rotation, refusal with a published code, the filing-answer override, close without ruling and the rule listing — MUST be proven by its double's suite through the typed client over HTTP, and so MUST the reservation control.

#### Scenario: A response is lost after commit

- **WHEN** a drop-after-commit rule matches a request
- **THEN** the double commits the request and abandons its response, the caller sees a transport error, and a retry under the same key returns the original result without a second effect

#### Scenario: A double is unavailable

- **WHEN** an unavailable rule with `match: {}` is installed on a double
- **THEN** every API request's response is abandoned and its callers see a transport error, never an HTTP error status
- **AND** the control routes still answer, and removing the rule restores the API

#### Scenario: An unavailable rule is scoped

- **WHEN** a scenario installs an unavailable rule whose `match` is not empty
- **THEN** the double refuses it as an invalid request and installs nothing

#### Scenario: A rule states no scope

- **WHEN** a scenario installs a rule without `match`
- **THEN** the double refuses it as an invalid request and installs nothing

#### Scenario: A finaliser removes rules

- **WHEN** a scenario deletes a rule that has matched or completed, and then deletes a rule that does not exist
- **THEN** the first is removed from the listing, and the second is reported not found

#### Scenario: A call is refused with a published code

- **WHEN** the payments double's suite installs a refusal rule and calls the matching route through the payments kit's client
- **THEN** the client receives the rule's published status and code, and the rule listing counts the match

#### Scenario: An account is funded

- **WHEN** the payments double's suite funds an account through the typed client
- **THEN** the account's balance read through the payments kit's client shows the funding

#### Scenario: A rate part's further periods are reserved

- **GIVEN** a started rate part whose payer's balance funds one period beyond its first reservation
- **WHEN** the payments double's suite calls the reservation control through the typed client, naming the Agreement's end
- **THEN** the control answers the part reserved through one period past its first reservation, and the transaction's signed snapshot through the payments kit's client shows that instant as its funded boundary
- **AND** with injected time set to that boundary, the next read shows the part's `terms` stop there

#### Scenario: A reservation is refused when no rate part runs

- **WHEN** the payments double's suite calls the reservation control through the typed client for a transaction whose rate part has not started, then for one whose only part is once-only, then for one whose rate part has stopped
- **THEN** each call is refused with the code `no_running_rate_part`, and the transaction's signed snapshot through the payments kit's client is unchanged

#### Scenario: A rate part is not reserved unasked

- **WHEN** the payments double's injected time is set past a started rate part's first reservation and no reservation control was called
- **THEN** the next read shows the part's `terms` stop at its first reservation's end, whatever the payer's balance

#### Scenario: A scenario leaves a rule behind

- **WHEN** a module ends with a rule still installed
- **THEN** the rule listing shows it with its matched and waiting counts

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
Each compute lane MUST run, each on its own deal, under the shipped presets with a default buyer and a lane declaration listing charged and returned: funds running out, where the rate part's `terms` stop ends delivery at its effective time and is classified exhaustion; a spot seller's preemption, where the payments double holds the pending stop and the deal ends when it takes effect with the unstarted period returned; and the maximum term, where the rate part ends at the Agreement's end with `returned` and is classified the term end. Each row MUST reach its instants by setting lane time, never by waiting, and MUST be labelled lane-double evidence. A row that sets lane time past its deal's first reservation MUST first program the payments double's further reservation through its control, as the payments service's own scheduler would have reserved, in a stage of its own declared only where the double runs.

#### Scenario: Funds run out
- **GIVEN** a delivered on-demand deal whose payer balance funds one period beyond the part's first reservation
- **WHEN** the scenario reserves the part through the Agreement's end, sets lane time to the funded boundary the payments double then reports, and steps `deal-servicing`
- **THEN** the payments double records a `terms` stop at that boundary, after the first reservation's end and before the Agreement's end, the storefront classifies it exhaustion and tears the deal down at that instant, and the buyer's read says a top-up cannot revive it

#### Scenario: A spot seller preempts with notice
- **GIVEN** a delivered spot deal
- **WHEN** the seller runs `deals preempt`, the scenario sets lane time to the request's time plus the Agreement's seller notice and steps `deal-servicing`
- **THEN** the payments double held the pending stop until then, the storefront records the seller's entitled stop at its effective time and tears the deal down, and the unstarted period is returned

#### Scenario: The maximum term ends
- **GIVEN** a delivered on-demand deal whose payer balance funds the whole term
- **WHEN** the scenario reserves the part through the Agreement's end, sets lane time to the Agreement's end and steps `deal-servicing`
- **THEN** the rate part ends with `returned`, the storefront classifies the end as the term end, not exhaustion, and tears the deal down

### Requirement: The buyer's watchdog is qualified against a delivered deal
Each compute lane MUST run the buyer's watchdog against a delivered rate deal: the shipped `buy` with the opt-in monitoring from `available`; a killed command whose read shows `unmonitored` once lane time passes its last probe's staleness bound; the resumed run whose read shows `monitored`; and the disclosed endpoint ceasing to accept connections while the storefront's loops are paused, which yields one buyer stop. The shipped `buy`, its resume and the buyer's read MUST run in the harness's process, the deal's probe answering and every wait `buy` makes — its commit, its wait for the deal to become available and the watchdog's — stepped as the harness programs them through each buyer CLI's own probe and wait-clock factories, so that no probe leaves the harness, no case waits on real time, and nothing test-only ships with the CLI. Staleness MUST be reached by setting lane time. Each case MUST be labelled lane-double evidence.

#### Scenario: A watched purchase is monitored, goes stale when killed, and resumes
- **GIVEN** a rate deal whose `buy` runs in the harness's process with the watchdog opted in, waiting at the harness's gate for the deal to become available, its probe programmed to answer reachable
- **WHEN** the scenario sets lane time to the Agreement's start and steps delivery recovery, and the harness releases `buy`'s wait and steps one probe interval
- **THEN** the same command enters its watchdog, the buyer's read shows `monitored`, and the probe was built for the endpoint the deal disclosed
- **AND** after the harness interrupts the command and sets lane time past one interval, the probe timeout and the grace after its last probe, the read shows `unmonitored`
- **AND** after the buyer resumes the run and the harness steps one probe interval, the read shows `monitored`

#### Scenario: Access is lost while the storefront is paused
- **GIVEN** the resumed run of a delivered rate deal, and the storefront's loops paused
- **WHEN** the probe answers unreachable for the threshold of stepped intervals
- **THEN** the watchdog sends one payer stop and hint, which the payments double accepts, and the command exits with the outcome `stopped`
- **AND** the payments double's events for the transaction are the storefront's `start` and then the payer's stop, with nothing from the storefront between
- **AND** the storefront records the buyer's stop with no filing, and once the scenario steps `deal-servicing` the deal's teardown has begun
