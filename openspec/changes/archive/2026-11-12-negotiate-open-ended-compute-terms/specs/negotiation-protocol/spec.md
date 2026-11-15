## ADDED Requirements

### Requirement: Agreed compute prices carry their unit

Compute price consumers MUST use one core accessor returning the agreed quote and
its unit, `total` or `per_period`, with the selected period available for display.
`Agreement.amount` MUST contain the accepted monetary amount, not the multiplier.
Before acceptance, prepaid quotes MUST use Agreement duration and recurring quotes
one selected option period, preserving upward rounding once and asset amount limits.
The multiplier MUST remain negotiation-transcript state; the accessor MUST return
the accepted amount and label it using the selected option's acceptance-bound billing kind. Every
consumer that spends, caps, displays, recovers or confirms accepted money MUST read it through
the accessor, and each such consumer MUST be tested with a per-period Agreement; no repository
check inventories reads of `Agreement.amount`.

#### Scenario: Sub-hour recurring quote

- **WHEN** a negotiation agrees 10,000 bps and selects PT1M at 2,500,000 USD/6 per hour
- **THEN** acceptance writes the upward-rounded monetary amount 41,667 into the Agreement
- **AND** the accessor returns that accepted 41,667 per period rather than the full maximum-term price

#### Scenario: Prepaid recovery

- **WHEN** an accepted two-hour prepaid Agreement at that rate is recovered
- **THEN** the accessor returns 5,000,000 total from the accepted option

#### Scenario: Publication is repriced before materialization

- **WHEN** the pool rate changes after signed acceptance but before mandate derivation or restart recovery
- **THEN** the accessor returns the accepted monetary amount with the accepted option's unit, and the agreed price does not change
- **AND** recovery and buyer mandate checks verify it against the acceptance-bound rate structure and transcript multiplier, never the current listing

#### Scenario: A money consumer reads a per-period Agreement

- **WHEN** mandate derivation, a buyer cap or display, recovery or confirmation reads an accepted recurring Agreement
- **THEN** each treats `Agreement.amount` as one period's price, as the accessor labels it, never as the deal's total

### Requirement: Acceptance pins the published rate identity

A multiplier-priced compute acceptance MUST bind the agreed multiplier and the same
rate-structure digest pinned at opening in the seller-signed response. Every round
MUST refer to that digest, computed over the publication's `pricing.rate_structure`. The buyer
MUST verify it against the registry's retained seller-signed publication, with historical
signature/context, listing identity, the publication's whole `pricing` object, exact selected
option and transcript-price checks before accepted recovery or mandate use. Missing evidence
MUST fail closed.

#### Scenario: Opening, rounds and acceptance use one publication

- **WHEN** a buyer negotiates a rate-structured listing
- **THEN** opening, every round and acceptance carry the same digest of the published rate structure
- **AND** acceptance binds that digest and the agreed multiplier in its signed response

#### Scenario: A signed acceptance substitutes its rate identity

- **WHEN** the accepted digest differs from the retained seller-signed registry publication or the pin differs from the transcript multiplier
- **THEN** the buyer refuses the acceptance before persistence or funding

#### Scenario: Historical evidence is incomplete

- **WHEN** recovery lacks retained publication proof or the signed acceptance pricing pin
- **THEN** it fails closed rather than substituting a current listing or a seller-returned snapshot
- **AND** Agreement.listing_hash keeps its existing database-listing meaning, a known gap recorded in `openspec/changes/README.md`

#### Scenario: Retained pricing differs from the signed publication

- **WHEN** the retained listing's `pricing` object, or the family rates the buyer reads, differ from the seller-signed publication's `pricing`
- **THEN** the buyer refuses the acceptance before persistence or funding

### Requirement: Compute horizons bind both seller bounds

Reserved duration MUST be positive and fit both bounds.

#### Scenario: The full policy is enforced

- **WHEN** a recurring negotiation resolves its final duration
- **THEN** Reserved duration MUST be positive and fit both bounds. Recurring horizons MAY be omitted; default is the least stated relative bound or absolute availability minus resolved start, floored to whole seconds when the limiting bound is a fractional-second `available_until_utc`. Accepted duration/max term MUST equal that default or a shorter selection without rounding, and MUST include at least one whole period. Acceptance MUST refuse expired, excessive or sub-period selections. For a recurring option, acceptance MUST also refuse a horizon whose term end is earlier than `max(floor(accepted_at) + approval_window, start_utc) + delivery_deadline_seconds + period`, naming the minimum horizon that passes, and derivation MUST apply the same inequality to the default horizon so that no advertised recurring option fails it at its default selection.

#### Scenario: The horizon leaves no runway

- **WHEN** a buyer proposes a 15-minute horizon on an option with a 15-minute period, a 15-minute approval window and a 1200-second delivery deadline
- **THEN** acceptance refuses with the minimum horizon of 50 minutes
- **AND** a 50-minute proposal is accepted and a buyer approving at the last permitted instant still receives one whole period after the deadline

#### Scenario: Absolute bound is earlier

- **WHEN** max duration is 48 hours, availability is 20 hours after resolved start and a recurring buyer names no horizon
- **THEN** the signed selection binds duration and max term to 20 hours

#### Scenario: Maximum term is not a whole period

- **WHEN** the effective seller bound or shorter buyer horizon is 125 seconds for a 60-second period
- **THEN** duration and max term bind 125 seconds before signature, without rounding
- **AND** the term end carries its own `settles_through` under the foundation codec: compute presets use `last_boundary` mapped to `end.partialPeriod: returned`, admitted where the mechanism supports it and the composition declares it qualified

#### Scenario: The limiting absolute bound has fractional seconds

- **WHEN** a recurring buyer names no horizon and the limiting bound is an `available_until_utc` 72000.4 seconds after the resolved start
- **THEN** the default horizon binds 72000 seconds rather than being refused

#### Scenario: Reserved term exceeds availability

- **WHEN** a reserved duration fits the relative maximum but ends after absolute availability
- **THEN** acceptance is refused

#### Scenario: Buyer chooses a shorter horizon

- **WHEN** a buyer chooses 10 hours under a 20-hour seller bound
- **THEN** the final identity-bound option and Agreement both bind 10 hours before acceptance
- **AND** no cached or accepted option is silently mutated

### Requirement: The horizon is the Agreement's, and the option is unchanged by it

A recurring selection MUST resolve its horizon into `Agreement.duration_seconds` at acceptance — the buyer's stated horizon, else the earliest listing bound at the agreed start — and the seller's signed acceptance MUST carry the advertised option unchanged, with its advertised ID. The option MUST NOT carry a maximum term of its own. The buyer MUST check `duration_seconds` against both listing bounds at `start_utc` before committing.

#### Scenario: Two buyers accept one option

- **WHEN** two buyers accept the same recurring option at different starts under a 20-hour relative bound
- **THEN** each Agreement carries its own `duration_seconds` and the same option with the same ID

#### Scenario: A horizon exceeds the advertised bound

- **WHEN** a signed acceptance carries `duration_seconds` of 21 hours under an advertised 20-hour bound
- **THEN** the buyer refuses to commit

#### Scenario: A horizon ends after absolute availability

- **WHEN** a signed acceptance's `start_utc + duration_seconds` falls after the listing's `available_until_utc`
- **THEN** the buyer refuses to commit

#### Scenario: The seller resolves an omitted horizon

- **WHEN** a buyer names no horizon and the signed acceptance carries the default bound at its `start_utc`, while its provision terms carry no duration
- **THEN** the buyer accepts, comparing a provision duration with the Agreement's only where the buyer requested one

### Requirement: The negotiation runtime resolves acceptance through a domain hook

The schema-opaque negotiation runtime MUST fix one acceptance instant and, on every acceptance
path, call the optional `resolve_acceptance` domain hook with it before building artifacts or
writing acceptance. The hook MAY refine the Agreement's start and duration and MAY refuse; the
runtime MUST NOT interpret the domain's terms itself.

#### Scenario: A counter is accepted

- **WHEN** a buyer accepts a seller's counter on a recurring option
- **THEN** the runtime calls the domain hook with its fixed acceptance instant before any artifact is built or acceptance persisted, and a refusal leaves no acceptance written

### Requirement: Recurring starts resolve before signature

The terms runtime MUST resolve recurring start_utc to whole-second precision before the final signature, with bound/horizon and canonical option identity fixed. It MUST reject a fractional rate start rather than round accepted bytes. Once-only timestamp handling MUST remain unchanged.

#### Scenario: A recurring start is fractional

- **WHEN** the final recurring proposal carries a fractional-second start
- **THEN** acceptance refuses before signature rather than silently shifting the window

### Requirement: Acceptance checks current rate servicing

Seller acceptance MUST refuse recurring selections if the composition no longer
declares compatible servicing, even if a cached advertised option carries recurring
terms. The refusal MUST precede persistence and use the withdrawn-option/refetch
outcome. The listing MUST NOT be treated as the servicing declaration.

#### Scenario: Cached recurring option after servicing is disabled

- **WHEN** a buyer selects a cached recurring option and composition no longer declares servicing
- **THEN** the seller refuses before persisting acceptance and asks the buyer to refetch
