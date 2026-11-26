# inference Specification

## Purpose
The inference market domain's vocabulary: the `inference.v1` contract under
which a seller lists one served model with a model card and a rate card, a
buyer purchases credits at one base unit of the settlement asset each, a
request's consumption is recorded and charged deterministically, usage evidence
is signed without secrets, and a registry serves the `inference` schema
identity. See the [architecture companion](architecture.md).

## Requirements

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
required field MUST be refused before it is published: the domain's listing
codec refuses it on the storefront's publication path, and a registry serving
the inference specification refuses it against the served shape at publication
and in its dry-run validation. The codec also holds what the served shape
cannot express, the unit rate and the one-asset rule.

A listing SHOULD derive `model_id` by the domain's derivation rule — the
upstream owner and repository name, lowercased, with revision and quantization
suffixes stripped; the owner's namespace for private weights; the fine-tuner's
for a fine-tune — so that independent sellers of the same weights converge on
one identifier. Quantization and context limits MUST be carried as explicit
fields, and `model_id` MUST NOT be the only place a deployment property is
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
settlement option settles in. An inference settlement option MUST advertise
exactly one amount rate, of one base unit per credit, and so MUST an accepted
escrow, so no escrow's price is left to a seller's configured floor; provision
intent's `quantity` MUST be read as base units purchased, and the scalar
reference payment MUST equal that quantity. A rate card MUST name the asset its values are denominated in, and
every settlement option and escrow token on the listing MUST identify that
asset; rate-card values MUST be read as base units of it per million tokens
or per request. The domain's listing codec MUST refuse, before publication, a
listing whose settlement option or escrow advertises no amount rate, more than
one, a per-credit rate other than one, or another asset.

#### Scenario: Buyer purchases a balance

- **WHEN** a buyer requests a quantity of 2,000,000 from a listing settling in an
  asset with six decimals
- **THEN** the reference payment is 2,000,000 base units (two whole units of the
  asset)

#### Scenario: Seller advertises a non-unit credit rate

- **WHEN** an inference settlement option or accepted escrow carries a
  per-credit rate other than one
- **THEN** the listing codec rejects the listing before publication

#### Scenario: Option or escrow advertises no amount rate, or two

- **WHEN** an inference settlement option or accepted escrow carries no amount
  rate, or two
- **THEN** the listing codec rejects the listing before publication, so no
  published option is one a buyer cannot select and no escrow is priced by a
  configured floor

#### Scenario: Listing takes payment in a second asset

- **WHEN** a listing's rate card names one asset and a settlement option or an
  escrow token names another
- **THEN** the listing codec rejects the listing before publication, so a rate
  bound never reads the card in an asset the seller did not price in

### Requirement: Rate card is integer-valued and carried to issuance

A rate card MUST express base units per million prompt tokens and base units per
million completion tokens as non-negative integers, MAY express an integer flat
charge per request and integer rates for cached prompt tokens and images, and
MUST reject fractional or negative values. Rate-card amounts and the derived
charge MUST be carried on the wire as decimal-digit strings in the uint256
domain, never as JSON numbers, so a signed listing or usage-evidence body
stays canonical at any asset precision. The materialization handed to
issuance MUST carry the accepted listing and the rate card the grant is to pin,
and that card MUST equal the listing's card.

#### Scenario: Handoff carries a card other than the accepted listing's

- **WHEN** a materialization carries the accepted listing and a rate card with
  higher rates than that listing's card
- **THEN** the materialization codec refuses it, so issuance cannot pin a card
  the buyer did not accept

#### Scenario: Handoff omits the accepted listing

- **WHEN** a materialization carries a rate card and no accepted listing
- **THEN** the materialization codec refuses it, because there is nothing to
  hold the card to

#### Scenario: Rate card carries a fraction

- **WHEN** a rate card entry is not a non-negative integer
- **THEN** the listing is rejected before publication

#### Scenario: Seller prices on an eighteen-decimal asset

- **WHEN** a rate card carries an amount above the JSON-safe integer range
- **THEN** the card validates, the listing publishes under the publisher's
  canonical signature, and usage evidence pinning the card signs and verifies

### Requirement: Usage record and deterministic charge derivation

A usage record MUST carry the model and key the request ran under, a request
identity, prompt, completion, and cached-prompt token counts, a count of image
units, and an outcome of `completed`, `cancelled`, or `failed`. Its prompt
token count MUST exclude the cached prompt tokens it counts separately. The
charge for a record MUST be derived only from that record and the grant's
pinned rate card: the ceiling of the sum of each token count multiplied by its
per-million rate, plus the image units multiplied by the per-unit image rate,
plus the flat request charge, for `completed` and `cancelled` outcomes; and
zero for `failed`. A cached-prompt or image rate the card does not name MUST
be read as zero. Two independent implementations given the same record and
card MUST derive the same integer charge.

#### Scenario: Cached prompt tokens are priced at their own rate

- **WHEN** a completed record carries 1,000,000 prompt tokens and 1,000,000
  cached prompt tokens against a card of 500 credits per million prompt tokens
  and a request charge of zero
- **THEN** its charge is 500 credits where the card names no cached rate, and
  600 where it names 100 credits per million cached prompt tokens

#### Scenario: Streamed response is cancelled midway

- **WHEN** a client stops a streamed request after 400 completion tokens were
  produced against a card of 200 credits per million completion tokens with a
  request floor of 1
- **THEN** the record's outcome is `cancelled` and its charge is 2 credits: the
  ceiling of 0.08, which is one, plus the request charge of one

#### Scenario: Upstream fails to answer

- **WHEN** the model server returns an error and no usable response
- **THEN** the record's outcome is `failed` and its charge is zero regardless of
  any token count it carries

### Requirement: Usage evidence is secret-free

Inference usage evidence MUST carry the usage record, the pinned rate card, the
derived charge, the request identity, and the grant and fulfillment identities,
and MUST NOT carry the bearer secret, the prompt, the completion, or any
response payload. Its format MUST admit no free-form field: an attestation it
carries is a reference — a `kind`, a `schema_version`, and a `sha256` digest of
the proof, which is held elsewhere — never an opaque payload. Verification MUST
bind evidence to the grant and the request the consumer expects; the grant and
request identities together name one usage record.

#### Scenario: Evidence is emitted for a completed request

- **WHEN** a usage evidence body is produced for any request
- **THEN** a canary bearer secret, prompt text, and completion text supplied to
  the producing code are absent from the serialized body

#### Scenario: A producer places a secret in the attestation slot

- **WHEN** a usage evidence body is built with a canary bearer secret or prompt
  text as its attestation's payload, digest, or kind
- **THEN** the body is refused, so no signed evidence carries it: the reference
  admits no payload, a digest only as `sha256:` hex, and a kind only as a short
  lowercase identifier

#### Scenario: Evidence for another request is presented

- **WHEN** valid evidence for one request is verified against expected facts
  naming another request on the same grant
- **THEN** verification refuses it

### Requirement: Attestation is reserved and unverified

The model card MAY carry an optional `attestation` envelope with a `kind`, a
`schema_version`, and an opaque `payload` that MUST be canonical JSON, and the
usage evidence MAY carry an attestation reference as its own requirement
states. In this version no component MUST verify, interpret, or act on its contents, a consumer
MUST treat a listing or record with the envelope exactly as one without it, and
a registry MUST NOT expose the envelope as a filter. A future proof format is
introduced as a new `kind` under the same envelope.

#### Scenario: Seller publishes an attestation nobody verifies

- **WHEN** a listing carries an `attestation` envelope
- **THEN** publication, discovery, negotiation, and settlement proceed exactly as
  for a listing without one, and no filter selects on its presence or contents

### Requirement: Discovery under the inference schema identity

A registry serving inference listings MUST declare schema identity `inference`
version `1` and MUST validate and filter listings from the inference filter
specification: exact filters on `model_id`, `model_family`, `quantization`,
modality, `supported_parameters`, and `provenance`; range filters on
`context_length` and on the rate card's decimal-text amounts; an exact filter
on the rate card's asset; and the settlement mechanism and asset projections.
Each rate bound MUST declare `rate_card_asset` as a co-required filter, so a
registry refuses an unpaired bound rather than comparing across assets.

#### Scenario: Buyer bounds a rate

- **WHEN** a buyer queries with `rate_card_asset` set and a maximum of 500 base
  units per million completion tokens
- **THEN** listings in that asset whose card exceeds 500 are excluded, and a
  listing missing the rate is excluded rather than matched

#### Scenario: Buyer bounds a rate without naming an asset

- **WHEN** a query supplies a rate bound and no `rate_card_asset`
- **THEN** the registry refuses it rather than evaluating it
