## Why

`docs/development/ROADMAP.md`'s Goal 4 names "an inference-token domain" as the
kind of market the kit layering exists to make cheap: "codecs, a contract, and
configuration rather than a fork of the VM storefront." Nothing of it exists.
On `dev` at `c8318b6b` (verified 2026-09-21) there is no `inference` domain
identity, registry schema identity, filter specification, offering mode, or usage
vocabulary anywhere in the repository, and no active or archived change owns one.

The nearest thing is API credits, which sells prepaid finite units for a *named
service*. Its listing carries `service_name`, `base_url`, and a quota resource;
its gate consumes one configured fixed amount per admitted request; and its own
architecture companion records the limit plainly: "route-specific or
variable-cost metering is not established." The vLLM cookbook
(`docs/cookbooks/vllm-apicredits-seller.md`) already sells a model server behind
that domain, and it demonstrates the gap rather than closing it. A listing that
says `service_name: vllm-chat` cannot be compared with another seller's, because
nothing on it says which model, at what context length, in what quantization, or
at what price per token. A buyer of inference compares exactly those things, and
pays for measured input and output rather than for a request.

Two framings were rejected before this one.

**Extending API credits.** API credits is deliberately generic — it is the right
shape for any prepaid API, and it has consumers beyond inference. Pinning a
token-denominated interpretation of "one credit" onto it would break the general
case for every non-model service. What a market domain *is* in this repository
is the place an interpretation gets pinned: API credits leaves the meaning of a
credit to the seller; inference fixes it, per model, so listings are comparable.
That difference is a domain, not a field.

**Extracting shared machinery first.** An earlier plan opened with an
extraction from API credits so a new domain could compose it. The extraction
boundary cannot be known from one consumer, and the pieces most tempting to
extract — balances, quantities, consumption rules — are precisely the ones an
inference market interprets differently. This change therefore defines
vocabulary only. The follow-on changes in this campaign compose a stack by
copying, prove one deal, and extract only what two working consumers show to be
shared.

## What Changes

- Introduce the `inference.v1` market-domain identity, the `inference` registry
  schema identity (version 1), and the `inference` offering mode. The offering
  mode joins the enumerated values in `ARCHITECTURE.md`'s one-name table at
  promotion.
- Define the published listing shape. One listing is one served model at one
  seller. `listing_resource` is a **model card**: a canonical `model_id` in a
  domain-defined format naming the logical model at one version, an
  `artifact_ref` naming the exact weights served (optionally with an
  `artifact_digest`), the seller's `served_model_name`, `model_family`, `context_length`,
  `max_completion_tokens`, `quantization`, an `architecture` block (modality,
  tokenizer, instruct type), `supported_parameters`, an `endpoint` block
  (`base_url`, `openapi_url`, `api_style: "openai.v1"`), a **rate card**, and
  the quota-backing fields API credits already uses (`capacity_site_id`,
  `resource_id`). Every field a buyer compares on is required; `display_name`
  is an optional mutable label. The domain owns the identifier format; a
  registry validates it and may narrow the vocabulary by operator policy but
  never mints or resolves identifiers.
- Define the **rate card** as exact integers: credits per million prompt
  tokens, credits per million completion tokens, an optional flat credits-per-
  request floor, and optional cached-prompt and image rates. Pricing in
  `settlement_options[*].rates` stays per **credit**; the rate card says what a
  credit buys. The card in force at issuance is pinned to the grant.
- Define round-zero provision intent `inference.v1`: a positive integer credit
  `quantity` and a key disposition of `new` or `existing` with `key_id`. This is
  the API-credits purchase shape under a new kind, because the purchase layer is
  identical by design; it is copied, not imported.
- Define the six market-domain codecs — listing, message, terms,
  materialization, receipt, result — and register the domain's conformance
  examples with the shared `assert_domain_conformance` harness.
- Define the **usage record** and its deterministic charge derivation: prompt,
  completion, and cached-prompt token counts; the model and key the request ran
  under; a request identity; an outcome of `completed`, `cancelled`, or
  `failed`; and the exact integer charge a record and a pinned rate card produce
  together. Define the secret-free **usage evidence** body. This change defines
  the shapes and the arithmetic; `meter-inference-usage` enforces them on the
  request path.
- Write the `inference` registry filter specification: exact filters on
  `model_id`, `model_family`, `quantization`, modality, and
  `supported_parameters`; range filters on `context_length` and on the rate
  card's integer credit rates; and the settlement projections the API-credits
  specification already carries. Add the repository test that loads it and the
  registry image `COPY` that ships it, so any deployment can select it through
  `REGISTRY_FILTER_SPEC_PATH`.
- Package the vocabulary as the `arkhai-inference-domain` wheel with the
  structural and installation tests the API-credits domain wheel already has.

## Capabilities

### New Capabilities

- `inference`: listing, rate card, provision intent, negotiated terms, usage
  record and charge derivation, usage evidence, and the identity separation
  between marketplace principal, bearer credential, and spending authority for
  metered model inference.

### Modified Capabilities

- None normatively. `registry-discovery`'s schema-driven validation and opaque
  payload storage already admit any filter specification; this change adds a
  third deployed instance, not a rule. `deployment-state`'s registry image
  contract gains one carried file, on the pattern the API-credits specification
  already follows.

## Non-Goals

- No storefront or buyer executables, gateway, authority service deployment,
  Compose stack, development identities, or end-to-end scenario. Those are
  `compose-inference-domain-stack`.
- No extraction from API credits and no change to any API-credits behavior,
  wire shape, digest, database row, or distribution. That is
  `extract-access-issuance-kit`, and it waits until two consumers exist.
- No admission holds, no post-response settlement, no streaming usage capture,
  no cancellation handling. That is `meter-inference-usage`.
- No hosted fiat (`fiat.stripe.v1`) option for inference listings, and no
  Stripe, Metronome, Formance, or WorkOS integration of any kind. The hosted
  route is owned outside this repository's workstream.
- No Arkhai-hosted inference registry deployment, no Helm alias, no webapp
  integration.
- No unbacked inference listing and no `asking_rate` field. Both are revisited
  on the triggers recorded in `design.md`.
- No embeddings, image, audio, or batch endpoints. Version 1 names chat
  completions and completions.
- No seller packaging or installer.

## Impact

- **New code.** `domains/inference/{__init__,domain_runtime,schema}.py`,
  `domains/inference/listings/{models,pricing}.py`,
  `domains/inference/negotiation/terms.py`,
  `domains/inference/usage/{models,evidence}.py`,
  `domains/inference/registry/filter-spec.yaml`,
  `domains/inference/pyproject.toml`, and `domains/inference/tests/`.
- **Touched code.** `core/registry/Dockerfile` (one `COPY` per stage),
  `core/registry/tests/unit/test_filter_spec.py` (a load test beside
  `test_repo_api_credits_spec_loads`), `domains/Makefile`
  (`dist-inference-domain`, `test-inference`), and the root `Makefile`'s
  aggregate `dist-domains`/`test` membership.
- **Wire.** A new schema and a new domain kind. No existing wire shape changes.
- **Database.** None.
- **Deployment.** The registry image carries one more filter specification;
  nothing selects it until a deployment sets the path.
- **Packaging.** One new wheel, `arkhai-inference-domain`, depending on
  `arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-policy`, and `pydantic`.
- **Contributor workflow.** None.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the one-name table's `offering_mode`
      values gain `inference`; the Terms table gains **rate card** and **usage
      record**; the runtime service map notes a third registry schema once the
      stack change deploys one (that promotion belongs to the stack change, not
      this one).
- [ ] Existing subsystem specification — none.
- [x] New subsystem specification — a new `inference` capability with a
      normative `spec.md` and an `architecture.md` companion, created at
      promotion.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- A market domain is where the interpretation of a prepaid credit is pinned;
  API credits leaves it to the seller, inference fixes it per model —
  the `inference` capability's `architecture.md` and, as one sentence, the
  API-credits architecture companion's "Market shape".
- Purchase is priced per credit and consumption is priced per token through a
  rate card pinned at issuance; the two layers are independent —
  the `inference` capability's `spec.md`.
- One listing is one served model, so the registry compares sellers per model —
  the `inference` capability's `spec.md`.
- Marketplace principal, bearer credential, and spending authority are three
  identities; the bearer credential is delivery, never payment authorization —
  the `inference` capability's `spec.md`, restating the API-credits companion's
  "Commercial and usage identity" for the new domain.
- Model identity is domain-canonical: `model_id` names the logical model,
  `artifact_ref` the exact source, quantization stays a field, and a registry
  validates the format but never mints or resolves identifiers — the
  `inference` capability's `spec.md` and `architecture.md`.
- Charge derivation is a pure function of a usage record and a rate card —
  the `inference` capability's `spec.md`.
- Why copy-first and extract-after-two-consumers is the sequencing rule for this
  campaign — the `inference` capability's `architecture.md`, and
  `docs/development/ROADMAP.md`'s Goal 8 current state.

## Dependencies and Related Changes

- **No blocking dependency.** The vocabulary this change is written in —
  `listing_resource`, `offering_mode`, `listing_cardinality_mode` — was settled
  by [`settle-listing-vocabulary`](../archive/2026-09-15-settle-listing-vocabulary/),
  archived 2026-09-15, so nothing here waits on a rename.
- [`compose-inference-domain-stack`](../compose-inference-domain-stack/),
  [`extract-access-issuance-kit`](../extract-access-issuance-kit/),
  [`meter-inference-usage`](../meter-inference-usage/),
  [`package-inference-seller`](../package-inference-seller/), and
  [`qualify-inference-market`](../qualify-inference-market/) follow this change
  in that dependency order; each is opened in design phase and planned when its
  predecessor is accepted.
- [`unbacked-listing-publication`](../unbacked-listing-publication/) — version-1
  inference listings are quota-backed on the API-credits path that exists today.
  When backing becomes an explicit listing property, an inference listing with
  no finite supply behind it is the natural next shape; `design.md` records the
  trigger.
- [`publish-indicative-listing-rates`](../publish-indicative-listing-rates/) —
  owns the exact-decimal filter value type and declarative filter
  co-requirements the generic registry lacks. Inference does not duplicate that
  work; it filters on integer credit rates and the settlement asset today and
  revisits a monetary `asking_rate` when those primitives land.
- [`add-future-domain-shape-validation`](../add-future-domain-shape-validation/)
  — admits a bounded fixture for an inference domain "the product does not
  have" and forbids that fixture from carrying domain design. Once this change
  lands the fixture has a product referent, and that change's own rule requires
  it to be replaced by a real adapter there rather than kept as speculation.
- [`sign-multi-language-credits-middleware`](../sign-multi-language-credits-middleware/)
  — the bearer gate's outbound signing that the stack and metering changes
  consume. Not a dependency of the vocabulary.
- `docs/development/ROADMAP.md` Goal 4 names an inference-token domain as a
  beneficiary of kit composition; this campaign is that domain and also serves
  Goal 4.
