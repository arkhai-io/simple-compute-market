# Design

## Context

Verified against `origin/dev` at `c8318b6b` on 2026-09-21. Most of this is not
stated in any specification and the decisions below depend on it.

### What exists

| Concern | Where | What it does today |
|---|---|---|
| Prepaid access domain | `domains/apicredits/` | Listing names a `service_name`; provision intent is `quantity` + key disposition; settlement issues or tops up a bearer key; a gate consumes credits online |
| Consumption write path | `POST /api/v1/keys/{key_id}/consume` | Takes an arbitrary positive `amount` and an optional `idempotency_key`. Every caller passes `1`. Variable-amount consumption is supported and unused |
| Admission hold | — | None. Nothing reserves a worst-case cost before work runs |
| Gate charge model | `apicredits_middleware/gate.py` | Charges `amount_per_request` *before* proxying; optional optimistic batching flushes above a low-balance threshold |
| Gate outbound authentication | `apicredits_middleware/signing.py` | Signs as the `service` role under marketplace identity v2; `market_identity` is an optional extra so the published library keeps an httpx-only default |
| Issuance identity | `domains/apicredits/settlement/credits_client.py` and the mirror in `service/src/models/keys_model.py` | `fulfillment_id` derives from `obligation_ref` under a payload containing the literal `"domain": "api-credits"`; the request digest hashes a payload containing the literal schema string `arkhai.api-credits.issuance-request.v1`. Both strings are inside SHA-256 inputs |
| Settlement rate unit | `market_core.schemas.RateValue.per` | Free string, default `"hour"`. API-credits pricing accepts `credit`, `token`, `request` |
| Registry filter operators | `core/registry/src/api/filter_spec.py` | `in`, `not_in`, `range`, `exists`. Range bounds are float-parsed; exact-decimal ranges do not exist |
| Deployed filter specifications | `core/registry/Dockerfile` | Two: compute and API credits, each `COPY`ed into both stages and selected by `REGISTRY_FILTER_SPEC_PATH` |
| Second registry in Helm | `helm/Chart.yaml`, `helm/values.yaml` | The `registry` subchart is aliased as `api-credits-registry` with its own identity, descriptor, and filter-spec path |
| Storefront composition for a non-compute domain | `apicredits_storefront/domain_runtime.py` | Own executable on the `kit/storefront` shell, registered under `market.storefront_domains`. The compute-family shell (`market.storefront_contributions`) explicitly excludes API credits in `multi-domain-storefront-composition` |
| Domain conformance | `market_core.domain_conformance.assert_domain_conformance` | Shared harness every domain's six codecs pass |
| Inference anywhere | — | Nothing. No identity, schema, filter spec, or change |

### What changed since the investigation

Re-verified on 2026-09-24 against `origin/dev` at `29b84d82`. Four changes the
table above treated as pending have merged and been archived:
`capacity-resource-administration`, `project-capacity-resources-without-hosts`,
`pool-declared-advertisement-and-backing`, and `unbacked-listing-publication`.
Backing is now a declared property of every pool and listing, with promoted
requirements in `storefront-publication` and `registry-discovery`, and the
compute registry schema publishes it. `kit/capacity-publication`'s hooks moved
under that work, so any copy of the API-credits publication roles must be taken
from current `dev`. `publish-indicative-listing-rates` is design-complete and
unblocked. The decisions below were corrected in place; none was reversed.

### What planning settled before this change

Five points were settled during planning (2026-09-16 and 2026-09-19) and are
adopted here without re-arguing them:

1. Inference is its own domain, not API credits renamed.
2. What is reusable from API credits is issuance, stable fulfillment identity,
   request digest, evidence projection, and recovery — not balances or
   consumption semantics.
3. The bearer credential is delivery. It is neither marketplace identity nor
   payment authorization.
4. The SCM domain describes accepted prices and produces trustworthy usage
   evidence; how evidence becomes a charge on the hosted route is decided by
   services outside this workstream.
5. An external rating or billing system may consume usage records. It is never
   the synchronous admission authority.

## Goals / Non-Goals

**Goals.** A listing a buyer can compare across sellers per model. A purchase
that reuses the existing settlement and issuance flow unchanged. A consumption
vocabulary that expresses measured input, output, and cached tokens against a
rate card fixed at the moment credits were bought. A schema the registry can
validate and filter with the operators it has today.

**Non-Goals.** Composing a running stack, extracting anything, enforcing
metering, hosted fiat, seller packaging, or any deployment. Each is owned by a
named follow-on change.

## Decisions

### A domain, not an API-credits extension

API credits sells prepaid access to a *named service*. Its listing carries a
service name, an endpoint, and a quota; nothing on it says what is served, at
what context length, in what quantization, or what a unit of usage costs. A
buyer of inference compares exactly those things, so the domain's job is to
give the listing the **shapes** a buyer compares on: a model card, a rate card,
and a usage record.

What the domain does *not* do is decide what a storefront sells or what it
charges. Converting money into a balance is the payment kit's job (Stripe for
fiat, Alkahest for crypto) and is opaque to the domain. How a storefront prices
its balance against tokens is the storefront's declaration, made in the rate
card. And whether two storefronts' listings are comparable is whatever the
operator of the registry they publish to chooses to enforce — a registry here is
the analogue of an OpenRouter or a Featherless, and there is no promise of
compatibility between registries, nor within one unless its operator imposes it.

Inference is a domain rather than a field on API credits because the vocabulary
is different, not because the meaning of a credit is. Adding a model card to the
API-credits listing would make every weather-API seller carry a context length,
and one buyer plugin interpret two comparison surfaces. That alternative — a
`pricing_model` discriminator on the API-credits listing — was rejected on those
grounds.
### One listing is one served model

The registry compares listings, not sellers. A buyer asking "who serves this
model under this price with this context length" needs each answer to be a
listing. So a seller serving six models publishes six listings, each carrying
one model card, and `listing_id` is chosen by the seller per model.

The alternative — one listing per endpoint with a catalogue array inside —
was rejected: the registry's filters project over JSON paths and would match a
listing if *any* catalogue entry matched, so a price bound on one model would
surface a listing because a different model was cheap. Per-model listings make
every filter mean what it says.

### Model identity is seller-asserted and convergent

`model_id` is asserted by the seller. The domain does not maintain a list of
models and must not: which models are sold is the storefront's business, and
which of them a registry admits is its operator's. What the domain owns is a
**derivation rule**, shipped as a pure function sellers and the seller path can
call, so that two sellers of the same weights arrive at the same string without
anyone minting it:

- weights with a public upstream: the upstream owner and repository name,
  lowercased, with revision, branch, and quantization suffixes stripped
  (`meta-llama/llama-3.1-8b-instruct`);
- private weights: the model owner's namespace, not the seller's;
- a fine-tune: the fine-tuner's namespace, because it is different weights.

The spec says a listing **SHOULD** derive its identifier this way. A registry
operator who wants convergence enforced makes it a MUST for their registry by
narrowing the field in the filter specification — an `enum`, a pattern — which
is curation in the right place: an operator policy, outside the registry
service. The registry itself never mints, resolves, or aliases identifiers;
`registry-discovery` keeps it opaque to domain payloads, and federated
registries would otherwise let one string mean different things in two places.

Quantization, runtime, and context limits are **not** in the identifier. They
are explicit fields, so "every listing of this model" and "this model at fp8"
are both one query, and one fact has one name. `quantization` is an enumerated
field — initially `none`, `fp16`, `bf16`, `fp8`, `int8`, `int4`, `awq`, `gptq`,
extended additively. Aliases such as `latest` are not in the protocol; a listing
carries exactly one identifier, and `model_family` is the coarse grouping.

The exact source rides beside the identifier: `artifact_ref` names the weights
served, under any scheme including private ones, and `artifact_digest`
optionally carries an immutable hash. `display_name` is a mutable label with no
identity role. All are seller assertions, like every published field.

**Provenance and resale.** A listing carries a required, filterable
`provenance` of `self-hosted` or `resold`. Resale — fronting a model someone
else hosts — is a legitimate listing, stated as such. Misrepresentation (a
wrong derivation, `self-hosted` while proxying, model X while serving Y) is out
of scope for version-1 detection: it is a curation matter under the posture
Goal 7 records for rates, and later a reputation input. Buyer-side verification
is anticipated and unowned; the attestation envelope below is where it attaches.

**The three-party hook.** A listing MAY name a `model_owner` marketplace
principal distinct from the seller, for the case where the party who owns the
weights is not the party serving them. Nothing pays the owner in version 1 and
there is no royalty field: the direction of money in that arrangement — does the
host pay the owner a share, or does the owner pay the host to serve — is the
subject of a separate hosting domain, and settlement already carries a list of
obligations with their own payer and claimant, so paying a second party later is
wiring rather than a schema change. `provenance` can gain a `hosted-for-owner`
value under a version bump when that domain exists.

Rejected: `deployment_id` as a further identifier. A seller's deployment is
already identified by `storefront_url` plus the publisher-chosen, normatively
stable `listing_id`, and `served_model_name` is what a request names.
### One pricing layer: a credit is one base unit of the settlement asset

In inference, **one credit is one base unit of the asset the listing settles
in** — one micro-USDC, one cent, one wei. The settlement option therefore
advertises `{field: amount, per: credit, value: 1}`, `quantity` at purchase is
the number of base units the buyer puts on the key, and the rate card's integers
are prices in that asset: base units per million prompt tokens, base units per
million completion tokens, an optional flat charge per request, and optional
cached-prompt and image rates. A request's charge is the ceiling of the sum of
those products, in base units, and the key's balance is in the same unit.

This is what makes listings comparable. The number a buyer sees on the card is
the number the meter charges and the number the balance is kept in; there is
one authoritative figure, so nothing can drift, and a rate bound in a registry
query means what it says within an asset. Every settlement mechanism, issuance
path, and top-up flow applies unchanged, because the purchase is still "N
credits at a per-credit rate" — the rate is simply always one.

The alternative — a credit as an abstract unit each seller denominates, with the
rate card in credits per million tokens — was the design's first draft and was
rejected because it breaks comparison. Seller A at one base unit per credit
listing 500 credits per million and seller B at a hundred base units per credit
listing 5 credits per million charge the same real price and show numbers a
filter cannot relate. Two knobs per seller guarantee that denominations vary,
and a filter over the credit figure looks like a price filter and is not.

Costs, accepted: on an 18-decimal asset the integers are large (the existing
uint256 overflow guards apply); on a fiat-cent asset the finest expressible rate
is one cent per million tokens, which nobody undercuts. Integers remain required
so two independent implementations of the charge arithmetic cannot disagree by
rounding.
### The rate card is pinned at issuance

A grant carries the rate card in force when it was issued. A seller who
republishes a listing with a new card changes the price of *new* purchases only;
credits already bought consume at the rate the buyer saw when paying. Without
this, a seller could reprice sold credits after the escrow settled, and the
buyer would have no recourse because the settlement mechanism already closed.

This is stated normatively in the spec delta. The mechanism — where the pinned
card is stored and how the authority reads it on the consumption path — is
`meter-inference-usage`'s to implement; the invariant is this change's to state.

### Comparability without a derived price field

An earlier sketch published a derived monetary block computed from two
authoritative fields so the registry could range-filter a price. Rejected: a
derived field can drift from what it is computed from, and a buyer who accepted
on the derived number while settlement charged the authoritative one would be
charged a price they did not see. With one pricing layer the derivation is
unnecessary — the rate card *is* the price — so the rejection stands and the
problem it guarded against no longer exists.

What the registry filters on is therefore authoritative: `prompt_credits_max`
and `completion_credits_max` are upper bounds on the rate card's integers, and
`settlement_asset` selects the asset they are denominated in. A rate bound is
meaningful only alongside an asset, and the generic registry cannot yet express
"this filter requires that one" — `publish-indicative-listing-rates` is building
that declarative co-requirement. Until it lands, the **buyer plugin** enforces
the pairing: a rate bound without `--asset` is refused at query compilation, and
the seller path documents the same rule. Cross-asset comparison needs an
exchange rate the registry must not be an authority on, and stays client-side,
consistent with Goal 7.

**Revisit trigger:** when `publish-indicative-listing-rates` promotes filter
co-requirements, move the pairing rule from the buyer plugin into the inference
filter specification so the registry refuses an unpaired bound itself.
### Quota-backed publication in version 1

An inference seller's supply is, in truth, not finite in the way a GPU is: a
model server can keep serving. Backing is now a declared property of every pool
and listing — `unbacked-listing-publication` merged and was archived on
2026-09-24 — so the question is not whether the shape exists but which value
inference admits.

Version 1 admits only the backed value, and publishes exactly the way API
credits does: the listing names a `capacity_site_id` and a `resource_id` naming
a quota resource in the authority's ledger, the seller declares how many credits
it is willing to sell, the reconciler closes the listing at zero and reopens it
when quota is added, and issuance commits finite quota through an open-ended
reservation. The quota is a **sales cap**, not capacity: a seller whose declared
quota reaches zero leaves discovery while the model server is fine, so the
seller path should default it large. Inference carries the backing discriminator
from day one with backed as its only admitted value — the capacity variant of
the declared property, not a domain-local shape.

Admitting the unbacked value later is an inference filter-specification version
bump plus close-and-republish of affected listings, because backing is immutable
per durable listing. It is not a migration. What unbacked would buy an inference
seller is not declaring a sellable quantity and not being closed at zero — a
convenience, not a correctness property — so it waits for a seller to ask.

### Provision intent is the API-credits shape under a new kind

Round zero carries `ProvisionTerms{kind: inference.v1, version: 1, payload:
{quantity, key: {mode, key_id?}}}`. This is byte-for-byte the API-credits
payload shape. It is the right shape because the purchase layer *is* the same:
a buyer is buying N credits onto a new or existing key. What differs between the
domains is the listing and the consumption, not the purchase.

It is copied into `domains/inference/negotiation/terms.py`, not imported.
`ARCHITECTURE.md`'s dependency layers forbid a domain importing a sibling, and
the copy is small. Whether it becomes kit is `extract-access-issuance-kit`'s
question, answered with two consumers in view.

### Usage record and charge derivation are domain-owned deterministic semantics

`market-composition` requires a domain to own "the pure interpretation required
for independent implementations of that market to agree." The charge a request
costs is exactly that kind of interpretation, so this change defines it as a
pure function even though nothing enforces it yet.

A **usage record** carries: the model the request ran under, the key it ran
under, a request identity, prompt tokens, completion tokens, cached prompt
tokens, and an outcome. Outcomes are `completed` (usage is final), `cancelled`
(the client stopped the request; usage is what was produced before it stopped),
and `failed` (the upstream did not produce a usable response). Charge derivation
is `ceil(prompt × Rp/10^6 + cached × Rc/10^6 + completion × Rcomp/10^6 +
images × Ri) + request_floor` for `completed` and `cancelled`, and zero for
`failed`. A cancelled request is charged because the seller did the work; a
failed one is not because the buyer got nothing.

This gives `meter-inference-usage` a fixed target and gives conformance
something to pin across the Python, TypeScript, and Rust gates, which is
exactly where per-token billing would otherwise diverge silently.

### Usage evidence is secret-free

The usage evidence body — what a storefront or authority can sign and hand to a
resolver — carries the usage record, the pinned rate card, the derived charge,
and the grant and fulfillment identities. It never carries the bearer secret,
the prompt, the completion, or the response. This is the same rule the
API-credits issuance evidence enforces with a canary test, applied to usage.

### Attestation is reserved as an opaque, unverified envelope

The model card and the usage evidence each carry an optional `attestation`
field shaped as the repository's standard versioned envelope — `kind`,
`schema_version`, and an opaque `payload`. In version 1 it is empty, nothing
verifies it, and the registry does not expose it as a filter. Its purpose is to
fix *where* a proof attaches — to the listing (what the seller claims to run)
and to each usage record (what served this request) — while the two shapes are
being designed together, and to give a future trusted-execution proof a place
to land as a new `kind` rather than a schema change.

The envelope is deliberately not a promise: a value in it is a seller assertion
that nothing checks, which is why the spec states it is unverified and why it
cannot be selected on. Defining the first `kind` is separate, later work whose
input is the verification chain a comparable open-source market already ships —
platform, measurement, and verifier on the listing; a check at purchase; a check
per request — read before the field's shape is fixed.

### Three identities, restated for this domain

The API-credits architecture companion already separates a marketplace principal
(who may negotiate and buy), a bearer credential (what admits a request), and
canonical ownership (who may top up a key). Inference keeps all three separate
and states the consequence normatively: the bearer credential is delivery of
what was bought, and its balance is not payment authorization for anything
else. A hosted route that adds a spending authority does so beside these, not
by merging them. In one sentence: an API credential is access, not the billing
model.

### The authority stays synchronous; rating systems are downstream

The inference authority — the service that holds keys, grants, pinned rate
cards, and balances — is the only thing consulted on the admission path.
External rating or billing platforms (Metronome, OpenMeter, Formance were the
ones evaluated) may receive usage records as a downstream feed and are never
asked whether a request may proceed. They assume one merchant billing many
customers, are not in the request path, and would make every seller depend on a
third party's availability to serve a request. Keeping them at the usage-record
seam preserves seller autonomy and provider neutrality, which is the SCM
posture.

### Storefront composition mirrors API credits

The stack change will give inference its own storefront executable on the
`kit/storefront` shell, registered under `market.storefront_domains`, exactly as
API credits is composed. The compute-family shell that hosts VM and bare metal
together is scoped by `multi-domain-storefront-composition` to compute-family
contracts and names generalizing to API credits as a non-goal; inference is
non-compute in the same way. Recorded here because the listing shape (no
`CapacityBinding` to a Resource Pool; a quota resource instead) follows from it.

### Copy first, extract after two consumers

The campaign's sequencing rule, stated once: `compose-inference-domain-stack`
copies the API-credits issuance client, fulfillment orchestration, evidence
projection, and publication roles into `domains/inference/` with the issuance
label changed to `inference`; `extract-access-issuance-kit` then moves what both
copies share into kit and deletes both copies.

The reason is narrow. The issuance *label* is not the difficulty: it appears in
three places per side, and a regression test that pins the digest bytes for a
fixed input set proves a parameterization byte-identical with one consumer —
that pin is the extraction change's first task. What is not knowable from one
consumer is the boundary inside `fulfillment.py`, where issuance and the quota
commit are tangled, and how the authority service should be packaged. Those two
questions are answered by having a second, working consumer in view.

Two rules keep the copy cheap:

- **Copies are frozen.** No feature work in a copied module until extraction
  lands. A copy that diverges is no longer a copy, and extraction becomes a
  reconciliation.
- **Extraction blocks metering.** `meter-inference-usage` is the change that
  mutates the authority; it does so against the kit-composed authority, once,
  after `extract-access-issuance-kit` is accepted. "Sequenced, whichever lands
  second rebases" was the earlier posture and is withdrawn: if metering landed
  first, extraction would be separating one copy from one that had diverged in
  exactly the module it needs to move.
### Schema identity and filter specification

Schema identity is `inference`, version 1; filter-specification version 1. The
buyer plugin declares `inference` and therefore queries only registries
declaring it, which keeps inference discovery off the compute and API-credits
registries — the same load-bearing schema identity API credits relies on.

Filters: `model_id`, `model_family`, `quantization`, `modality`,
`supported_parameter`, and `provenance` are exact `in` filters, fail-on-missing
where the field is required. `context_length_min` is a lower-bound range.
`prompt_credits_max` and `completion_credits_max` are upper-bound ranges over the
rate card's base-unit integers, paired with `settlement_asset` by the buyer
plugin as described above. The token, mechanism, asset, and funding projections
are copied from the API-credits specification. `offering_mode` is required and
equals `inference`. The attestation envelope is **not** a filter.
### OpenAI-compatible surface, version 1

`endpoint.api_style` is `openai.v1` and names chat completions and completions.
Embeddings, images, audio, and batch are excluded from version 1 so that the
usage record has one shape. Adding a modality later adds rate-card fields and
usage fields under a version bump, not a reinterpretation.

## Risks / Trade-offs

- **Transient duplication.** The stack change ships a second copy of the
  issuance machinery. Mitigated by the extraction change's rule that no
  domain-local copy survives, and by the API-credits regression suite pinned
  before extraction.
- **Integer granularity.** On a fiat-cent asset the finest rate is one cent
  per million tokens; on an 18-decimal asset the integers are large. Neither
  prices anyone out; the overflow guards already exist.
- **Declared finite supply.** Quota-backed publication means a seller declares
  a sellable credit quantity that a model server does not physically enforce.
  This is API credits' posture today and inherits its limits; the quota is a
  sales cap, and admitting the unbacked backing value later is a
  filter-specification bump, not a migration.
- **A rate bound without an asset is meaningless, and the registry cannot yet
  refuse one.** Mitigated by the buyer plugin refusing to compile it, until
  filter co-requirements land and the rule moves into the specification.
- **Cross-asset comparison is client-side.** Accepted for the reasons
  `publish-indicative-listing-rates` records.
- **Identifier convergence is a SHOULD.** Two sellers may still name the same
  weights differently. Mitigated by the shipped derivation function, by
  `model_family` grouping, and by a registry operator who can make the rule a
  MUST for their registry; misrepresentation is a curation and reputation
  matter, not detected in version 1.

## Open questions

Each carries its revisit trigger. None is prescribed by a task in this change;
where a task touches one it is an explicit decision gate.

1. **Registry-side pairing of a rate bound with its asset.** Trigger:
   `publish-indicative-listing-rates` promotes declarative filter
   co-requirements; the rule then moves from the buyer plugin into the
   inference filter specification.
2. **Admitting the unbacked backing value for inference listings.** The
   property exists; the trigger is a seller who needs it. Cost: an inference
   filter-specification bump and close-and-republish.
3. **Whether the inference authority is the same kit-composed service binary as
   API credits deployed twice, or a distinct distribution.** Owned by
   `extract-access-issuance-kit`; irrelevant to this change's vocabulary.
4. **Pre-flight token estimation source** (vLLM `/tokenize` versus a local
   tokenizer). Owned by `meter-inference-usage`.

## Migration Plan

Additive. No existing wire shape, database, deployment, or distribution
changes. Rollback is deleting the new wheel and the registry image's two `COPY`
lines; no deployed registry selects the new specification until an operator sets
`REGISTRY_FILTER_SPEC_PATH` to it.
