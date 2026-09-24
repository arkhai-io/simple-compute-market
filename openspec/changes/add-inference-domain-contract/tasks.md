# Implementation Tasks

Sections are ordered by real dependency and sized to land in roughly a day each.
Sections 1–4 are pure vocabulary and tests with no runtime, deployment, or
packaging effect; Section 5 touches the registry image; Section 6 packages.
Nothing here starts a service or changes API credits.

**Decision gate.** Task 7.1's question — the `model_id` naming authority — was
decided on 2026-09-21 and is recorded in `design.md`'s decisions ("Model
identity is domain-canonical"). The task remains as the record of the gate; no
open gate remains in this change.

## 1. Domain identity and listing vocabulary

- [ ] 1.1 Confirm by inspection, before writing anything, that `design.md`'s
      "Context" table still holds on the target branch: no `inference` identity,
      schema, or filter specification exists; `consume` still takes a variable
      `amount`; the digest strings in `credits_client.py` and `keys_model.py`
      are still literal; `RateValue.per` is still a free string. Record drift in
      `design.md` rather than working around it.
- [ ] 1.2 Create `domains/inference/` with `__init__.py`, `pyproject.toml`
      (`arkhai-inference-domain`, hatchling, `force-include` of every module as
      the API-credits domain wheel does), and a `tests/` root. Depend on
      `arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-policy`, `pydantic`.
- [ ] 1.3 `domains/inference/listings/models.py`: `INFERENCE_KIND =
      "inference.v1"`, `INFERENCE_OFFERING_MODE = "inference"`, and the
      `InferenceModelCard` model (`listing_resource` payload) with `model_id`
      (validated against the domain's canonical pattern: lowercase
      `<org>/<name>`, no alias segment), `artifact_ref` (non-empty,
      scheme-prefixed source reference), `artifact_digest` (optional,
      `sha256:` hex), `display_name` (optional),
      `served_model_name`, `model_family`, `context_length` (positive int),
      `max_completion_tokens` (optional positive int), `quantization`,
      `architecture` (`modality`, `tokenizer`, `instruct_type`),
      `supported_parameters` (list of non-empty strings), `endpoint` (`base_url`,
      `openapi_url`, `api_style` literal `openai.v1`), `rate_card`
      (Section 2's model), `capacity_site_id`, `resource_id`, and
      `offering_mode` pinned to `inference`. `extra="forbid"`. Include the
      `coerce_resource_dict` and `resource_is_inference` helpers on the
      API-credits pattern.
- [ ] 1.4 `domains/inference/schema.py`: `InferenceListing` (kind,
      `listing_resource`, `accepted_escrows`, `settlement_options`, `demands`)
      with the same before-validator that normalizes a wheel-boundary model back
      to its wire form, duplicate-option-id rejection, and the required-field
      rejection the spec's "One listing is one served model" scenario names.
- [ ] 1.5 Focused tests (`tests/test_listing_models.py`): a complete card
      validates; each comparison field missing is rejected with the field named;
      `offering_mode` other than `inference` is rejected; `api_style` other than
      `openai.v1` is rejected; a listing round-trips through JSON text as the
      storefront's SQLite path stores it; a `model_id` with uppercase, an alias
      segment, or an encoded quantization is rejected with the format rule
      named; two cards sharing one `model_id` with different `artifact_ref` and
      rate cards both validate independently.

## 2. Rate card and pricing arithmetic

- [ ] 2.1 `domains/inference/listings/models.py`: `InferenceRateCard` with
      `prompt_credits_per_million`, `completion_credits_per_million`
      (non-negative int, required), `request_credits` (non-negative int, default
      0), `cached_prompt_credits_per_million` and `image_credits_per_unit`
      (optional non-negative int). Strict integer validation: `bool`, `float`,
      and numeric strings are rejected, matching `checked_credit_total`'s
      posture in the API-credits pricing module.
- [ ] 2.2 `domains/inference/listings/pricing.py`: `selected_unit_price` and
      `extract_unit_price_from_order` accepting `per: credit` only, computing
      `quantity × rate` with the uint256 overflow guard;
      `determine_strategy_from_order` returning `maximize` for inference
      listings. Copied from the API-credits module and narrowed, not imported.
- [ ] 2.3 Focused tests (`tests/test_pricing.py`): per-credit scaling; `per:
      hour` and `per: token` rejected; fractional and overflow rejected;
      hidden-reserve fallback to a configured minimum; the rate card has no
      effect on the purchase price (spec: "Purchase is priced per credit").

## 3. Provision intent, negotiation carriers, and codecs

- [ ] 3.1 `domains/inference/negotiation/terms.py`: `InferenceProvisionTerms`
      (`kind: inference.v1`, `version: 1`, payload `{quantity ≥ 1, key: {mode,
      key_id?}}`) and `make_inference_provision_terms`, copied from the
      API-credits module with the kind changed. State in the module docstring
      that the shape is shared by design and that kit ownership is decided by
      `extract-access-issuance-kit`.
- [ ] 3.2 `domains/inference/schema.py`: `InferenceMessage`, `InferenceTerms`,
      `InferenceMaterialization` (adds the pinned `rate_card`), `InferenceReceipt`,
      `InferenceResult`, each `extra="forbid"`, each carrying `kind:
      inference.v1`, with the same joint-presence rule for settlement selection
      and canonical principals API credits enforces.
- [ ] 3.3 `domains/inference/domain_runtime.py`: `INFERENCE_MARKET_DOMAIN =
      MarketDomainContract(identity=DomainIdentity("inference.v1"),
      contract_version=MARKET_DOMAIN_CONTRACT_VERSION, codecs=...)` and
      `market_domain()`.
- [ ] 3.4 Conformance: `tests/test_domain_conformance.py` runs
      `assert_domain_conformance` with one valid and one invalid example per
      codec, including a materialization whose `rate_card` is absent (rejected)
      and one whose card is fractional (rejected).
- [ ] 3.5 Focused tests for provision intent: quantity below one, existing key
      without `key_id`, wrong kind, wrong version.

## 4. Usage record, charge derivation, and evidence

- [ ] 4.1 `domains/inference/usage/models.py`: `UsageOutcome` literal
      (`completed`, `cancelled`, `failed`), `InferenceUsageRecord` (`model_id`,
      `key_id`, `request_id`, `prompt_tokens`, `completion_tokens`,
      `cached_prompt_tokens`, `image_units`, `outcome`; non-negative ints;
      `extra="forbid"`), and `derive_charge(record, rate_card) -> int`
      implementing the ceiling formula from `design.md` with zero for `failed`.
      Integer arithmetic only: compute the sum as a rational over `10**6` and
      take the ceiling without floats.
- [ ] 4.2 Focused tests (`tests/test_usage.py`): the two spec scenarios
      (cancelled after 400 tokens → 1 credit; failed → 0); exact-million
      boundaries; all-zero record with a floor; cached tokens priced separately
      when a cached rate is present and ignored when absent; a property-style
      test that `derive_charge` never returns a float and never underflows.
- [ ] 4.3 `domains/inference/usage/evidence.py`: `InferenceUsageEvidenceBodyV1`
      (protocol `arkhai.inference.usage-evidence.v1`, schema version `1`,
      `domain: inference`, the record, the pinned card, the derived charge,
      `grant_id`, `fulfillment_id`, `issuer`) with canonical-JSON digest and
      signing/verification helpers on the pattern of the API-credits issuance
      evidence module. Copied and renamed, not imported.
- [ ] 4.4 Canary test (`tests/test_usage_evidence.py`): construct evidence with
      a sentinel bearer secret, prompt text, and completion text available to
      the producing code and assert none appears in the canonical bytes;
      verification rejects a tampered charge and an untrusted signer.

## 5. Registry filter specification

- [ ] 5.1 `domains/inference/registry/filter-spec.yaml`, version 1, `schema: {id:
      inference, version: 1}`. `listing_shape` requires `listing_id`,
      `listing_resource`, `storefront_url`, and inside `listing_resource`
      requires `model_id` (with the canonical `pattern`), `artifact_ref`,
      `served_model_name`, `context_length`,
      `quantization`, `architecture.modality`, `supported_parameters`,
      `endpoint.base_url`, `rate_card.prompt_credits_per_million`,
      `rate_card.completion_credits_per_million`, and `offering_mode`
      (`const: inference`). Settlement-option and accepted-escrow shapes copied
      from the API-credits specification. State in the `model_id` field
      description that a registry operator may narrow it to an `enum` by
      policy and that the registry never mints or resolves identifiers.
- [ ] 5.2 Filters: `model_id`, `model_family`, `quantization`, `modality`
      (`$.listing_resource.architecture.modality`), and `supported_parameter`
      (`$.listing_resource.supported_parameters[*]`) as `in`, fail-on-missing
      for required paths; `context_length_min` as `range` lower bound;
      `prompt_credits_max` and `completion_credits_max` as `range` upper bounds
      over the rate card; `offering_mode` as `in`, fail-on-missing; the
      `token`, `token_exclude`, `settlement_mechanism`, `settlement_asset`,
      `funding_profile`, and `funding_interaction` projections verbatim from the
      API-credits specification.
- [ ] 5.3 `core/registry/tests/unit/test_filter_spec.py`: add
      `test_repo_inference_spec_loads` beside `test_repo_api_credits_spec_loads`,
      asserting schema identity `inference` version 1, that every filter path
      resolves against a sample listing built from Section 1's model, and that
      a `model_id` violating the canonical pattern is refused at validation.
- [ ] 5.4 `core/registry/Dockerfile`: `COPY domains/inference/registry/filter-spec.yaml
      ./filter-spec-inference.yaml` in the builder stage and the matching
      `COPY --from=builder` in the runtime stage, beside the API-credits lines.
- [ ] 5.5 **Integration.** Publish a valid inference listing to a registry
      started with `REGISTRY_FILTER_SPEC_PATH=/app/filter-spec-inference.yaml`
      through the registry client; query each filter; confirm a listing under
      `offer_resource` is rejected and a listing missing `rate_card` is
      rejected. Use the existing registry integration fixtures.

## 6. Distribution and aggregate targets

- [ ] 6.1 `domains/Makefile`: `dist-inference-domain` (wheel into `$(DIST_DIR)`
      with the `py3-none-any` assertion the other domain targets carry) and
      `test-inference`; add both to the `dist` and `test` aggregates.
- [ ] 6.2 Root `Makefile`: `test-inference` delegating to `domains`, added to
      the root `test` aggregate so the aggregate contract stays complete
      coverage.
- [ ] 6.3 `domains/inference/tests/test_distribution.py` and
      `test_distribution_install.py` on the API-credits pattern: the wheel
      carries every module; no `[tool.uv.sources]` editable override anywhere
      under `domains/inference/`; the contract imports from the built wheel in a
      clean environment and `market_domain().identity == "inference.v1"`.
- [ ] 6.4 Run `make dist-domains` and `make test-inference` from a clean `.dist`
      and record the result.

## 7. Decision gates

- [x] 7.1 **Decision gate — `model_id` naming authority.** Decided 2026-09-21
      and recorded in `design.md`, "Model identity is domain-canonical": the
      domain owns a canonical lowercase `<org>/<name>` format identifying the
      logical model at one version; `artifact_ref` and an optional
      `artifact_digest` carry the exact source; quantization, runtime, and
      context limits stay explicit fields; aliases are not in the protocol; a
      registry validates the format and may narrow the vocabulary by operator
      policy but never mints, resolves, or aliases identifiers; `deployment_id`
      was rejected as a second name for `listing_id`. The item is out of "Open
      questions". Sections 1.3, 1.5, 5.1, and 5.3 carry the resulting work. The
      field's type is unchanged.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Read the copied modules directly for references to the API-credits
      change history their docstrings may have carried across.
- [ ] 8.2 **Import placement.** Review imports this change adds; move
      function-level imports to module level where no genuine circular import or
      documented lazy-load reason applies, verified against the suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules; confirm the domain-versus-extension
      rationale and the copy-first rule landed in
      the `inference` capability's `architecture.md` and the normative statements in
      the `inference` capability's `spec.md`, not only here.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations; keep rejected
      alternatives in `design.md`.
- [ ] 8.5 **Roadmap currency.** Update Goal 8's current-state prose in
      `docs/development/ROADMAP.md` (the vocabulary now exists) and remove this
      change's row from its gap table; name the update in the promotion record.
- [ ] 8.6 **Campaign index currency.** Update this change's row and the
      campaign graph in `openspec/changes/README.md`; confirm every campaign
      link resolves to an existing directory.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=add-inference-domain-contract` and resolve
      every match.
- [ ] 8.8 **End-to-end pipeline.** This change adds no service and no scenario,
      so the existing pipeline is the regression check: run
      `make -C e2e-tests test-e2e` on the branch and record that the compute
      and API-credits scenarios are unaffected. If the pipeline cannot run for a
      reason unrelated to this change, record the blocker and the owning change.
- [ ] 8.9 **Promotion.** Complete the design-promotion record below, last.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A market domain is where a credit's interpretation is pinned; inference fixes it per model, API credits leaves it to the seller | the `inference` capability's `architecture.md` — "Market shape"; one sentence in `openspec/specs/api-credits/architecture.md` — "Market shape" |
| One listing is one served model | the `inference` capability's `spec.md` — "One listing is one served model" |
| Purchase is priced per credit; consumption is priced per token through a rate card; the layers are independent | the `inference` capability's `spec.md` — "Purchase is priced per credit", "Rate card is integer-valued and pinned at issuance" |
| The rate card is pinned at issuance | the `inference` capability's `spec.md` — "Rate card is integer-valued and pinned at issuance" |
| Charge derivation is a pure function of record and card | the `inference` capability's `spec.md` — "Usage record and deterministic charge derivation" |
| Usage evidence is secret-free | the `inference` capability's `spec.md` — "Usage evidence is secret-free" |
| Three identities; the bearer credential is delivery | the `inference` capability's `spec.md` — "Bearer credential is delivery, not identity or payment authority" |
| The authority is the singular synchronous admission decision; rating systems are downstream | the `inference` capability's `spec.md` — "Admission authority is synchronous and singular"; rationale in the `inference` capability's `architecture.md` |
| Discovery under the `inference` schema identity | the `inference` capability's `spec.md` — "Discovery under the inference schema identity" |
| Quota-backed publication in version 1 as the backed value of the declared backing property, quota being a sales cap | the `inference` capability's `spec.md` — "Quota-backed publication"; trigger in the `inference` capability's `architecture.md` — "Current limits" |
| No derived discovery price; comparability is on integer rates and asset until the exact-decimal primitives land | the `inference` capability's `architecture.md` — "Current limits" |
| Copy first, extract after two consumers | the `inference` capability's `architecture.md` — "Implementation composition"; `docs/development/ROADMAP.md` Goal 8 current state |
| `inference` joins the enumerated offering modes; **rate card** and **usage record** join the Terms table | `docs/development/ARCHITECTURE.md` — "One name per concept", "Terms" |
| Model identity is domain-canonical: a logical-model identifier in a domain-defined format, the exact source in `artifact_ref`, quantization as a field, no protocol aliases, and a registry that validates but never mints | the `inference` capability's `spec.md` — "One listing is one served model"; rationale in its `architecture.md` |
