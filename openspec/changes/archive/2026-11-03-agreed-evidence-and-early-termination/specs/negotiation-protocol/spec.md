## MODIFIED Requirements

### Requirement: Deterministic agreed terms

On acceptance, negotiation MUST produce exactly one Agreement containing `negotiation_id`, `listing_id`, `listing_hash`, canonical `buyer` and `seller` principals, the exact selected settlement option, opaque buyer `settlement_params`, `amount`, `asset`, `duration_seconds`, explicit `start_utc`, domain-owned `provision_terms`, and `accepted_at`. The seller MUST resolve relative start requests at acceptance. Both parties MUST retain the exact returned Agreement bytes, not reconstruct them. Each mechanism defines its own commitment hash.

#### Scenario: Seller accepts a proposal

- **WHEN** a round terminates in acceptance
- **THEN** its Agreement pins the exact option's optional `price`, required `settlement` and optional `lifecycle`, and an explicit start time

#### Scenario: Both participants retain the accepted Agreement

- **WHEN** the buyer receives the accept response
- **THEN** buyer and seller retain the exact Agreement bytes and neither reserializes a replacement before settlement

### Requirement: Additive settlement option carriers

Listings MAY carry ordered `SettlementOption` envelopes. Acceptance MUST pin one exact option through `SettlementSelection`, containing its `option_id`, a `settlement` envelope with the same `schema` and buyer-owned parameters, and optional `expiration_unix`. Buyer parameters MUST remain opaque and enter Agreement `settlement_params` without the schema tag; they MUST NOT replace seller-owned parameters. Alkahest-only acceptance MAY omit a selection. Absent optional price and lifecycle keys MUST be omitted.

#### Scenario: Legacy Alkahest negotiation is serialized

- **WHEN** an Alkahest-only listing has no settlement options or selection
- **THEN** negotiation does not synthesize a shared option from its escrow fields

#### Scenario: Arkhai payment option is advertised

- **WHEN** a listing supports `arkhai.payments.v1`
- **THEN** its option is carried in `settlement_options` without rewriting Alkahest escrow fields

### Requirement: Deterministic option identity

A settlement option ID MUST be lowercase SHA-256 of sorted compact UTF-8 JSON of `settlement` and any present `price` and `lifecycle`. Rates MUST serialize their values as decimal strings. Seller acceptance MUST exact-match the stored listing option and derive mechanism values from it, not buyer-supplied duplicates. An unrecognized option shape MUST be refused at selection before approval or funding.

#### Scenario: Buyer changes condition after discovery

- **WHEN** a buyer changes option parameters so the ID or body no longer matches the stored option
- **THEN** acceptance fails without creating an Agreement

#### Scenario: Lifecycle rights change

- **WHEN** only an option's lifecycle terms change
- **THEN** its option ID changes; an absent lifecycle is hashed without that key

## ADDED Requirements

### Requirement: The protocol ends at the mechanism's commitment act

The negotiation protocol MUST consist of discovery, negotiation, and the selected mechanism's commitment act. Every later exchange MUST be post-commitment lifecycle, governed by the `deal-lifecycle` capability and visible to arbitration only through evidence. Core MUST keep the agreement and commitment carriers schema-opaque.

#### Scenario: A buyer commits and never reports it

- **WHEN** a buyer approves a hosted mandate and sends nothing to the seller
- **THEN** the deal is committed but unstarted, and the buyer has broken no protocol step

### Requirement: Each option names its dispute authority

A clause MUST be decided by the dispute authority its option names, an independent party identified per deal by its interface and that interface's fields. A buyer MUST refuse an option whose authority it has not accepted, whose interface its client has no adapter for, or that does not advertise the option's payment mechanism. A dispute authority MUST be chosen by choosing among options; a buyer MUST NOT edit seller-owned option parameters.

#### Scenario: A seller offers two dispute authorities

- **WHEN** a listing carries two otherwise equal options whose clauses name different dispute authorities
- **THEN** the buyer chooses its dispute authority by selecting one option, and each has its own option ID
