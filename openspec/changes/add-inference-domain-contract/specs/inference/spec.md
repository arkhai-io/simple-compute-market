## ADDED Requirements

### Requirement: Versioned inference vocabulary

The inference domain MUST validate listings, round-zero provision intent,
negotiated terms, materializations, receipts, and results against the
`inference.v1` domain contract, and MUST register its codecs under the supported
market-domain contract version with the domain identity `inference.v1`.
Provision intent MUST use version `1`, request a positive integer credit
quantity, and select either a new key or an existing key identified by `key_id`.

#### Scenario: Invalid provision intent is received

- **WHEN** provision intent has another kind or version, a quantity below one,
  or existing-key mode without `key_id`
- **THEN** the domain rejects it before policy or settlement processing

#### Scenario: The domain is loaded beside the shipped domains

- **WHEN** the inference contract is discovered alongside the VM, bare-metal,
  and API-credit contracts
- **THEN** it satisfies the same supported contract version, registers a unique
  domain identity, and passes the shared domain conformance harness without
  modifying core

### Requirement: One listing is one served model

An inference listing MUST describe exactly one served model at one seller. Its
`listing_resource` MUST carry a non-empty seller-asserted `model_id`, an
`artifact_ref` naming the weights served under any scheme, the seller's
`served_model_name`, `context_length`, an enumerated `quantization`, an
architecture block naming modality, `supported_parameters`, an endpoint block
whose `api_style` is `openai.v1`, a complete rate card, a `provenance` of
`self-hosted` or `resold`, and `offering_mode` equal to `inference`; it MAY
carry an `artifact_digest`, a mutable `display_name`, a `model_owner` principal
distinct from the seller, and an `attestation` envelope. A listing omitting any
required field MUST be rejected at publication rather than published with the
field absent.

A listing SHOULD derive `model_id` by the domain's derivation rule — the
upstream owner and repository name, lowercased, with revision and quantization
suffixes stripped; the owner's namespace for private weights; the fine-tuner's
for a fine-tune — so that independent sellers of the same weights converge on
one identifier. Quantization, runtime, and context limits MUST be carried as
explicit fields and MUST NOT be the only place a deployment property is
expressed. The domain MUST NOT maintain a list of admitted models. A registry
MAY narrow the accepted `model_id` vocabulary by operator policy through its
filter specification and MUST NOT mint, resolve, or alias identifiers. A resold
listing is a legitimate listing.

#### Scenario: Seller serves several models

- **WHEN** a seller serves three models from one endpoint
- **THEN** it publishes three listings, each with its own `listing_id` and one
  model card, and a filter on one model's rate matches only that model's listing

#### Scenario: Two sellers serve the same weights

- **WHEN** two sellers independently derive `model_id` for the same upstream
  weights and publish with different `quantization`, `artifact_ref`, and rate
  cards
- **THEN** both listings carry the same `model_id`, a filter on it returns both,
  and filters on quantization and rate distinguish them

#### Scenario: Listing omits a required field

- **WHEN** a listing candidate lacks `context_length`, `provenance`, or a rate
  card entry
- **THEN** publication is rejected before the registry stores it

#### Scenario: Registry operator narrows the vocabulary

- **WHEN** a registry's filter specification enumerates the `model_id` values it
  accepts and a listing names another
- **THEN** the registry rejects the listing at validation, and no component of
  the domain or registry resolves or aliases the identifier

#### Scenario: Listing is resold

- **WHEN** a seller publishes a listing with `provenance: resold` fronting a
  model hosted elsewhere
- **THEN** the listing is accepted and discoverable, and a buyer may filter on
  provenance
### Requirement: Purchase is priced in settlement-asset base units

One inference credit MUST equal one base unit of the asset the selected
settlement option settles in. An inference settlement option MUST advertise a
per-credit rate of exactly one base unit, provision intent's `quantity` MUST be
read as base units purchased, and the scalar reference payment MUST equal that
quantity. Rate-card values MUST be read as base units of the same asset per
million tokens or per request.

#### Scenario: Buyer purchases a balance

- **WHEN** a buyer requests a quantity of 2,000,000 from a listing settling in an
  asset with six decimals
- **THEN** the reference payment is 2,000,000 base units (two whole units of the
  asset) and the issued key's balance is 2,000,000

#### Scenario: Seller advertises a non-unit credit rate

- **WHEN** an inference settlement option carries a per-credit rate other than
  one
- **THEN** the listing is rejected before publication
### Requirement: Rate card is integer-valued and pinned at issuance

A rate card MUST express base units per million prompt tokens and base units per
million completion tokens as non-negative integers, MAY express an integer flat
charge per request and integer rates for cached prompt tokens and images, and
MUST reject fractional or negative values. A credit grant MUST record the rate
card in force at issuance, and consumption against that grant MUST be priced by
the recorded card. A republished listing with a different rate card MUST affect
only grants issued after republication.

#### Scenario: Seller reprices after a sale

- **WHEN** a seller republishes a model's listing with higher rates after a buyer
  has purchased a balance under the previous card
- **THEN** the buyer's existing grant consumes at the previous card and only new
  purchases consume at the new one

#### Scenario: Rate card carries a fraction

- **WHEN** a rate card entry is not a non-negative integer
- **THEN** the listing is rejected before publication
### Requirement: Usage record and deterministic charge derivation

A usage record MUST carry the model and key the request ran under, a request
identity, prompt, completion, and cached-prompt token counts, and an outcome of
`completed`, `cancelled`, or `failed`. The charge for a record MUST be derived
only from that record and the grant's pinned rate card: the ceiling of the sum
of each token count multiplied by its per-million rate, plus the flat request
charge, for `completed` and `cancelled` outcomes; and zero for `failed`. Two
independent implementations given the same record and card MUST derive the
same integer charge.

#### Scenario: Streamed response is cancelled midway

- **WHEN** a client stops a streamed request after 400 completion tokens were
  produced against a card of 200 credits per million completion tokens with a
  request floor of 1
- **THEN** the record's outcome is `cancelled` and its charge is 1 credit, the
  ceiling of 0.08 plus the floor

#### Scenario: Upstream fails to answer

- **WHEN** the model server returns an error and no usable response
- **THEN** the record's outcome is `failed` and its charge is zero regardless of
  any token count it carries

### Requirement: Usage evidence is secret-free

Inference usage evidence MUST carry the usage record, the pinned rate card, the
derived charge, and the grant and fulfillment identities, and MUST NOT carry the
bearer secret, the prompt, the completion, or any response payload.

#### Scenario: Evidence is emitted for a completed request

- **WHEN** a usage evidence body is produced for any request
- **THEN** a canary bearer secret, prompt text, and completion text supplied to
  the producing code are absent from the serialized body

### Requirement: Attestation is reserved and unverified

The model card and the usage evidence MAY each carry an optional `attestation`
envelope with a `kind`, a `schema_version`, and an opaque `payload`. In this
version no component MUST verify, interpret, or act on its contents, a consumer
MUST treat a listing or record with the envelope exactly as one without it, and
a registry MUST NOT expose the envelope as a filter. A future proof format is
introduced as a new `kind` under the same envelope.

#### Scenario: Seller publishes an attestation nobody verifies

- **WHEN** a listing carries an `attestation` envelope
- **THEN** publication, discovery, negotiation, and settlement proceed exactly as
  for a listing without one, and no filter selects on its presence or contents
### Requirement: Bearer credential is delivery, not identity or payment authority

The inference domain MUST treat the marketplace principal that negotiates and
pays, the bearer credential that admits a request, and any authority that
authorizes spending as three separate identities. A bearer credential MUST admit
requests only against its own grant's balance and MUST NOT be accepted as
authorization to negotiate, purchase, top up another key, or authorize a charge
outside its grant.

#### Scenario: Bearer credential is presented to a market operation

- **WHEN** a bearer credential is offered as the credential for a negotiation,
  purchase, or top-up
- **THEN** the operation is refused as unauthenticated rather than treated as
  the key owner's marketplace signature

### Requirement: Admission authority is synchronous and singular

The inference authority that holds keys, grants, pinned rate cards, and
balances MUST be the only component consulted on whether a request may proceed.
An external rating, metering, or billing system MAY receive usage records as a
downstream feed and MUST NOT be consulted on the admission path or hold a
balance the authority treats as authoritative.

#### Scenario: Downstream rating system is unavailable

- **WHEN** a configured downstream usage consumer cannot be reached
- **THEN** admission decisions continue from the authority's own balance and the
  undelivered records are retained for later delivery rather than blocking
  requests

### Requirement: Discovery under the inference schema identity

A registry serving inference listings MUST declare schema identity `inference`
version `1` and MUST validate and filter listings from the inference filter
specification: exact filters on `model_id`, `model_family`, `quantization`,
modality, `supported_parameters`, and `provenance`; range filters on
`context_length` and on the rate card's base-unit integers; and the settlement
mechanism, asset, and funding projections. The inference buyer plugin MUST
declare the `inference` schema identity, MUST query only registries declaring
it, and MUST refuse to compile a rate bound that is not paired with a settlement
asset.

#### Scenario: Buyer bounds a rate

- **WHEN** a buyer queries with `settlement_asset` set and a maximum of 500 base
  units per million completion tokens
- **THEN** listings in that asset whose card exceeds 500 are excluded, and a
  listing missing the rate is excluded rather than matched

#### Scenario: Buyer bounds a rate without naming an asset

- **WHEN** a buyer supplies a rate bound and no settlement asset
- **THEN** the buyer plugin refuses to compile the query and names the pairing
  rule

#### Scenario: Compute and API-credit registries are also configured

- **WHEN** the buyer's configuration names a compute registry, an API-credits
  registry, and an inference registry
- **THEN** inference discovery queries only the registry declaring the
  `inference` schema identity
### Requirement: Quota-backed publication

An inference listing MUST identify an authoritative quota resource at a
configured site, and publication MUST require that resource to exist with
available credits. Reconciliation MUST close an open listing when authoritative
availability reaches zero and MAY reopen it when availability later becomes
positive; an unavailable authority MUST preserve the last complete listing state
rather than be read as zero.

The declared quota is a sales cap, not capacity. An inference listing MUST carry
the backed value of the declared backing property; a listing MUST NOT change
backing in place, and admitting the unbacked value is a filter-specification
version change.

#### Scenario: Seller declares no sellable quantity

- **WHEN** a seller submits an inference listing candidate with no quota resource
  or a zero declared quantity
- **THEN** publication is refused, because version 1 admits only the backed
  value, and the seller declares a cap instead

#### Scenario: Declared credits are sold out and later replenished

- **WHEN** reconciliation observes zero available credits for an open listing and
  later observes a positive quantity
- **THEN** it closes the listing and subsequently republishes it from the new
  authoritative view
