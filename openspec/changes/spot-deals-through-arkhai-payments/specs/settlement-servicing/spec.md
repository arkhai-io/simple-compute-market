## ADDED Requirements

### Requirement: Hosted rate mandates are derived from the selected option
SCM MUST derive time rate parts through the agreed-price accessor and lifecycle codec, using the selected Agreement's asset, period, reservation lead, absolute term end, adjudication hold and cap. The buyer MUST independently check all parts and authorities before approval, including any disclosed setup once part.

#### Scenario: A mixed setup and rate option is selected
- **GIVEN** a selected option with setup_amount and a price accessor returning a per-period charge
- **WHEN** buyer and seller derive the mandate
- **THEN** both derive setup once followed by rate, with the same amounts, asset, end, afterStop hold, maxHoldExtension and per-part authorities
- **AND** neither reads Agreement.amount as a direct charge

#### Scenario: A seller adds stop authority to on-demand
- **GIVEN** an accepted option with no payee early-termination entitlement
- **WHEN** the buyer checks a mandate containing a payee stop authority on the rate part
- **THEN** the mandate is refused before approval

#### Scenario: Notice is explicitly priced
- **GIVEN** a payer entitlement with notice_seconds zero and a nonzero exposure_seconds
- **WHEN** the adapter derives stop authorities
- **THEN** payer notice is zero, not exposure added to or substituted for the accepted notice
- **AND** reserve_ahead_seconds must still cover exposure_seconds

#### Scenario: Provisioning starts late
- **GIVEN** a finite maximum term equal to accepted duration_seconds
- **WHEN** rate start occurs after Agreement start_utc
- **THEN** the derived part end remains start_utc plus max_term_seconds

### Requirement: Hosted rate commands preserve part identity and uncertain outcomes
The hosted adapter MUST translate lifecycle commands into explicit per-part events with stable operation-derived request identities. It MUST require provisioned-delivery evidence for rate start, reject key reuse with changed content, and expose unknown outcomes for resolution by verified reads before another monetary delta is issued.

#### Scenario: A start response is lost
- **GIVEN** a caller-journaled start operation with provisioned-delivery evidence
- **WHEN** its response is lost
- **THEN** the adapter reports unknown and exposes the authority event through read
- **AND** retry uses the same part, bytes and request identity

#### Scenario: Start loses to a stop
- **GIVEN** the rate part is already stopped at the authority
- **WHEN** start is refused as transaction_stopped
- **THEN** the adapter reports the failed start for delivery-end handling, not successful start

#### Scenario: A stop is repeated
- **WHEN** a stop submission reports an already-stopped part
- **THEN** the adapter confirms satisfaction only from a verified same-or-earlier effective stop
- **AND** it never reports a later local timestamp as the authority's end

### Requirement: Rate corrections use a cumulative target and half-open periods
SCM's rate correction helper MUST evaluate intervals from the authority start as half-open periods. Buyer-caused ends keep an incomplete started period; seller-caused ends return it. The helper MUST subtract confirmed earned-money returns by every actor from a cumulative target, exclude returned unearned reservations, and produce only a positive remaining delta.

#### Scenario: The end crosses a period boundary
- **GIVEN** start 0, period 60 and amount 100
- **WHEN** end is 60
- **THEN** buyer-caused and seller-caused permitted charges are both 100
- **WHEN** end is 61
- **THEN** buyer-caused permitted charge is 200 and seller-caused permitted charge is 100
- **AND** end at start permits zero charge

#### Scenario: A reversal acknowledgement is lost and another actor reverses
- **GIVEN** an unresolved operation and a later target increase
- **WHEN** the caller requests the next delta
- **THEN** it must first resolve the earlier operation from verified records
- **AND** the next operation subtracts all confirmed earned-money returns, including the other actor's reversal

#### Scenario: A part never started
- **GIVEN** an approved rate part without authority start
- **WHEN** it stops and the reserved batch returns
- **THEN** earned charge and earned-money reversal target are zero
- **AND** the returned reservation is not counted again as a refund of earnings

### Requirement: Rate correction respects the dispute authority boundary
SCM MUST journal lawful preemption's cooperative started-period correction for voluntary reverse while held. Exceptional ends MUST instead be filed as exceptional_end(at) through the dispute adapter, not realized by backdated payee stop or a locally computed ruling. A paid-out shortfall MUST be reported rather than queued as an unsupported post-release refund.

#### Scenario: The storefront recovers after lawful notice matured
- **GIVEN** a journaled seller notice and its started-period correction obligation
- **WHEN** verified records show effective stop while rate earnings remain held
- **THEN** the caller can submit the remaining voluntary reverse after stop under its immutable operation identity

#### Scenario: A site reports an earlier exceptional end
- **WHEN** the seller learns service ended without an entitlement covering that end
- **THEN** it files exceptional_end at the reported instant
- **AND** the dispute authority determines the stop-now and reversal effects

#### Scenario: Held money has already matured
- **WHEN** a voluntary reverse cannot reach paid-out money
- **THEN** SCM reports the unrecoverable local shortfall and case path
- **AND** it does not invent a refund command or retry unsupported forever

### Requirement: Rate observations require verified authority state
The hosted adapter MUST consume the foundation's verified snapshot interface before interpreting start, funding, pending stop, stop, extensions, releaseAt or event sequence. It MUST expose per-part changes to lifecycle read/watch without treating a courtesy hint or a missing funding field as an authoritative stop.

#### Scenario: A pending stop survives the storefront
- **GIVEN** a verified authority pendingStop
- **WHEN** the storefront restarts after its effective time
- **THEN** adapter read exposes the authority's resulting stop and cause for end service
- **AND** no local payment-stop schedule is required

#### Scenario: The snapshot cannot be verified
- **WHEN** snapshot verification fails or its known sequence regresses
- **THEN** no rate state from it is used for billing, start admission or funding renewal

### Requirement: Running hosted deals can re-anchor during identity overlap
SCM MUST support bounded overlap of current and retiring payment identities. It MUST provide fresh current-key verified snapshot evidence bound to the persisted mandate for durable re-anchoring, preserve original signed bytes, and report deals still dependent on a retiring identity. A mode change MUST require draining rather than re-anchoring.

#### Scenario: An old-key receipt is embedded in a new-key snapshot
- **GIVEN** an old receipt verified during the configured overlap
- **WHEN** a fresh current-key snapshot attests that receipt and matches the mandate, parties, mode and sequence
- **THEN** SCM provides that snapshot for durable replacement of the approval trust anchor
- **AND** the retiring key is removable only after dependent deals re-anchor or drain

#### Scenario: A stale snapshot attempts to restore old trust
- **WHEN** a restart sees evidence below the persisted sequence or signed only by a retired key
- **THEN** it cannot replace the current approval evidence or revive the retired anchor

#### Scenario: Test mode changes to live
- **WHEN** payment livemode changes
- **THEN** the running test-mode deal cannot re-anchor as a live deal
