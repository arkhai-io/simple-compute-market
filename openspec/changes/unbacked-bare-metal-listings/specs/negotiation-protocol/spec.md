## ADDED Requirements

### Requirement: The accept reply carries no escrow terms

A seller's accept reply MUST NOT carry materialized escrow terms beside its settlement
plan, and a buyer MUST NOT read escrow terms from a reply. The settlement plan a reply
carries is the seller's committed copy of what the Agreement and its listing determine,
which the buyer compares with its own derivation and never funds in its place.

#### Scenario: A seller accepts an Alkahest proposal

- **WHEN** a VM, bare-metal, or API-credit seller accepts an Alkahest escrow proposal
- **THEN** its reply carries the Agreement and the settlement plan, and no
  `accepted_escrow_terms`

#### Scenario: A reply carries escrow terms

- **WHEN** a buyer receives an accept reply that carries `accepted_escrow_terms`
- **THEN** the buyer ignores them and funds only the escrow it derives

## MODIFIED Requirements

### Requirement: An Alkahest obligation uses exactly the release condition its listing authorizes

Every published Alkahest settlement option MUST carry an authorized release condition — an
arbiter and its demand data — for the chain it publishes on. Where a buyer's proposal selects a
release condition, the seller MUST reject the round unless the selected arbiter and demand data
equal a condition the listing authorizes for that chain, including when the listing authorizes
none. Independently of any seller policy, the plan a seller materializes MUST use exactly the
authorized condition the proposal selected, or the listing's authorized condition where the
proposal selected none, and a listing whose authorized condition is missing or cannot be read
MUST fail closed before any obligation is accepted. A seller MUST NOT accept an Alkahest deal
without its materialized plan: a plan that cannot be materialized refuses the acceptance, and an
exact settlement selection of a mechanism whose deals need a plan is accepted only with that
plan; only a mechanism that settles from the Agreement alone is accepted without one. An escrow
proposal MUST name the escrow contract it funds: a proposal naming none, or the zero address,
MUST be refused, by the seller's escrow-shape policy where it runs and, independently of any
seller policy, by plan materialization, while a negotiation that carries no escrow proposal is
unaffected. An escrow proposal naming a contract the listing does not accept, including against a
listing accepting none, MUST be refused before any seller decision accepts it, and no listing
entry prices it.

#### Scenario: A proposal substitutes the recipient

- **WHEN** a buyer proposes an Alkahest escrow naming the listing's advertised arbiter with a
  recipient other than the one its demand data authorizes
- **THEN** the seller rejects the round and no plan is materialized

#### Scenario: A listing authorizes no release condition

- **WHEN** a buyer proposes an Alkahest escrow naming a release condition against a listing that
  authorizes none
- **THEN** the seller rejects the round rather than accepting the buyer's condition

#### Scenario: A proposal names no escrow address

- **WHEN** a buyer's Alkahest proposal names no escrow address, or the zero address
- **THEN** the seller refuses it, naming the unpinned contract, and no plan is materialized
  and no listing entry prices it

#### Scenario: A proposal names an escrow the listing does not accept

- **WHEN** a buyer's Alkahest proposal names an escrow contract the listing does not accept, or
  any escrow against a listing accepting none
- **THEN** the seller refuses it, naming `escrow_not_in_accepted_set`, and no listing entry
  prices it

#### Scenario: A seller without the shape policy receives an unpinned proposal

- **WHEN** a seller's negotiation policies omit the escrow-shape guard and a buyer's Alkahest
  proposal names no escrow address
- **THEN** plan materialization refuses it and no obligation is accepted

#### Scenario: The seller configures no escrow-shape policy

- **WHEN** a seller's negotiation policies omit the escrow-shape guard and a buyer selects an
  unauthorized release condition
- **THEN** plan materialization refuses it and no obligation is accepted

#### Scenario: The plan cannot be materialized

- **WHEN** a seller accepts an Alkahest proposal whose release condition is authorized but whose
  plan cannot be materialized, for a reason other than the release condition
- **THEN** the seller refuses the acceptance and records neither an Agreement nor a plan

#### Scenario: An exact selection names a mechanism that needs a plan

- **WHEN** a buyer's opening selects an advertised option exactly, and the seller has no way to
  build that mechanism's plan from the selection
- **THEN** the seller refuses the opening rather than accepting a deal it cannot settle

### Requirement: The seller's reference amount is the selected option's rate

A seller's reference amount for a scalar negotiation MUST be derived from the amount rate of the
option the buyer's proposal selects: the matched accepted escrow for an escrow proposal, or the
settlement option matched by its identity for a settlement selection. A configured negotiation floor
MUST apply only when the selected option advertises no rate. A reference amount MUST NOT be derived
from an option the buyer did not select or from a rate in another asset. The negotiation runtime
MUST give the domain the buyer's pinned proposal when it asks for the reference amount, and a seller
MUST price the pinned proposal in every round, whatever a later counter names. A proposal selecting
nothing the listing offers MUST be priced from no option and no floor, and refused before any seller
decision accepts it.

#### Scenario: A second mechanism's option is selected on a two-mechanism listing

- **WHEN** a listing offers an Alkahest option and an Arkhai payments option, and the buyer selects
  the payments option
- **THEN** the seller's reference amount is derived from the payments option's rate in its own minor
  units, not from the Alkahest rate

#### Scenario: A listing offering only non-escrow options is negotiated

- **WHEN** a listing offers only Arkhai payments options with rates and the storefront configures a
  negotiation floor
- **THEN** the seller's reference amount is derived from the selected option's rate, and the floor
  is not used

#### Scenario: The selected option is a hidden reserve

- **WHEN** the buyer selects an option that advertises no rate
- **THEN** the seller's reference amount is derived from the configured negotiation floor

#### Scenario: A proposal selects nothing the listing offers

- **WHEN** a buyer's opening names an escrow the listing does not accept, or a selection matching
  no option, and the storefront configures a negotiation floor
- **THEN** the seller derives no reference amount from any option or from the floor, and refuses
  the opening

#### Scenario: A counter names another option

- **WHEN** a buyer's counter names an option other than the one its opening selected
- **THEN** the seller's reference amount, and whether the round bargains an amount, remain the
  opening's
