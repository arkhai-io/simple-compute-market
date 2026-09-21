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

### What the surrounding conversations settled

The Discord planning threads (2026-09-16 and 2026-09-19) and the earlier
Stripe-integration thread converged on five points this design adopts without
re-arguing them:

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

API credits leaves the meaning of a credit to the seller: one credit is whatever
the gated service charges per admitted request, and the listing says nothing
about it. That is right for a market that sells access to any API, and it has
consumers beyond inference that depend on it staying generic.

Inference needs the opposite. Two sellers' listings are only comparable if a
credit means the same kind of thing on both — a fixed number of tokens on a
named model. Fixing that meaning is what a domain does. It is not a field API
credits could grow, because the moment API credits says "a credit is N tokens,"
every weather-API seller has to have a tokenizer.

The alternative — a `pricing_model` discriminator on the API-credits listing —
was rejected because it makes one listing schema carry two incompatible
comparison surfaces and one buyer plugin interpret both.

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

### Two pricing layers, and a credit is the joint

Purchase is priced per **credit**, exactly as API credits prices it:
`settlement_options[*].rates` carries `{field: amount, per: credit, value: N}`
in payment base units, and the negotiated scalar is `quantity × N`. Nothing in
settlement, issuance, or the settlement runtime changes.

Consumption is priced per **token** through the model card's **rate card**:
integer credits per million prompt tokens, integer credits per million
completion tokens, an optional integer flat charge per request, and optional
integer rates for cached prompt tokens and images. A request's charge is the
ceiling of the sum of those products, in credits.

Keeping the credit as the unit that changes hands means every existing
settlement mechanism, issuance path, and top-up flow applies unchanged, and a
seller keeps its choice of asset. The cost is that a buyer computing price per
million tokens in an asset has to multiply the two layers together; that is a
buyer-side computation and is discussed under comparability below.

Integers are required at both layers. `pricing.py` in API credits already
refuses fractional base units and overflow; the rate card follows the same rule
so that two independent implementations of the charge arithmetic cannot
disagree by rounding. A seller who wants a price below one credit per million
tokens chooses a finer credit by lowering the per-credit settlement rate.

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

An earlier sketch published a derived `discovery_pricing` block — credits per
million multiplied through the settlement rate into asset base units — so the
registry could range-filter a monetary price. Rejected. A derived field can
drift from the two authoritative fields it is computed from, and a buyer who
accepted a deal on the derived number while settlement charged the authoritative
one would be charged a price they did not see. Guarding against that needs
recompute-on-publish and buyer-side re-derivation before accept, which is a lot
of machinery to protect a convenience.

What the registry filters on instead is what is authoritative: the rate card's
integer credit rates (ranges work on integers today) and the settlement asset
(`settlement_options[*].asset`, already projected for API credits). A buyer
comparing two sellers in the same asset divides one integer by another. A buyer
comparing across assets needs an exchange rate, which the registry must not be
an authority on — the same reasoning `publish-indicative-listing-rates` records
for compute.

That change is also building the two generic primitives a monetary rate filter
actually needs: an exact-decimal filter value type and declarative filter
co-requirements. Inference must not duplicate them. **Revisit trigger:** when
`publish-indicative-listing-rates` lands, decide whether an inference listing
publishes an `asking_rate` per million tokens in the settlement asset, reusing
its shape. Until then, comparability across assets is client-side.

### Quota-backed publication in version 1

An inference seller's supply is, in truth, not finite in the way a GPU is: a
model server can keep serving. But `unbacked-listing-publication` — the change
that makes a listing with no admission authority a legal shape — has zero of
sixty tasks complete, and it is scoped to the compute family.

So version 1 publishes exactly the way API credits does: the listing names a
`capacity_site_id` and a `resource_id` naming a quota resource in the
authority's ledger, the seller declares how many credits it is willing to sell,
the reconciler closes the listing at zero and reopens it when quota is added,
and issuance commits finite quota through an open-ended reservation. This works
today and needs nothing new.

**Revisit trigger:** when `unbacked-listing-publication` promotes the backing
discriminator, decide whether inference publishes unbacked listings. Its design
already says "a market family with no physical supply at all reaches it by the
same route," so the door is open. Backing is immutable per durable listing there,
so the transition would be close-and-republish, not a migration.

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

### Three identities, restated for this domain

The API-credits architecture companion already separates a marketplace principal
(who may negotiate and buy), a bearer credential (what admits a request), and
canonical ownership (who may top up a key). Inference keeps all three separate
and states the consequence normatively: the bearer credential is delivery of
what was bought, and its balance is not payment authorization for anything
else. A hosted route that adds a spending authority does so beside these, not
by merging them. This is what the Discord threads meant by "an API credential
is access — not the billing model."

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
copies the API-credits issuance client, fulfillment orchestration, and evidence
projection into `domains/inference/` with the digest label changed to
`inference`; `extract-access-issuance-kit` then moves what both copies share
into kit and deletes both copies.

Two reasons this order is right and the reverse is wrong. First, the boundary
is not knowable from one consumer — the reverse order guesses it and discovers
the guess when the second consumer arrives. Second, the extraction is delicate
in a specific way: the schema strings are inside the digests and the service
keeps a mirror copy of the digest function, so the extraction is a
parameterization that must leave every existing API-credits digest byte-
identical. That is far safer to do with a second working consumer and an
API-credits regression suite pinned first than as the opening move.

The cost is a transient second copy of roughly a thousand lines. Accepted;
the extraction change removes both copies, which is the Goal 4 rule that an
extracted concern leaves no domain-local implementation.

### Schema identity and filter specification

Schema identity is `inference`, version 1; filter-specification version 1. The
buyer plugin declares `inference` and therefore queries only registries
declaring it, which is what keeps inference discovery off the compute and
API-credits registries — the same load-bearing schema identity API credits
relies on.

Filters: `model_id`, `model_family`, `quantization`, `modality`, and
`supported_parameter` are exact `in` filters, fail-on-missing where the field is
required. `context_length_min` is a lower-bound range. `prompt_credits_max` and
`completion_credits_max` are upper-bound ranges over the rate card's integers.
The token, mechanism, asset, and funding projections are copied from the
API-credits specification. `offering_mode` is required and equals `inference`.

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
- **Integer granularity.** A seller cannot express less than one credit per
  million tokens on the rate card. Mitigated by the seller choosing a finer
  credit through the per-credit settlement rate.
- **Declared finite supply.** Quota-backed publication means a seller declares
  a sellable credit quantity that a model server does not physically enforce.
  This is API credits' posture today and inherits its limits; the unbacked
  revisit trigger is the way out.
- **Cross-asset comparison is client-side.** Accepted for the reasons
  `publish-indicative-listing-rates` records; that change owns the primitives
  for anything better.
- **Model identity.** `model_id` needs a naming authority (see open questions).
  A wrong choice is an additive filter alias, not a migration.

## Open questions

Each carries its revisit trigger. None is prescribed by a task in this change;
where a task touches one it is an explicit decision gate.

1. **Model identity naming authority.** Is `model_id` a Hugging Face repository
   identifier, a registry-curated canonical name, or seller-asserted with a
   family alias? Affects the `model_id` filter's usefulness across sellers.
   Gate: task 7.1 in `tasks.md`.
2. **`asking_rate` per million tokens.** Trigger:
   `publish-indicative-listing-rates` promotes the exact-decimal value type and
   filter co-requirements.
3. **Unbacked inference listings.** Trigger: `unbacked-listing-publication`
   promotes the backing discriminator and its scope is widened beyond the
   compute family.
4. **Whether the inference authority is the same kit-composed service binary as
   API credits deployed twice, or a distinct distribution.** Owned by
   `extract-access-issuance-kit`; irrelevant to this change's vocabulary.
5. **Pre-flight token estimation source** (vLLM `/tokenize` versus a local
   tokenizer). Owned by `meter-inference-usage`.

## Migration Plan

Additive. No existing wire shape, database, deployment, or distribution
changes. Rollback is deleting the new wheel and the registry image's two `COPY`
lines; no deployed registry selects the new specification until an operator sets
`REGISTRY_FILTER_SPEC_PATH` to it.
