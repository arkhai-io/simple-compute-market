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
`listing_resource` MUST carry a canonical `model_id`, an `artifact_ref` naming
the exact weights it serves, the seller's `served_model_name`, `context_length`,
`quantization`, an architecture block naming modality, `supported_parameters`,
an endpoint block whose `api_style` is `openai.v1`, a complete rate card, and
`offering_mode` equal to `inference`; it MAY carry an `artifact_digest` and a
mutable `display_name`. A listing omitting any field a buyer filters on MUST be
rejected at publication rather than published with the field absent.

`model_id` MUST identify the logical model — one weights lineage at one version
— under the domain-defined canonical format: lowercase, `<org>/<name>`, with the
version inside the name and no alias segment such as `latest`. Quantization,
runtime, and context limits MUST NOT be encoded in `model_id`; they are explicit
fields. A fine-tune is a different logical model and MUST carry its own
`model_id`. The domain MUST own the format. A registry MUST validate the format
from its filter specification and MAY restrict the accepted vocabulary by
operator policy, but MUST NOT mint, resolve, or alias identifiers.

#### Scenario: Seller serves several models

- **WHEN** a seller serves three models from one endpoint
- **THEN** it publishes three listings, each with its own `listing_id` and one
  model card, and a filter on one model's rate matches only that model's listing

#### Scenario: Listing omits a comparison field

- **WHEN** a listing candidate lacks `context_length`, `quantization`, or a rate
  card entry
- **THEN** publication is rejected before the registry stores it

#### Scenario: Two sellers serve the same logical model

- **WHEN** two sellers publish listings carrying the same `model_id` with
  different `artifact_ref`, `quantization`, and rate cards
- **THEN** both are stored under their own `listing_id`, a filter on that
  `model_id` returns both, and a filter on rate distinguishes them

#### Scenario: Identifier violates the canonical format

- **WHEN** a listing's `model_id` carries uppercase, an alias segment such as
  `latest`, or an encoded quantization
- **THEN** publication is rejected before the registry stores it

#### Scenario: Registry operator narrows the vocabulary

- **WHEN** a registry's filter specification enumerates the `model_id` values it
  accepts and a listing names another
- **THEN** the registry rejects the listing at validation, and no component of
  the domain or registry resolves or aliases the identifier

### Requirement: Purchase is priced per credit

Inference negotiation MUST interpret an advertised settlement rate as a
per-credit rate with `per` equal to `credit`, and MUST compute the scalar
reference payment as quantity multiplied by that rate in payment base units.
Seller and buyer policy MUST evaluate offers against that same quantity-scaled
amount. The rate card MUST NOT participate in the purchase price.

#### Scenario: Buyer requests credits

- **WHEN** a buyer requests one million credits from a listing whose selected
  option's rate is 3 base units per credit
- **THEN** buyer and seller policy use 3,000,000 base units as the scalar
  reference payment regardless of the listing's rate card

### Requirement: Rate card is integer-valued and pinned at issuance

A rate card MUST express credits per million prompt tokens and credits per
million completion tokens as non-negative integers, MAY express an integer flat
charge per request and integer rates for cached prompt tokens and images, and
MUST reject fractional or negative values. A credit grant MUST record the rate
card in force at issuance, and consumption against that grant MUST be priced by
the recorded card. A republished listing with a different rate card MUST affect
only grants issued after republication.

#### Scenario: Seller reprices after a sale

- **WHEN** a seller republishes a model's listing with higher rates after a buyer
  has purchased credits under the previous card
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
modality, and `supported_parameters`; range filters on `context_length` and on
the rate card's integer credit rates; and the settlement mechanism, asset, and
funding projections. The inference buyer plugin MUST declare the `inference`
schema identity and MUST query only registries declaring it.

#### Scenario: Buyer bounds a rate

- **WHEN** a buyer queries with a maximum of 500 credits per million completion
  tokens
- **THEN** listings whose card exceeds 500 are excluded, and a listing missing
  the rate is excluded rather than matched

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

#### Scenario: Declared credits are sold out and later replenished

- **WHEN** reconciliation observes zero available credits for an open listing and
  later observes a positive quantity
- **THEN** it closes the listing and subsequently republishes it from the new
  authoritative view
