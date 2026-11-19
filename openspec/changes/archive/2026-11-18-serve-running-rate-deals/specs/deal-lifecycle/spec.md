## REMOVED Requirements

### Requirement: Neutral delivery decisions delegate payment interpretation

**Reason**: Its refusal to commit a deal that is not once-only, and the three scenarios of a deal refused at commit, end with this change: end service asks the payment adapter for every deal, and a changed answer at an unchanged revision is held pending instead.

**Migration**: "Delivery authorization delegates payment interpretation" keeps the protocol, the deadline barrier and the remaining scenarios, drops the refusal and its code, and adds the changed-answer rule. No released storefront made the refusal (`marketplace-v0.3.0`), so no refused deal is recovered.

### Requirement: Stop requests are distinct from final stops, readable by released clients

**Reason**: Its omission of an empty `parts` and a null `settles_through` from the lifecycle read and list, and its scenario of a contracts 0.1.0 client validating a once-only deal, end with this change: a client released earlier is not owed reading a later storefront, and the lifecycle contracts take an incompatible version.

**Migration**: "Stop requests are distinct from final stops" keeps the rule and its two remaining scenarios. The client shipped with the storefront reads every deal shape ("The seller half lists deals"); a 0.1.0 client upgrades with the storefront.

## ADDED Requirements

### Requirement: Stop requests are distinct from final stops

A raw stop request MUST NOT end delivery. The lifecycle contracts MUST carry each part's verified rate bounds and its pending and final stops (`PaymentPartObservation`, `AuthorityView.parts`) and a payment event's treatment (`PaymentEvent.settles_through`). Because notice maturity can carry no new event sequence, the watch MUST read each part's final stop outside its event cursor and record it once by authority record, refusing a replay that changes the recorded end. The lifecycle read and list MUST carry every field of their models, defaults included.

#### Scenario: A stop request is pending

- **WHEN** the authority records a stop request effective in the future
- **THEN** the watch records no end, and read exposes the pending stop

#### Scenario: Notice matures without a new event

- **GIVEN** the watch consumed a stop request's event in an earlier poll
- **WHEN** the authority's final stop appears with no new event sequence
- **THEN** the watch records the end once, by the stop's authority record
- **AND** a later read changing that stop's end is refused

### Requirement: Delivery authorization delegates payment interpretation

kit/deal-servicing MUST own authorize_delivery for commit, dispatch, start and disclose with durable allow/refuse/pending, reason, operation ID and evidence references. The foundation payment-adapter protocol MUST expose authorize(phase, evidence, billing) and start_billing(keys, activated_delivery_evidence). `billing` is optional: end service's journaled billing-start intent, its operation key and, once recorded, its result, which end service MUST pass at disclosure. `keys` are the operation keys of end service's one billing-start intent and MUST carry its operation store, so a mechanism records each operation it derives before any I/O. Generic servicing MUST NOT interpret hosted part fields; once-only adapters MUST validate commitment evidence and use no-op billing start.

authorize_delivery MUST ask the deal's payment adapter for every phase, whatever the deal's parts; a servicing declaration enables rate offers and does not decide their delivery. The first `allow` or `refuse` journaled for a phase at an admission revision MUST stand for that revision: when the adapter later answers that phase differently at the same revision, end service MUST return `pending`, naming the changed answer, and MUST NOT journal it, so a changed answer only holds a phase back until the revision moves.

For a deal whose committed seller projection is not once-only, end service's admission MUST NOT record the delivery-deadline end or journal its filing until a successful payment observation made at or after the deadline shows no lawful end effective at or before it; while the payment authority cannot be read the deal MUST stay unended with nothing filed. Each compute domain's recovery MUST read the payment authority before it admits a missed deadline. A once-only deal, and a deal with no committed seller projection, which no payment watch observes, keep admission's deadline rule unchanged.

#### Scenario: A rate deal is committed
- **GIVEN** a committed deal whose seller projection is not once-only, under a composition declaring the rate treatments its option uses
- **WHEN** delivery asks authorize_delivery to commit it
- **THEN** end service asks the payment adapter and journals its answer, and an `allow` lets delivery place the deal's capacity

#### Scenario: A once-only deal is committed
- **WHEN** delivery asks authorize_delivery to commit a deal whose seller projection is once-only
- **THEN** end service asks the payment adapter as before

#### Scenario: The payment authority's answer changes while a deal waits for its start
- **GIVEN** a rate deal whose commit was allowed and journaled at revision 4 and which waits for its Agreement start
- **WHEN** the next drive asks the commit again at revision 4 and the payment adapter answers `pending` because its snapshot is unavailable
- **THEN** end service returns `pending`, the journaled `allow` is unchanged, and nothing is raised
- **AND** a later drive whose adapter answers `allow` proceeds

#### Scenario: A stop the watch has not yet recorded refuses a phase
- **GIVEN** a rate deal whose commit was allowed and journaled at revision 4, and whose buyer's stop the payment authority has recorded but the watch has not
- **WHEN** a drive asks the commit again at revision 4 and the payment adapter refuses it
- **THEN** end service returns `pending` without journaling the refusal
- **AND** once the watch records the stop the revision moves and admission answers ended

#### Scenario: An undelivered rate deal passes its delivery deadline
- **GIVEN** a rate deal never available, whose buyer has not stopped
- **WHEN** it is driven after its delivery deadline, following a payment observation made after the deadline
- **THEN** admission records seller non-delivery at the deadline and journals the seller's `delivery_end(cause=payee, delivered=false)` filing

#### Scenario: A buyer stops while the storefront is down
- **GIVEN** a rate deal never available whose buyer's stop took effect at the payment authority before the delivery deadline, while the storefront was down and the hint was lost
- **WHEN** the storefront recovers after the deadline
- **THEN** recovery reads the authority before admitting the deadline, records the buyer's lawful end, and journals no seller non-delivery filing

#### Scenario: The payment authority is unreadable at the deadline
- **GIVEN** a rate deal never available
- **WHEN** it is driven after its delivery deadline and the payment authority cannot be read
- **THEN** no end is recorded and no filing is journaled, and a later drive after a successful read admits the deadline

#### Scenario: A financial decision is pending
- **WHEN** the injected adapter cannot resolve authority evidence for dispatch
- **THEN** delivery stays pending and a later allow still cannot override end-service admission

#### Scenario: Disclosure reads the journaled billing start
- **GIVEN** end service has journaled its billing-start intent and recorded its result
- **WHEN** delivery asks authorize_delivery to disclose
- **THEN** the adapter receives that intent's operation key and recorded result
- **AND** no other phase receives a billing start

### Requirement: Each deal's servicing steps run in one kit-owned order

kit/deal-servicing MUST own the order in which a storefront services a page of deals, and each compute storefront's `deal-servicing` loop MUST run it, contributing only its domain's steps and a respondent port that answers whether an authority's credential is usable and builds a deal's dispute adapter from its binding. Each cycle MUST first discover counterparty cases, once per dispute authority, resolving each listed case to its local deal itself, then run for each deal: the authorities read, the domain's recovery steps, the physical end, local reconciliation, site-report correction, filing dispatch and the physical end again. Every step MUST run in its own error isolation, so a failed step does not skip the steps after it, and a failed discovery at one authority MUST NOT skip another authority's discovery or any deal's steps. A deal with no dispute authority, or whose authority's credential is unusable, MUST be left out of discovery. A cycle MUST page every registered deal, reading the payment and dispute authorities only for committed deals and dispatching filings only in its filing step, and MUST keep its page position durably in kit-owned servicing state. Local reconciliation MUST admit a missed delivery deadline and, once admission allows, record the deal's own term-end final request at the Agreement's end, classified as the term end, in every compute domain.

#### Scenario: A physical failure does not skip filings

- **GIVEN** a deal with a journaled `delivery_end` filing whose physical end fails because the site cannot be reached
- **WHEN** the `deal-servicing` loop runs a cycle
- **THEN** local reconciliation, site-report correction and filing dispatch still run for that deal, and the physical end is attempted again after them

#### Scenario: Both domains record their own term end

- **WHEN** a VM deal and a bare-metal deal each reach the Agreement's end with no earlier end recorded
- **THEN** each storefront records its own term-end final request classified as the term end, and drives its physical end

#### Scenario: The page position survives a restart

- **WHEN** a storefront restarts between two cycles of its `deal-servicing` loop
- **THEN** the next cycle resumes from the durable page position

#### Scenario: Counterparty cases are discovered per authority

- **WHEN** a page holds several deals under one dispute authority, some paid through Arkhai payments and one through Alkahest
- **THEN** the cycle runs one respondent discovery for that authority before the per-deal steps, whichever deal comes first on the page

#### Scenario: One authority's discovery fails

- **GIVEN** a page holding deals under two dispute authorities
- **WHEN** the first authority's respondent listing cannot be read
- **THEN** the failure is logged naming the authority, the second authority's discovery still runs, and every deal's steps still run

#### Scenario: An authority's credential is unusable

- **WHEN** a page holds a deal whose dispute authority's credential cannot build a client
- **THEN** the deal is left out of respondent discovery, shows repair required for its missing credential, and its other steps still run

## MODIFIED Requirements

### Requirement: Cause classification is owned by end service

End service MUST classify verified evidence as lawful (entitled stop, term end/exhaustion, ruling, surrender), seller failure (unentitled withdrawal, provisioning/start failure, activation lapse, established non-delivery) or pending, and correlate site reports with their controllers. It MUST follow evidence and entitlements, never event kind or arrival order; admission refusal or a later stop MUST NOT erase earlier non-delivery or alone create a penalty. Physical work MUST NOT wait for it.

Each compute domain's payment watch MUST classify every verified payment final stop it records, once-only deals' included, through one compute-family classifier bound to the deal's accepted entitlements and the Agreement's end: a payer or payee stop is an entitled stop when the deal entitles that party, an authority stop is a ruling, a `terms` stop effective at or after the Agreement's end is the term end and one effective before it is exhaustion, and any other cause or an unentitled party's stop stays pending. A payment stop recorded earlier with a pending classification MUST be resolved through the pending-correction resolution once the watch next reads it and the classifier classifies it.

#### Scenario: Delivery deadline passes without availability

- **WHEN** the accepted delivery deadline passes without durable available evidence
- **THEN** end service classifies the end as seller non-delivery established at the deadline, refuses a new billing start, and journals the seller's `delivery_end(cause=payee)` filing

#### Scenario: A site report confirms a lawful end

- **WHEN** a site report is correlated to an already recorded lawful authority end
- **THEN** end service retains both evidence sources without inventing seller fault

#### Scenario: The seller activates after the delivery deadline inside a long term

- **WHEN** a thirty-day deal with `delivery_deadline_seconds` 1800 is approved at 12:00 and the resource is not available to the buyer at 12:30
- **THEN** end service classifies the end as seller non-delivery at 12:30, not a lawful end, and the seller half files `delivery_end` with that basis although the term continues

#### Scenario: The site activates in time but the buyer cannot use the resource by the deadline

- **WHEN** the site activates the lease at 12:29 against a 12:30 deadline and the storefront records `available` only after 12:30, or never
- **THEN** the deal is seller non-delivery, established at 12:30, and the seller half files `delivery_end(cause=payee)` — the Agreement start, the never-delivered basis; a `begin_billing` not yet sent is refused and no new rate part starts; the site's activation is a capacity fact the lifecycle does not treat as delivery

#### Scenario: Billing started seconds before the deadline and availability failed

- **WHEN** the payment authority accepts the payee's `start` at 12:29:58 against a 12:30 deadline and the storefront crashes before recording `available`, recovering at 12:40
- **THEN** the accepted start stands as history and is not refused after the fact; the deal is seller non-delivery, established at 12:30, access is never granted, the resource is ended through end service, and the seller half files `delivery_end(cause=payee)` with the Agreement start as its never-delivered basis, sending no stop or reverse of its own

#### Scenario: Billing ran for many periods before the deadline and availability failed

- **WHEN** a spot deal with a one-minute period, no setup charge and no penalty is approved at 12:00 with a 12:30 deadline, billing starts at 12:01, the storefront crashes before `available` and recovers at 12:40
- **THEN** the seller half files `delivery_end(cause=payee)` with `delivered: false` and the Agreement start as its basis, and sends no reverse for the thirty-nine completed periods, whose return is the dispute authority's ruling

#### Scenario: The buyer's stop discharges a later seller failure's filing

- **GIVEN** a delivered on-demand deal whose buyer's stop the watch recorded and classified as an entitled stop
- **WHEN** provisioning later reports the resource failed during its teardown
- **THEN** the failure is recorded under the buyer's earlier classified end and no `delivery_end(cause=payee)` filing is journaled

#### Scenario: Funds running out is told from the term end

- **WHEN** the watch records a `terms` stop effective one period before the Agreement's end, and on another deal one effective at the Agreement's end
- **THEN** the first is classified exhaustion and the second the term end, both lawful

#### Scenario: An earlier pending payment stop is resolved

- **GIVEN** a once-only deal whose payment term end was recorded with a pending classification by an earlier release
- **WHEN** the watch next reads that stop
- **THEN** the pending slot is resolved as the term end, without changing the recorded end

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token and each deal's negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state, current deadline, open-extension flag and open cases. Once-only deals MUST run from verified commitment until delivery ends. Rejected required filings MUST remain terminal, set repair required, expose every filing outcome in read/list and MUST NOT auto-resubmit.

A deal with a recorded end MUST be listed `ended` only when its resource is proven released, every payment part has a verified stop or end at the payment authority, and, when it names a dispute authority, a verified read of that authority has been saved and shows no case open; otherwise it MUST be listed `ending`, with `ending` naming each outstanding condition from a closed list — `release_pending`, `payment_running`, `case_open`, `case_unobserved` — whose text the lifecycle contracts carry. A dispute authority's first-page refusal of a record read that it also gives a reader who is no party — for `arkhai.mediation.v1`, `404 invalid_request`, its answer for an Agreement no party has filed on — MUST be read as a saved read showing no case, by the seller's and the buyer's reads alike. That read is not verified: it holds only on the premise, which the published contract gives no way to check, that the reader's credential authenticates the Agreement's party, so under a credential authenticating another account a deal MAY be listed `ended` while a case is open. A case opened after a deal was listed `ended` MUST return it to `ending`. The client shipped with the storefront MUST read every deal shape the list serves; a client released earlier is not owed reading it.

#### Scenario: A rejected filing is visible after restart

- **WHEN** the authority rejects a required seller filing and servicing restarts
- **THEN** the rejection remains visible under repair required, every filing outcome is returned, and the refused filing is not sent again

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

#### Scenario: Listed lifecycle states are explicit

- **WHEN** a deal is returned by `list`
- **THEN** its lifecycle state is unstarted, running, ending, ended or repair required

#### Scenario: A released deal whose rate still bills is ending

- **GIVEN** a rate deal whose buyer ended delivery at the storefront and whose resource is proven released, while the buyer's stop has not reached the payment authority
- **WHEN** the seller lists its deals
- **THEN** the deal is `ending` with `ending` naming `payment_running`, never `ended`

#### Scenario: A released deal whose dispute authority was never observed is ending

- **GIVEN** a deal naming a dispute authority, whose resource is proven released and whose payment needs no further stop, while no verified read of the dispute authority has been saved
- **WHEN** the seller lists its deals
- **THEN** the deal is `ending` with `ending` naming `case_unobserved`, never `ended`
- **AND** once a verified read showing no open case is saved, it is `ended` with no `ending`

#### Scenario: A deal nobody filed on is observed with no case

- **GIVEN** a deal naming a dispute authority that holds no record of its Agreement, because no party has filed, whose resource is proven released and whose payment needs no further stop
- **WHEN** servicing reads the authority with the seller's credential, which authenticates the Agreement's payee, and the authority answers the first record page `404 invalid_request`
- **THEN** a view showing no case is saved, the seller's and the buyer's reads of the deal carry an accepted dispute outcome, and the seller lists the deal `ended` with no `ending`
- **AND** once a party files, the next read shows the case and the deal is `ending` with `case_open`

#### Scenario: Several conditions are outstanding

- **WHEN** a deal's resource is still tearing down and a case is open
- **THEN** it is `ending` with `ending` naming `release_pending` and `case_open`
- **AND** once both clear and every part has stopped, it is `ended` with no `ending`
