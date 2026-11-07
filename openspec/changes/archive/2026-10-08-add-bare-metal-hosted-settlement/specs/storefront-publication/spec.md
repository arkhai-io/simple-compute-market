## ADDED Requirements

### Requirement: Bare-metal hosted options require complete trusted readiness

A trusted `bare_metal.v1` publication MAY advertise `fiat.stripe.v1` only as exact `settlement_options` independent from legacy `accepted_escrows`. Each hosted option MUST bind one canonical funding profile, exact currency and rate/amount derivation, seller/claimant principal, hosted seller account readiness, condition/evidence mode, funding deadline, and the listing's trusted site/resource/capacity/access context. Publication MUST omit that option when the exact hosted release/authority, identity trust, seller account, profile/currency, condition resolver, selected site/Physical Resource mapping, authoritative availability, access capability, offer window, or funding window is absent, stale, inconsistent, or unavailable.

#### Scenario: Exact whole-host option is ready

- **WHEN** a trusted specific-resource candidate and every hosted dependency agree on one supported profile, USD quote, condition, seller, and deadline
- **THEN** publication emits one deterministic hosted option bound to that candidate and keeps Alkahest alternatives independent

#### Scenario: Site or resource projection becomes unavailable

- **WHEN** the exact trusted site generation is incomplete, the Physical Resource is unavailable, or the offer/funding window cannot cover the accepted path
- **THEN** the hosted option is omitted or the listing is closed according to ordinary reconciliation without substituting another site/resource

#### Scenario: One profile is not ready

- **WHEN** card is ready but ACH Direct Debit or bank-transfer prerequisites are not
- **THEN** only `card.v1` is advertised and no generic hosted option implies the missing profile

### Requirement: Accepted bare-metal binding is immutable

Settlement admission MUST reconstruct the selected hosted option from the signed accepted listing and seller-owned negotiated terms, then bind exact agreement, obligation, buyer/payer, seller/claimant, price/currency, condition, site, Physical Resource when intentionally selected, access policy, offer expiry, funding expiry, and fulfillment deadline. Buyer-supplied fields MUST NOT invent or override a Physical Resource, physical host, pool, site, executor machine/provider, seller account, seller/claimant, rate/price, access policy, condition, or expiry.

#### Scenario: Buyer overrides trusted placement

- **WHEN** the buyer submits a different site, Physical Resource, physical host, pool, executor, or seller than the accepted signed artifacts
- **THEN** admission fails before financial mutation, capacity commitment/scheduling, or executor work

#### Scenario: Trusted offer expires before funding

- **WHEN** current time reaches the accepted offer or billable-hold bound while hosted funding remains nonterminal
- **THEN** the accepted option is not extended or silently republished and the servicing expiry path begins

### Requirement: Funding cannot lengthen bare-metal availability

A bare-metal hosted funding deadline MUST be no later than the accepted offer expiry and the billable negotiation-hold deadline. Slow or interactive payment state MUST NOT renew, extend, replace, rebind, or commit an existing hold. Republished availability after expiry is a new signed offer and MUST NOT mutate or rescue the old obligation.

#### Scenario: ACH remains pending at the hold boundary

- **WHEN** ACH Direct Debit has not reached authoritative funded state when the billable hold expires
- **THEN** the old deal cannot commit, schedule, or provision the host even if that host is later republished
