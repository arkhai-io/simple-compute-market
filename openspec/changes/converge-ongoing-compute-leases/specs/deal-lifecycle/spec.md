## MODIFIED Requirements

### Requirement: Each deal's servicing steps run in one kit-owned order

kit/deal-servicing MUST own the order in which a storefront services a page of deals, and each compute storefront's `deal-servicing` loop MUST run it, contributing only its domain's steps and a respondent port that answers whether an authority's credential is usable and builds a deal's dispute adapter from its binding. Each cycle MUST first drive the physical end of every deal on its page, then discover counterparty cases, once per dispute authority, resolving each listed case to its local deal itself, then run for each deal: the authorities read, the domain's recovery steps, the physical end, local reconciliation, site-report correction, filing dispatch and the physical end again. Every step MUST run in its own error isolation, so a failed step does not skip the steps after it, a failed physical end in the leading pass MUST NOT skip another deal's, and a failed discovery at one authority MUST NOT skip another authority's discovery or any deal's steps. A deal with no dispute authority, or whose authority's credential is unusable, MUST be left out of discovery. A cycle MUST page every registered deal, reading the payment and dispute authorities only for committed deals and dispatching filings only in its filing step, and MUST keep its page position durably in kit-owned servicing state. Local reconciliation MUST admit a missed delivery deadline and, once admission allows, record the deal's own term-end final request at the Agreement's end, classified as the term end, in every compute domain.

#### Scenario: A physical failure does not skip filings

- **GIVEN** a deal with a journaled `delivery_end` filing whose physical end fails because the site cannot be reached
- **WHEN** the `deal-servicing` loop runs a cycle
- **THEN** local reconciliation, site-report correction and filing dispatch still run for that deal, and the physical end is attempted again after them

#### Scenario: A recorded end waits behind no authority read

- **GIVEN** a page whose earlier deals' payment and dispute authorities do not answer, and a later deal with an end recorded before the cycle
- **WHEN** the `deal-servicing` loop runs a cycle
- **THEN** the later deal's physical end is dispatched before any authority is read or any counterparty case discovered

#### Scenario: An end a deal's own read discovers is torn down after its steps

- **GIVEN** a deal whose payment authority's read records a stop as its end, followed on the page by deals whose dispute authority does not answer
- **WHEN** the `deal-servicing` loop runs a cycle
- **THEN** that deal's physical end runs in its own steps, before the later deals' steps

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

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token and each deal's negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state, current deadline, open-extension flag and open cases. Once-only deals MUST run from verified commitment until delivery ends. Rejected required filings MUST remain terminal, set repair required, expose every filing outcome in read/list and MUST NOT auto-resubmit.

A deal with a recorded end MUST be listed `ended` only when its resource is proven released, every payment part has a verified stop or end at the payment authority, every `delivery_end` filing its end journal holds has been accepted by the dispute authority, and, when it names a dispute authority, a verified read of that authority has been saved and shows no case open; otherwise it MUST be listed `ending`, with `ending` naming each outstanding condition from a closed list — `release_pending`, `payment_running`, `case_open`, `case_unobserved`, `filing_unanswered` — whose text the lifecycle contracts carry. `filing_unanswered` MUST name a journaled `delivery_end` filing that is unsent, waiting for the Agreement's start, or of pending or unknown outcome; a rejected filing shows repair required instead. The report of open deals a storefront cannot service MUST apply the same rule. A dispute authority's first-page refusal of a record read that it also gives a reader who is no party — for `arkhai.mediation.v1`, `404 invalid_request`, its answer for an Agreement no party has filed on — MUST be read as a saved read showing no case, by the seller's and the buyer's reads alike. That read is not verified: it holds only on the premise, which the published contract gives no way to check, that the reader's credential authenticates the Agreement's party, so under a credential authenticating another account a deal MAY be listed `ended` while a case is open. A case opened after a deal was listed `ended` MUST return it to `ending`. The client shipped with the storefront MUST read every deal shape the list serves; a client released earlier is not owed reading it.

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

#### Scenario: A filing waits for the Agreement's start

- **GIVEN** a once-only deal ended as a seller failure before its Agreement's start, with nothing dispatched, whose `delivery_end` filing waits for that start, and a saved read of its dispute authority showing no case
- **WHEN** the seller lists its deals before the start
- **THEN** the deal is `ending` with `ending` naming `filing_unanswered`, never `ended`
- **AND** once the filing is accepted and its case closes, the deal is `ended`

#### Scenario: A filing's answer was lost

- **GIVEN** a released deal whose `delivery_end` filing was sent and whose answer was lost
- **WHEN** the seller lists its deals
- **THEN** the deal is `ending` with `ending` naming `filing_unanswered` until the filing's outcome is resolved under its operation key

### Requirement: Filing identities and revised requests are safe across callers

The dispute adapter MUST bind the semantic filing identity to commitment, Agreement authority, cause/end revision and fixed request, and MUST resolve or adopt the equivalent case without a concurrent-writer duplicate. An unresolved original writer MUST remain retryable rather than become a terminal rejection. A `delivery_end` whose claim differs from every `delivery_end` already filed on the Agreement, by either party, MUST be filed at once as a new case under a writer reservation of its own fixed request, and MUST stay pending, not rejected, while the caller's own earlier `delivery_end` filing is of unknown outcome. An identity or revision mapping the adapter cannot prove safe MUST report repair required, not allocate another key or use append as amendment.

#### Scenario: An original filing's result is unknown

- **WHEN** an original filing's submission returns no answer
- **THEN** the filing stays retryable under the same semantic identity and is not recorded as rejected

#### Scenario: An operator and online replay submit one intent

- **WHEN** operator recovery and online replay submit the same semantic filing identity concurrently
- **THEN** both resolve one case, or refuse with repair required if the adapter cannot prove safe adoption

#### Scenario: A changed claim follows a filed one

- **GIVEN** a deal whose dispute authority holds the buyer's accepted `delivery_end(cause=payer)` case, and a later site report proving the seller's failure at an earlier instant
- **WHEN** the storefront's filing step sends the payee's `delivery_end` for that earlier end
- **THEN** it is filed as a new case on the Agreement, not answered repair required, and the deal is listed with that case open

### Requirement: Revised cases carry their prior rulings

A `delivery_end` that revises an earlier one on the same Agreement MUST be filed as a case of its own, carrying nothing that names the case it revises; the dispute authority identifies the revised case from its own record, as the latest earlier `delivery_end` case on the Agreement in the order it accepted them. SCM MUST rely on the dispute authority to rule a payee-endorsed revision ending no later than the revised claim mechanically, after every earlier case on the Agreement has closed or applied its effects, and to net it against the effects earlier cases applied, the premature-stop penalty taken at most once per Agreement; any other revision is an operator's. SCM MUST record the delivery end a revision's ruling applies as it records any ruling's, and MUST NOT compute or send a remedy of its own.

#### Scenario: A revision follows a ruling

- **GIVEN** a seller's `delivery_end` filing ruled with a stop at its claimed end and the premature-stop penalty
- **WHEN** the storefront files the payee's revision to an earlier end and the authority rules it
- **THEN** the storefront records the ruling's earlier delivery end, classified as a ruling, and sends no stop or reverse of its own
- **AND** the ruling reverses only the earnings between the two ends and takes no second penalty
