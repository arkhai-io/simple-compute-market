# inference Specification

## Purpose
The inference market domain's vocabulary: the `inference.v1` contract under
which a seller lists one served model with a model card and a rate card, a
buyer purchases credits at one base unit of the settlement asset each, a
request's consumption is recorded and charged deterministically, usage evidence
is signed without secrets, and a registry serves the `inference` schema
identity; and the roles that sell under it over the `api` family kit — the
storefront, the authority service, the gateway in front of a model server, and
the buyer plugin — with their publication, issuance, admission, and time
controls. See the [architecture companion](architecture.md).

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
stays canonical at any asset precision. A materialization, the record of what
a grant was issued under, MUST carry the accepted listing and the rate card
the grant pins, and that card MUST equal the listing's card.

#### Scenario: Handoff carries a card other than the accepted listing's

- **WHEN** a materialization carries the accepted listing and a rate card with
  higher rates than that listing's card
- **THEN** the materialization codec refuses it, so no record of a grant shows
  a card the buyer did not accept

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

### Requirement: Inference roles are composed from independent distributions

The inference domain MUST be served by four roles, each an independently
installable distribution: a storefront that publishes model-card listings,
negotiates, verifies settlement, and requests issuance; an authority that holds
keys, grants, balances, and the quota ledger; a gateway that admits requests to
a model server; and a buyer plugin that discovers, negotiates, and settles. The
storefront and buyer plugin MUST register through the market-domain entry
points under the identity `inference`. No inference distribution may import an
API-credits distribution.

#### Scenario: Roles are installed

- **WHEN** the inference storefront and buyer distributions are installed from
  built wheels
- **THEN** each registers the `inference.v1` contract once under its entry-point
  group and loads without any API-credits distribution present

#### Scenario: A sibling domain is imported

- **WHEN** an inference module imports an API-credits module, including under
  `TYPE_CHECKING`
- **THEN** the boundary test fails naming the import

### Requirement: Alkahest is the only inference settlement mechanism

The inference storefront and buyer plugin MUST compose exactly one settlement
mechanism, `alkahest.v1`, and MUST NOT depend on the fiat payments
(`arkhai.payments.v1`) distribution. A configuration naming any other mechanism MUST be refused at
startup rather than ignored. The storefront's settlement composition MUST be
the kit's obligation list unmodified, so a second claimant in one deal is a
later addition to that list rather than a new mechanism.

#### Scenario: Another mechanism is configured

- **WHEN** a storefront configuration's settlement priority names a mechanism
  other than `alkahest.v1`
- **THEN** startup fails naming that mechanism before any request is served

#### Scenario: Role wheels are inspected

- **WHEN** the inference role wheels' requirements are read
- **THEN** none requires the fiat payments distribution

### Requirement: Issuance identifiers are inference-labelled and agree across the boundary

Inference issuance requests, results, evidence, and portable fulfillment
references MUST carry `inference` labels distinct from every other domain's, and
the storefront's issuance client and the authority MUST derive the same request
digest for the same request. Issued key identifiers MUST be distinguishable from
another domain's. A key issued for a purchase MUST hold a balance equal to the
purchased quantity, in base units of the settlement asset.

#### Scenario: A purchased balance is issued

- **WHEN** a buyer's purchase of 2,000,000 credits on a listing settling in an
  asset with six decimals settles and the key is issued
- **THEN** the authority holds a balance of 2,000,000 base units on the key

#### Scenario: The same request is digested on both sides

- **WHEN** a fixed issuance request is digested by the issuance client and by
  the authority
- **THEN** both produce the same bytes, and those bytes differ from the
  API-credits digest of the equivalent request

#### Scenario: A key is issued

- **WHEN** the inference authority issues a key
- **THEN** its identifier carries the inference prefix

### Requirement: Inference state is isolated

The inference authority and storefront MUST each persist to their own database,
shared with neither each other nor any other domain's services. An inference
key MUST NOT be accepted by another domain's authority, and another domain's key
MUST NOT be accepted by the inference authority.

#### Scenario: The stack is stood up beside API credits

- **WHEN** the inference and API-credits stacks run together
- **THEN** each authority and storefront uses an independent volume and no key
  issued by one authority verifies at the other

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

#### Scenario: The authority has no site identity

- **WHEN** the inference authority is started without a site signing credential
  or without any trusted caller role
- **THEN** it refuses to start before opening its database, and serves no route
  behind a shared secret instead

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

### Requirement: The issuance projection names the served model and pins the accepted terms

The inference storefront's issuance projection MUST digest the accepted
listing's `served_model_name` as the service identity and its `resource_id`
as the resource, MUST fill the subject's accepted terms with the canonical
JSON of the accepted card's `rate_card` and `attestation`, their digest, and
its request charge with the card's `request_credits`, and MUST deliver the listing's
`endpoint.base_url` as the connection payload's base URL, so a grant is bound
to the model name the gateway admits and to the price and attestation the
buyer accepted.

#### Scenario: Two listings of one model are purchased

- **WHEN** a buyer purchases from two sellers whose cards share a `model_id`
  but serve under different names
- **THEN** the two grants' digested service identities differ, and each
  credential's base URL is its own seller's gateway

### Requirement: The delivery's public result carries the accepted card

The inference storefront MUST extend the delivery's public result with the
contract's materialization built from the accepted listing the kit recorded
at acceptance, that listing's rate card, and the delivery context the kit
hands the extension (the mechanism and the escrow uid, with the issuance's
fulfillment id), under one key, so a buyer and an auditor read the rate the
purchase was made at. It is the buyer's copy of the
accepted terms: the storefront's accepted-listing artifact is the issuance
input, the authority's grant terms are what consumption and metering price
against, and one digest binds the three.

#### Scenario: The seller reprices between acceptance and fulfillment

- **WHEN** a negotiation is accepted and the seller republishes the listing with
  a different rate card before fulfillment completes
- **THEN** the public result's materialization carries the rate card in force
  at acceptance, and it validates against the listing it carries

### Requirement: Only request-priced rate cards are publishable without metered consumption

While the gateway charges a fixed amount on admission, the storefront MUST
refuse to publish a listing whose rate card has a non-zero prompt, cached-prompt,
completion, or image rate, or a `request_credits` of zero or above the
canonical JSON integer domain (`2^53 - 1`), and the gateway's charge per
admitted request MUST equal the published `request_credits`. A published
price MUST be one the seller charges and the issuance digest and ledger can
take.

#### Scenario: A per-token rate card is configured

- **WHEN** a seller configures a listing whose rate card has a non-zero
  completion rate
- **THEN** publication is refused naming that field and nothing is published

#### Scenario: A free request rate is configured

- **WHEN** a seller configures a listing whose rate card has a
  `request_credits` of zero
- **THEN** publication is refused naming `request_credits`, since the ledger
  cannot charge it

#### Scenario: A request-priced listing is consumed

- **WHEN** a buyer makes a successful request against a listing priced at one
  credit per request
- **THEN** the key's balance falls by exactly one credit

### Requirement: The gateway admits only paid requests for listed models

The gateway MUST expose chat completions and completions in the OpenAI
version-1 style and MUST forward a request only after the authority has
verified the bearer credential and charged it. A request naming a model the
gateway does not serve MUST be refused before any charge, so the gateway reads
the request body and checks the model before it verifies the key. The
gateway's executable MUST select the listing it fronts as the storefront's
one open listing for its configured resource and served model, read across
every page the storefront returns, retrying until the storefront has published
and refusing readiness on none or several, unless a listing id is configured; it MUST project that listing into the family's
offering, and the charge a request pays MUST be the `request_credits` the key
was issued under, returned by verification, so a republished price reaches
only keys issued after it. A retried request is a second charge, and a
request after a top-up is admitted once the gate's verification entry
expires, until metered consumption replaces the per-request charge. The gateway MUST
answer `401` for a missing or unknown credential, `403` for a revoked one, and
`402` with a pointer to where credits can be bought for an exhausted one. A
gateway MUST serve exactly one model at one configured charge, and its model
list MUST contain only that model. The inference authority MUST refuse a
verification or charge, batched or not, that names no key scope, so no caller
can reach a key except through the offering it was bought for.

#### Scenario: A key bought for another model is presented

- **WHEN** a buyer presents a funded key issued for model B to model A's
  gateway and requests model A
- **THEN** the gateway answers `403`, the model server receives nothing, and
  the key's balance is unchanged

#### Scenario: A caller names no scope

- **WHEN** a trusted caller verifies or charges an inference key, singly or in
  a batch, without naming a service and resource
- **THEN** the authority refuses it as `scope_required` and the key's balance
  is unchanged

#### Scenario: The gateway starts before the storefront has published

- **WHEN** the gateway starts with a resource and served model configured and
  the storefront has not yet published that listing
- **THEN** the gateway is not ready, retries the read, and becomes ready
  serving that listing once it is published

#### Scenario: A request names an unlisted model

- **WHEN** a request with a valid, funded key names a model the gateway does not
  serve
- **THEN** the gateway answers `404`, the model server receives nothing, and the
  key's balance is unchanged

#### Scenario: A key is exhausted

- **WHEN** a request arrives on a key with no remaining credits
- **THEN** the gateway answers `402` with the storefront and registry where more
  can be bought, and the model server receives nothing

#### Scenario: A buyer tops up

- **WHEN** a buyer purchases more credits onto an exhausted key
- **THEN** a request on that key is admitted once the gate's verification
  entry for it has expired

#### Scenario: A buyer tops up from another model's listing

- **WHEN** a buyer holding a key issued for one served model purchases onto it
  from the same seller's listing for another
- **THEN** the storefront's issuance is refused by the authority, the buyer
  plugin reports the key's scope, and the first model's balance is unchanged

### Requirement: The gateway and buyer carry verification seams for a later proof

The gateway MUST call a verification hook after the key is verified and
before it is charged, and the buyer plugin MUST call one before it proposes
settlement; the gateway's receives the offering's complete current canonical
terms and the key's accepted terms and digest as verification returned them,
so it can compare or verify against the accepted envelope, the plugin's the
envelope of the listing being bought, and either may refuse.
In this version both hooks admit everything, and the gateway image MUST be
built from digest-pinned inputs so a later proof format can measure it.

#### Scenario: No proof format is configured

- **WHEN** a request is admitted and forwarded, or a purchase proceeds to
  settlement, with no verification configured
- **THEN** behaviour is as without the hooks, and the hooks' presence is
  observable only in the gateway's and plugin's extension points

### Requirement: The buyer's credential stops at the gateway

The gateway MUST NOT forward the buyer's bearer credential to the model server.
A credential the model server requires MUST be the gateway's own, supplied from
a mounted secret.

#### Scenario: A request is proxied

- **WHEN** an admitted request is forwarded
- **THEN** the model server receives no `Authorization` value supplied by the
  buyer

### Requirement: Streaming responses are forwarded unbuffered

The gateway MUST forward a streamed response to the buyer as it arrives and
MUST NOT hold it until the model server finishes.

#### Scenario: A completion is streamed

- **WHEN** a buyer requests a streamed completion
- **THEN** the first event reaches the buyer before the model server has sent
  the last

### Requirement: The buyer plugin discovers by model card under the inference schema

The inference buyer plugin MUST declare the `inference` schema identity and
MUST query only registries declaring it. It MUST offer discovery filters for
model, model family, quantization, modality, supported parameter, provenance,
minimum context length, and the rate bounds, compiled from the registry's
served filter specification, and MUST resolve the rate-bound co-requirement
from that specification rather than from code, refusing an unpaired bound
before sending it. A completed purchase MUST give the buyer the key, the
gateway base URL, and the served model name.

#### Scenario: A buyer searches by model

- **WHEN** a buyer lists inference offers for a `model_id` with a compute
  registry, an API-credits registry, and an inference registry configured
- **THEN** only the registry declaring the `inference` schema is queried and
  only listings for that model are returned

#### Scenario: Buyer bounds a rate without naming an asset

- **WHEN** a buyer asks the plugin for a rate bound and no `rate_card_asset`
- **THEN** the plugin, compiling against the served specification, refuses
  before sending

#### Scenario: A buyer completes a purchase

- **WHEN** a purchase settles and a key is issued
- **THEN** the buyer is shown the key, the base URL, and the model name needed
  for a first request

### Requirement: Each inference party's time is configured and set through its own control

The inference service MUST install its process time source from `time.source`,
`"wall"` by default or `"injected"`. It MUST serve
`GET /api/v1/system/status`, a signed route admitting only the `admin` role,
carrying the time section, in either mode. Under injected time alone it MUST
serve `POST /api/v1/system/time`, a signed route admitting only the `admin`
role, taking `{"now": <Unix seconds>}`, answering
`{"source": "injected", "now": <Unix seconds>}`, refusing an earlier instant
with `409 time_moves_forward` and an invalid body with `422 invalid_time`. It
MUST serve both through the family authority's system route service, under the
family authority's route contracts, and MUST admit the gateway's `service` role
to neither.

The inference storefront MUST take its time source, its time-setting route and
its status's time section as `market-composition`'s "Storefront time is
configured and set through one kit route service" requires of every storefront.

The inference gateway MUST install its process time source from
`INFERENCE_GATEWAY_TIME_SOURCE`, `"wall"` by default or `"injected"`, refusing
to start on any other value, naming the setting and the value, and its gate
MUST read that source for every timestamp it signs and every response it
verifies. Under injected time alone the gateway MUST serve `POST /test/time`,
taking `{"now": <Unix seconds>}` and answering
`{"source": "injected", "now": <Unix seconds>}`, and `GET /test/status`,
reporting its source and now, each behind the control bearer token
`INFERENCE_GATEWAY_CONTROL_TOKEN` names, ahead of its gate and whether or not
its listing has loaded. A call without that token MUST be refused
`401 authentication_required` and change nothing. A gateway configured for
injected time with no control token MUST refuse to start, naming the token's
setting. On wall time the gateway MUST serve neither path.

#### Scenario: The administrator sets and reads the inference service's time

- **WHEN** the administrator sets an injected inference service at 1794822300
  to 1794823200, then to 1794822300
- **THEN** the first set answers source `injected` and now 1794823200 and the
  status reports the same, and the second is refused `409 time_moves_forward`

#### Scenario: The gateway's role reaches the service's time routes

- **WHEN** a request signed in the `service` role reaches
  `POST /api/v1/system/time` or `GET /api/v1/system/status`
- **THEN** each is refused `403` and the service's time is unchanged

#### Scenario: A wall-time inference service

- **WHEN** the inference service runs with `time.source` unset
- **THEN** its status reports source `wall` and `POST /api/v1/system/time`
  answers `404`

#### Scenario: The administrator sets the inference storefront's time

- **WHEN** the administrator sets an injected inference storefront at
  1794822300 to 1794823200 through the canonical storefront client
- **THEN** it answers source `injected` and now 1794823200, its status reports
  the same, and a set back to 1794822300 is refused `409`

#### Scenario: A wall-time inference storefront

- **WHEN** the inference storefront runs on wall time
- **THEN** its status reports source `wall` and its time-setting route answers
  `404`

#### Scenario: The gateway's time is set before its listing loads

- **WHEN** an injected gateway whose storefront has published no listing, and
  whose health reports it unready, is set one hour forward through its control,
  with its control token
- **THEN** the control answers source `injected` and the new instant, and the
  status reports the same

#### Scenario: A control call carries another token

- **WHEN** `POST /test/time` reaches an injected gateway with a bearer token
  other than its control token
- **THEN** it is refused `401 authentication_required` and the gateway's time
  is unchanged

#### Scenario: An injected gateway has no control token

- **WHEN** a gateway is composed on injected time with no control token
- **THEN** it refuses to start, naming `INFERENCE_GATEWAY_CONTROL_TOKEN`

#### Scenario: A wall-time gateway serves no control

- **WHEN** a gateway on wall time receives `POST /test/time`
- **THEN** it answers `404` as for any path it does not serve, and nothing is
  forwarded to the model server
