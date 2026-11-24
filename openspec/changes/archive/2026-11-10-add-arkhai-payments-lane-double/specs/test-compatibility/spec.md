## ADDED Requirements

### Requirement: Lanes run a mediation double that answers from programmed rules

Every lane MUST run a mediation double, recommended by the lane's registries, that reproduces the dispute authority's API mechanics — authentication, idempotency, the filing's admission checks, signed per-agreement records and cursors, the respondent listing, the closed-case refusal, extensions at the payments double, execution of a ruling's per-part `reverse` effects and the record of its delivery end — and takes every ruling from a scenario-programmed rule. It MUST NOT compute a ruling, and with no matching rule it MUST rule nothing. It MUST refuse at install, and install nothing for, a rule whose ruling carries a `stop` or `penalty` effect, which act on rate parts no lane running the double has, or an `award`, which the contract makes unexecutable on `arkhai.payments.v1`.

#### Scenario: A case is filed with no rule installed

- **WHEN** a party files a case and no rule matches it
- **THEN** the double accepts the filing, sends `extend` for each part to the payments double as the authority's own account, and reports each part `held` with its reference, or, when payments refuses it as nothing held, `not_held` with a reason classified from the part's signed amounts: `paid_out` when any money was released, otherwise `reversed` when any was reversed or refunded, otherwise `nothing_held`
- **AND** the case stays open and unruled, unless every part is `not_held`, when the contract's automatic dismissal closes it with nothing held

#### Scenario: A filing's Agreement is not the payment's

- **WHEN** a party files a case whose Agreement's JCS SHA-256 differs from the `deal` in the transaction's signed payment receipt
- **THEN** the double rejects the filing with `agreement_hash_mismatch`, reserves no case, and extends no part

#### Scenario: Protection cannot be established

- **WHEN** the payments double refuses an extend for any reason but nothing held, or cannot be reached
- **THEN** the filing is answered `error` with `protection_incomplete`, no part is reported `not_held`, and a retry under the same key completes the filing once payments answers

#### Scenario: A programmed ruling is applied

- **WHEN** a rule supplies a ruling's basis, delivery end and per-part effects for a matching case
- **THEN** the double records the ruling in the signed per-agreement record, applies each effect at the payments double with a stable effect key and the case reference, and then lifts only that case's extensions

#### Scenario: A ruling waits at its gate

- **WHEN** a rule's ruling with a delivery end and a reverse is held at its gate
- **THEN** the double records the ruled entry with the delivery end and the reverse `prepared`, sends nothing to payments, and applies both, lifts the case's extensions and closes the case only once the rule is resumed

#### Scenario: Payments fails between two effects

- **WHEN** the payments double refuses or drops a ruling's second effect after the first committed
- **THEN** the ruling is recorded as incompletely applied, and resuming applies the remaining effect without applying the first twice

#### Scenario: Closing a case still applying its ruling is refused

- **WHEN** a scenario closes a case whose ruling has an effect payments has not applied
- **THEN** the double refuses the close, lifts nothing, and the case stays applying with its effect prepared

#### Scenario: Appends follow the contract

- **WHEN** either party appends evidence to an open case, or the payer appends concurrence, or anyone appends to a closed case
- **THEN** the evidence is recorded under its actor and idempotency key, the payer's concurrence is refused because only `mandate.to` may concur, and the closed case refuses the append

#### Scenario: A party reads after an absence

- **WHEN** a party reads an agreement's record from its retained cursor
- **THEN** it receives the signed entries after that cursor in sequence, an authorized party reading an agreement with no cases receives an empty signed page, and an unknown agreement or unauthorized reader receives the contract's refusal

#### Scenario: The double's deviation is stated

- **WHEN** a payee files, or concurs in, a `delivery_end` claim that the dispute authority would rule mechanically
- **THEN** the double rules it only when a rule says so, and its README and this specification state that deviation from its producer

### Requirement: Lane double controls are typed deterministic steps

Both doubles MUST offer controls through one typed contract and client, shared with the end-to-end harness: when→then rules with refusals and transport faults, the mediation double's filing overrides, rulings, effects gate, operator decisions, closes and case listing, the payments double's funding and receipt-signer rotation, and rule listings. Controls MUST be lane-private, authenticated by a fixture token, and each MUST act only when the scenario advances it. Transport faults MUST apply only to the contract's API routes, never to the control routes. Every rule MUST state its `match`, and an unavailable rule MUST state `match: {}` and covers every contract API route. A control MUST refuse an unknown or malformed target with a typed code and install nothing. Each control the VM controls scenarios do not exercise — funding, signer rotation, refusal with a published code, the filing-answer override, close without ruling and the rule listing — MUST be proven by its double's suite through the typed client over HTTP.

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

#### Scenario: A scenario leaves a rule behind

- **WHEN** a module ends with a rule still installed
- **THEN** the rule listing shows it with its matched and waiting counts

### Requirement: Each lane double reads a perceived clock the scenario advances

Each double MUST evaluate time from a perceived clock, wall time plus an offset that only a control moves: forward by an advance, or back to a zero offset by a reset. One harness helper MUST advance both doubles together, and its fixture's finaliser MUST reset both whatever the module's outcome; each double's status MUST report its perceived now. A lane's clock MUST live only in that lane's own doubles. Due authority state MUST become visible at the next read, with no background work.

#### Scenario: A once part's hold is passed

- **WHEN** a scenario advances both doubles' clocks past a once part's release instant
- **THEN** the next read shows the part paid out, and a case the buyer files afterwards reports that part `not_held` with `paid_out` and is dismissed with nothing held, with no storefront step after the advance

#### Scenario: A module that advanced the clocks ends

- **WHEN** a module that advanced the doubles' clocks ends, whether it passed or failed
- **THEN** both doubles report wall time as their perceived now before the next module starts

#### Scenario: Lanes run side by side

- **WHEN** two lanes run at once, in separate Compose projects or separate Helm validation namespaces, and one advances its doubles' clocks
- **THEN** the other lane's doubles still report wall time

### Requirement: A lane-owned mediation target fails rather than skips

Each lane's runner MUST read its mediation target, CA bundle path, the buyer's mediation token and the control token from its committed lane profile, and the buyer MUST receive its token under the variable its dispute credential names. An unready lane-owned mediation target MUST fail setup by name; an unready external one MUST report a blocked skip.

#### Scenario: The lane's mediation double is not ready

- **WHEN** a lane's mediation target is marked its own and does not report itself ready
- **THEN** setup fails naming it, before any scenario stage

### Requirement: Controls scenarios prove the lane's dispute wiring in the VM lane

The VM lane MUST run exactly six controls scenarios, each a module of its own on its own once-only deal, that prove, end to end through the storefront's dispute servicing: a programmed ruling with a delivery end, an operator decision without one, a lost filing response, an unavailable mediation double, payments losing an effect's answer and then unavailable while a ruling is applied, and a clock advance past a hold. Each stage MUST advance one side effect through the services' typed clients, the doubles' control client, or the mediation kit's dispute adapter, never a raw HTTP call; where a scenario needs a case on a delivering deal, the harness MUST file it as the buyer through that adapter. A stage MUST NOT step the storefront's servicing while a ruling waits at its gate.

#### Scenario: A programmed ruling ends delivery

- **WHEN** the buyer files on a delivering deal, a gated rule's ruling with a delivery end and a reverse is resumed, and the storefront then steps its servicing
- **THEN** the payments double shows the reverse, and the storefront records the end with cause `ruling` and begins teardown

#### Scenario: An operator discount leaves the deal running

- **WHEN** the buyer files on a delivering deal, the storefront answers the case, and an operator decision reverses part of the held money with no delivery end
- **THEN** the reverse lands, the case's extensions are lifted, and delivery stays active

#### Scenario: A filing response is lost

- **WHEN** the response to the storefront's filing is dropped after commit and the storefront files again
- **THEN** the dispute adapter adopts the one filed case and no second case exists

#### Scenario: Mediation is unavailable while a deal runs

- **WHEN** mediation is unavailable while the storefront steps the servicing of a delivering deal with a case on record
- **THEN** it reports the authority unreachable and delivery stays active, and once the outage is removed its next step reads the authority again

#### Scenario: Payments holds a ruling before it completes

- **WHEN** payments loses its answer to the first of two reverses an operator decision rules, and is then unavailable while the decision is repeated
- **THEN** the storefront shows the ruling unapplied and the case not closed, and once payments answers, repeating the decision completes the ruling with exactly one reverse per effect

### Requirement: The in-lane payments double mirrors the service and proves its engine's surface

The VM, bare-metal and API-credit lanes MUST each run a payments double that wraps the payments kit's `PaymentsAuthority` engine and mirrors the payments service's HTTP API: its routes, bearer authentication, approval admission, read authorization, idempotency and error codes. The double MUST always sign `livemode: false`, MUST be reached over HTTPS under a lane CA the lane's callers trust through their configured CA bundle paths, and MUST hold only labelled public development fixtures. Its suite MUST prove the rate and hold surface its engine serves through the kit's real client. A lane result MUST be labelled lane-double evidence, never hosted-ledger, funding or live evidence.

#### Scenario: A lane's once-only payment scenario runs

- **WHEN** the bare-metal or API-credit lane runs its payment scenario
- **THEN** the scenario approves, receives a verified receipt and is refunded through the double, and does not skip

#### Scenario: The VM payment scenario runs

- **WHEN** the VM lane runs its payment scenario
- **THEN** it approves, receives a verified receipt, delivers, replays the commit and reaches servicing through the double, and its operator-end case and refund stages run against the lane's mediation double, without skipping

#### Scenario: An approval is retried after its mandate expires

- **WHEN** a payer repeats an approval the double has already made, after the mandate's expiry
- **THEN** the double returns the original receipt rather than refusing the mandate as expired

#### Scenario: The double mirrors a refusal

- **WHEN** a caller approves a mandate it is not the payer of, or reads a transaction or balance it may not read
- **THEN** the double refuses it with the payments service's status and error code

#### Scenario: The rate and hold surface is proven

- **WHEN** the double's suite drives rate parts, stops with notice, per-part ends, exhaustion, `afterStop` holds, partial reverses and `extend` and `lift` through the payments kit's client over HTTP
- **THEN** each answer and refusal is the engine's, and the earliest pending stop takes effect when the perceived clock reaches it

#### Scenario: A result against the double is reported

- **WHEN** a lane's payment scenario passes against the doubles
- **THEN** it is labelled lane-double evidence with each double's installed contract hashes, and establishes SCM's use of the boundaries, not either service's ledger, funding, adjudication or availability

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane against the lane doubles

The VM and bare-metal lanes MUST each run a buyer purchase that discovers, negotiates and
pays through the shipped buyer CLI (`market buy`, `market bare-metal buy`) in
`arkhai.payments.v1` against the lane's payments double, delivers through mock
provisioning, and ends: the VM lease through back-dating and a stepped lease-watchdog
cycle, the bare-metal lease through the buyer's `market bare-metal teardown`. The
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
  `market bare-metal teardown`
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

- **WHEN** the bare-metal buyer's teardown files a delivery-end case with the lane's
  mediation double and no rule matches it
- **THEN** the case is filed and each part reported held or not held, nothing is ruled,
  and the scenario does not read the filing as a ruling or refund

## REMOVED Requirements

### Requirement: The VM payment scenario's case stages need a mediation target

**Reason**: Every lane now runs a mediation double, so the VM payment scenario's case and refund stages run against it rather than skipping for want of a target.

**Migration**: "Lanes run a mediation double that answers from programmed rules" and "A lane-owned mediation target fails rather than skips" replace it; the VM stages' outcome is in "The in-lane payments double mirrors the service and proves its engine's surface".

### Requirement: Lanes run payment scenarios against an in-lane payments double

**Reason**: Its claim of only the once-only surface and its pinned unanswerable dispute authority no longer hold: the double's suite proves its engine's rate and hold surface, and the lanes pin the mediation double.

**Migration**: "The in-lane payments double mirrors the service and proves its engine's surface" carries its retained obligations; "Lanes run a mediation double that answers from programmed rules" replaces the pinned authority.

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane

**Reason**: Its bare-metal buyer's delivery-end filing now reaches the lane's mediation double instead of no authority.

**Migration**: "A compute buyer purchase settled through Arkhai payments runs in each compute lane against the lane doubles" carries every retained obligation and replaces the filing scenario.
