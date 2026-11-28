# Inference Architecture

The [normative contract](spec.md) defines the inference domain's vocabulary —
its listing, its pricing, its usage record and charge, its usage evidence, and
its discovery — and the roles that sell under it. This document explains the
shape of the market, how the roles compose the `api` family kit, and why each
part is cut as it is.

## Market shape

A seller serves a model and sells requests against it to many buyers at once. A
buyer compares sellers per model on context length, quantization, and price per
token, buys credits through any settlement mechanism the listing accepts, and
receives a bearer credential.

```text
model-card listing
      ↓ quantity-priced negotiation, one base unit per credit
verified settlement
      ↓ issuance carrying the accepted listing's rate card
key balance in the settlement asset's base units
      ↓ consumption priced by the pinned rate card
usage record → deterministic charge → usage evidence
```

The domain owns the shapes a buyer compares on: a model card, a rate card, and
a usage record. It does not decide what a storefront sells or what it charges.
Converting money into a balance is the settlement mechanism's and is opaque to
the domain; how a storefront prices its balance against tokens is the
storefront's declaration, made in the rate card; and whether two storefronts'
listings are comparable is whatever the operator of the registry they publish
to enforces. A registry is a model catalogue separated from payment, routing,
and the provider relationship, and nothing promises compatibility between
registries, nor within one unless its operator imposes it.

Inference is a domain beside API credits, not a field on its listing, because
the vocabulary differs and the meaning of a credit does not. An API-credits
listing names a service; nothing on it says what is served, at what context
length, in what quantization, or what a unit of usage costs. A model card on
that listing would make every seller of any API carry a context length, and one
buyer plugin interpret two comparison surfaces.

## One listing, one served model

The registry compares listings, not sellers, so each answer to "who serves this
model under this price with this context length" is a listing: a seller serving
six models publishes six, each carrying one model card. A catalogue of models
inside one listing would let a filter match on any entry, so a price bound on
one model would surface a listing because another model was cheap. One model
per listing makes every filter mean what it says.

### Model identity

`model_id` is asserted by the seller. The domain keeps no list of models: which
models are sold is the storefront's business, and which a registry admits is
its operator's. What the domain owns is a derivation rule, shipped as a pure
function, so two sellers of the same weights arrive at the same string without
anyone minting it:

- weights with a public upstream: the upstream owner and repository name,
  lowercased, with revision, branch, and quantization suffixes stripped;
- private weights: the model owner's namespace, not the seller's;
- a fine-tune: the fine-tuner's namespace, because it is different weights.

The rule is a SHOULD. A registry operator who wants convergence enforced
narrows `model_id` in the filter specification the registry serves, to an
enumeration or a pattern. That is curation in the right place, an operator's
policy outside the registry service, which never mints, resolves, or aliases an
identifier.

Quantization and context limits are explicit fields and not parts of the
identifier, so "every listing of this model" and "this model at fp8" are
each one query and one fact has one name. `artifact_ref` names the weights
served under any scheme, `artifact_digest` optionally pins them, and
`display_name` is a mutable label with no identity role. All are seller
assertions, as every published field is.

### Provenance and the model owner

`provenance` is required and filterable: `self-hosted`, or `resold` for a
listing fronting a model someone else hosts, which is a legitimate listing
stated as such. A listing may name a `model_owner` principal distinct from the
seller, for weights owned by a party that does not serve them. Nothing pays
that owner and the card has no royalty field: settlement already carries a
list of obligations each with its own payer and claimant, so paying a second
party is wiring a later domain adds, not a change to this card.

## One pricing layer

One credit is one base unit of the asset the listing settles in. The settlement
option advertises one base unit per credit, `quantity` at purchase is the number
of base units the buyer puts on the key, and the rate card's integers are prices
in that asset. The number a buyer sees on the card is the number a meter charges
and the number the balance is kept in, so there is one authoritative figure and
a rate bound in a registry query means what it says within an asset. Every
settlement mechanism, issuance path, and top-up flow applies unchanged, because
a purchase is still a quantity of credits at a per-credit rate, and the rate is
always one.

A credit as an abstract unit each seller denominates would break comparison:
one seller at one base unit per credit listing 500 credits per million tokens
and another at a hundred base units per credit listing 5 charge the same real
price and show numbers a filter cannot relate.

The card names its asset, and the listing codec refuses a settlement option or
escrow token naming another, because the card's integers are base units of
exactly one asset and a listing taking payment in two would let a discovery
bound read them in whichever matched. The codec also requires every option and
accepted escrow to advertise exactly one amount rate, of one per credit, so no
published price is left to a seller's configured floor.

Integers are required so two implementations of the charge arithmetic cannot
disagree by rounding. Amounts travel as decimal-digit strings, since canonical
JSON has no number form above 2⁵³ − 1 and both the published listing and the
usage evidence are signed canonically; token counts stay plain integers, the
magnitude living in the charge.

### The rate card at issuance

Issuance takes the accepted listing, whose rate card the grant pins. The
materialization is the record of that grant, carrying the accepted listing and
its rate card, and the codec refuses a card other than that listing's. A grant that
records the card it was issued under lets a seller's republication reprice new
purchases only: credits already bought consume at the rate the buyer saw when
paying, after the settlement mechanism has closed and the buyer has no other
recourse.

### Comparing prices

The registry filters on the authoritative figures: upper bounds on the card's
prompt and completion rates, each co-requiring the card's asset, so the registry
refuses a bound without one. No derived price field is published, because a
derived figure can drift from what it is computed from and a buyer accepting on
it would be charged a price they did not see. Comparing across assets needs an
exchange rate the registry is no authority on, and stays with the client.

## Usage, charge, and evidence

The charge a request costs is the kind of interpretation independent
implementations of a market must agree on, so the domain defines it as a pure
function of a usage record and a rate card. A cancelled request is charged for
what was produced, because the seller did the work; a failed one costs nothing,
because the buyer got nothing. A record's prompt tokens exclude the cached
prompt tokens it counts separately, which matters to whatever fills a record
from an upstream that reports cached tokens as a subset.

Usage evidence carries the record, the pinned card, the derived charge, and the
grant and fulfillment identities, and never the bearer secret, the prompt, the
completion, or the response. Verification binds a body to the grant and the
request its consumer expects, since a body is self-consistent for any of each.

## Attestation

The model card may carry an attestation envelope, and usage evidence a digest
reference to a proof held elsewhere. The evidence carries a reference and not an
envelope because an opaque field in signed, durable evidence could carry a
prompt or a secret, and the format has to keep it secret-free whatever a
producer does. Both fix where a proof attaches, to the listing for what the
seller claims to run and to each usage record for what served a request, so a
trusted-execution proof lands as a new `kind` and not a change of shape.
Nothing verifies either, a value in the envelope is a seller's assertion, and
the registry exposes neither as a filter.

## Identities and the admission authority

A marketplace principal negotiates and buys; a bearer credential admits a
request; canonical ownership decides who may top up a key. The three stay
separate: the bearer credential is delivery of what was bought, and its balance
authorizes payment for nothing else. A deployment that adds a spending
authority does so beside these.

The usage record is the seam at which a rating or billing platform attaches,
downstream of the authority holding keys, grants, pinned rate cards, and
balances. Such platforms assume one merchant billing many customers and sit
outside the request path, so putting one on the admission path would make every
seller depend on a third party's availability to serve a request.

## Composition

Inference is a domain of the `api` family. Its provision intent is the family's
purchase shape bound under the inference kind, because the purchase layer is
the same as API credits': a quantity of credits onto a new or an existing key.
What differs between the two domains is the listing and the consumption.

The domain binds the family's shapes and does not copy API credits' roles. The
roles of a market selling prepaid bearer access are one machinery, shared
whole: issuance and its digests, the authority's key service and ledger, the
storefront's settlement composition, and the buyer flows do not depend on what
is served. So the family's vocabulary and kit hold them, and a domain
contributes its listing schema, its publication guard, its materialization,
and its wiring.

An inference storefront is its own executable on the storefront shell,
registered as a storefront domain as API credits is, and not one of the compute
contributions the VM storefront executable selects. Its listing therefore binds a quota resource in the
authority's ledger, not a capacity binding to a resource pool.

## Role composition over the family kit

Four distributions compose the market, each a thin root over the family kit:
the storefront, the authority service, the gateway executable, and the buyer
plugin. The issuance label and the accepted-terms payload live in the domain
package, because two roots use each and one composition root cannot import
another: the storefront and the service compose the label, and the storefront
and the gateway build the terms payload.

The storefront fills the family's selling contributions. Its publish request
carries a model card, and its publication mapping fills the card's resource,
site, and offering mode from the quota resource the request names, so a seller's
card cannot name a resource other than the one its quota backs. Its issuance
projection names the served model as the digested service, so a grant is bound
to what the gateway admits in a request's `model` field, and delivers the
gateway's address as metadata outside the digest; the convergent `model_id`
stays in the accepted listing the kit pins. Its public-result extension places
the contract's materialization in the delivery, built from the accepted listing
and its rate card with the settlement reference the delivery context carries,
so the public record cannot show a buyer a rate they did not accept. The
storefront composes no dispute policy, because it settles through Alkahest
alone and reads no dispute authority.

The accepted terms then exist in three places, each with one role and all bound
by one digest: the storefront's accepted-listing artifact, which is the issuance
input and the seller's record; the authority's `grant_terms` row, which
consumption is charged against; and the public materialization, which is the
buyer's and an auditor's copy.

The storefront starts without its dependencies. It refuses at startup only what
waiting cannot repair — an unset authority address, a missing signing
credential or authority trust set, an unreadable capacity configuration, a
settlement priority naming a mechanism it does not compose — and otherwise
waits: the listing seed waits for the authority, the chain probe owns the chain
clients, and readiness reports a chain that does not answer. Its `publish` and
`listings` commands are clients of the running storefront. The seller is one
account, the one its wallet key signs as.

The authority service is the family authority composed under the inference
label, on its own database, which the family authority chain builds. It has no
shared-secret gate behind its signed authentication and refuses to start
without a signing credential and a trusted role.

The gateway executable reads the listing it fronts from the storefront that
published it, since a registry's copy can lag a republication and the two are
deployed together. It finds the listing by the quota resource and served model
name it is configured with, reading every page of the storefront's open
listings and refusing readiness on zero or several matches, and retries until
the storefront has published. It validates the listing, refuses one that is not
request-priced, and projects it to the family's gateway offering. It signs
toward the authority as the `service` role.

The buyer plugin fills the family's buying contributions and compiles its
discovery filters from the specification the registry serves, so it encodes no
rule pairing a rate bound with an asset. Its one settlement stage carries the
purchase-time verification hook.

## Verification seams

The contract fixes where a proof attaches; the roles carry the seams a first
proof format needs, each admitting everything. The gateway runs a hook per
request, after the key is verified and before it is charged, with the
offering's current rate card and attestation, the key's accepted terms, and
their digest, so a proof can refuse a credential whose seller changed the
attestation or the price since the buyer accepted, or verify against the
accepted envelope the authority holds. The buyer plugin runs a hook before it
proposes settlement, with the listing's attestation envelope. The gateway image
is built from a digest-pinned base, the input a measurement of it needs. No
proof `kind` is defined.

## Current limits

- Consumption is a flat charge per request: the storefront publishes only a
  card whose per-token and image rates are zero and whose request charge is
  between one and 2⁵³ − 1, the range the authority's ledger and the issuance
  digest both carry, and the gateway charges that amount. Pricing by measured
  usage replaces the guard and the charge together.
- A retried request is charged twice, as the family gate charges it.
- A republished price reaches new keys only. A key keeps the charge its first
  grant accepted, and a top-up under other terms is refused, so one balance
  never mixes two prices.
- A request straight after a top-up is refused until the gate's cached
  verification of the exhausted key expires.
- Alkahest is the one settlement mechanism. The storefront's settlement
  composition is the kit's obligation list unmodified, so a second claimant in
  a deal, such as a model owner, is an addition to that list and not a new
  mechanism.
- After each reconcile the storefront closes, at each registry, the open
  inference listings under its identity that it does not hold open. Two
  inference storefronts sharing one identity and one registry would close each
  other's listings.
- A listing publishes against a declared, finite quota, the backed value of
  the backing property every pool and listing declares. The quota is a sales
  cap and not capacity: a model server keeps serving after a seller's declared
  quota reaches zero and its listing leaves discovery. Admitting the unbacked
  value is a filter-specification version bump with the affected listings
  closed and republished, since backing is immutable for a durable listing; a
  seller who needs it is the trigger.
- Nothing fills a usage record or signs usage evidence: the vocabulary and its
  verifier exist, and no component meters a request.
- Identifier convergence is a SHOULD. Two sellers may name the same weights
  differently; the derivation function, `model_family`, and an operator's
  narrowed specification mitigate it. Misrepresentation — a wrong derivation,
  `self-hosted` while proxying, one model named while another is served — is
  not detected.
- The surface is `openai.v1`, chat completions and completions. Embedding,
  image-generation, audio, and batch endpoints are outside it, so the usage
  record has one shape; an image given as input to a chat completion is priced
  by the card's per-unit image rate.
- On an asset with cents as its base unit the finest expressible rate is one
  cent per million tokens.
- The model card requires `endpoint` and the rate card `asset`: an address a
  seller writes by hand, which nothing checks, and a second statement of the
  asset beside the settlement option's.

## Related contracts

- [Inference](spec.md)
- [API family](../api-family/spec.md)
- [API credits](../api-credits/spec.md)
- [Market composition](../market-composition/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
