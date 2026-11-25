# Implementation Tasks

Sections are ordered by real dependency and sized to land in roughly a day each.
Sections 1–4 are pure vocabulary and tests with no runtime, deployment, or
packaging effect; Section 5 touches the registry image; Section 6 packages.
Nothing here starts a service. The one change to API credits is the family
purchase shape's tightened validation (3.6).

**Decision gates.** Both gates this change carried are closed and recorded in
`design.md`: 7.1, model identity (decided 2026-09-21, revised 2026-09-24 to a
seller-asserted identifier with a SHOULD derivation rule); and 7.2, credit
denomination (decided 2026-09-24: one credit is one base unit of the settlement
asset). The tasks remain as the record; no open gate remains in this change.

## 1. Domain identity and listing vocabulary

- [x] 1.1 Confirm by inspection, before writing anything, that `design.md`'s
      "Context" table still holds on the target branch: no `inference` identity,
      schema, or filter specification exists; `consume` still takes a variable
      `amount`; the digest strings in `credits_client.py` and `keys_model.py`
      are still literal; `RateValue.per` is still a free string. Record drift in
      `design.md` rather than working around it.
- [x] 1.2 Create `domains/inference/` with `__init__.py`, `pyproject.toml`
      (`arkhai-inference-domain`, hatchling, `packages = ["src/arkhai_inference"]`
      as every project declares), and a `tests/` root. Depend on
      `arkhai-core`, `arkhai-kit-identity`, `pydantic`.
- [x] 1.3 `domains/inference/src/arkhai_inference/listings/models.py`: `INFERENCE_KIND =
      "inference.v1"`, `INFERENCE_OFFERING_MODE = "inference"`, and the
      `InferenceModelCard` model (`listing_resource` payload) with `model_id`
      (non-empty; characters restricted to what a filter path can carry, no
      format beyond that), `artifact_ref` (non-empty, any scheme including
      private ones), `artifact_digest` (optional, `sha256:` hex),
      `display_name` (optional), `model_owner` (optional marketplace
      principal), `provenance` (required, `self-hosted` | `resold`),
      `attestation` (optional `{kind, schema_version, payload}` envelope, opaque),
      `served_model_name`, `model_family`, `context_length` (positive int),
      `max_completion_tokens` (optional positive int),
      `architecture` (`modality`, `tokenizer`, `instruct_type`),
      `supported_parameters` (list of non-empty strings), `quantization` as an
      enumeration (`none`, `fp16`, `bf16`, `fp8`, `int8`, `int4`, `awq`,
      `gptq`), `endpoint` (`base_url`,
      `openapi_url`, `api_style` literal `openai.v1`), `rate_card`
      (Section 2's model), `capacity_site_id`, `resource_id`, and
      `offering_mode` pinned to `inference`. `extra="forbid"`. Include the
      `coerce_resource_dict` and `resource_is_inference` helpers on the
      API-credits pattern.
- [x] 1.3a `domains/inference/src/arkhai_inference/listings/identity.py`: `derive_model_id(...)`,
      a pure function implementing the derivation rule — public upstream owner
      and repository lowercased with revision, branch, and quantization
      suffixes stripped; the owner's namespace for private weights; the
      fine-tuner's for a fine-tune — plus focused tests that two independent
      inputs for the same weights derive the same identifier and that the
      three suffix kinds are stripped. Sellers and the seller path call it; the
      card does not require it.
- [x] 1.4 `domains/inference/src/arkhai_inference/schema.py`: `InferenceListing` (kind,
      `listing_resource`, `accepted_escrows`, `settlement_options`, `demands`)
      with the same before-validator that normalizes a wheel-boundary model back
      to its wire form, duplicate-option-id rejection, and the required-field
      rejection the spec's "One listing is one served model" scenario names.
- [x] 1.5 Focused tests (`tests/test_listing_models.py`): a complete card
      validates; each comparison field missing is rejected with the field named;
      `offering_mode` other than `inference` is rejected; `api_style` other than
      `openai.v1` is rejected; a listing round-trips through JSON text as the
      storefront's SQLite path stores it; a card without `provenance` or with a
      value outside the enumeration is rejected; a card with a `quantization`
      outside the enumeration is rejected; two cards sharing one `model_id`
      with different `artifact_ref`, `quantization`, and rate cards both
      validate independently; a card with and without the `attestation`
      envelope validate identically; a card naming a `model_owner` validates.

Done 2026-09-27: premises re-verified on `dev` at `29b84d82` with no drift;
`domains/inference/src/arkhai_inference/listings/{models,identity}.py`, `schema.py`; 56 focused
tests. `model_id` admits uppercase by design (seller-asserted); `resource_id`
is optional on the card as on the API-credits resource, the publication path
sets it. The rate card model landed here because the card requires it.

Round 1 (review 01-implementation-external, 2026-10-22). F3: the rate card
names its `asset`, and the listing codec refuses a settlement option or escrow
token naming another, so one card is read in one asset. F2: the card's amounts
are `Uint256Amount` — integers in memory, decimal-digit strings on the wire —
because canonical JSON carries no integer above 2⁵³ − 1 and both the published
listing and the evidence pinning the card are signed canonically. F1: the codec
runs the unit-rate check over every option and escrow; before, only the pricing
path did, and a listing at two per credit or one per hour validated. Tests:
eight listing cases for the refused and admitted shapes, a 7 × 10²¹ card
round-tripping through canonical JSON.

## 2. Rate card and pricing arithmetic

- [x] 2.1 `domains/inference/src/arkhai_inference/listings/models.py`: `InferenceRateCard` with
      `prompt_credits_per_million`, `completion_credits_per_million`
      (non-negative int, required), `request_credits` (non-negative int, default
      0), `cached_prompt_credits_per_million` and `image_credits_per_unit`
      (optional non-negative int) — all denominated in base units of the
      listing's settlement asset. Strict integer validation: `bool`, `float`,
      and numeric strings are rejected, matching `checked_credit_total`'s
      posture in the API-credits pricing module.
- [x] 2.2 `domains/inference/src/arkhai_inference/listings/pricing.py`: `selected_unit_price` and
      `extract_unit_price_from_order` accepting `per: credit` with a value of
      exactly `1` and refusing any other value or unit; the reference payment
      equals `quantity`, with the uint256 overflow guard;
      `determine_strategy_from_order` returning `maximize` for inference
      listings. Copied from the API-credits module and narrowed, not imported.
- [x] 2.3 Focused tests (`tests/test_pricing.py`): a unit rate scales to
      `quantity`; a per-credit rate other than one is rejected; `per: hour` and
      `per: token` rejected; overflow rejected; a listing with no advertised rate
      prices at one and a configured minimum other than one is refused; the rate card has no effect on the purchase price
      (spec: "Purchase is priced in settlement-asset base units").

Done 2026-09-27: `listings/pricing.py`; 23 tests. The hidden-reserve fallback
has no meaning under a fixed unit rate, so a configured minimum is admitted only
when it is one; task 2.3's text was amended to match.

Round 1 (F1, F3): `validate_listing_rates(options, escrows, asset=)` is the one
check the codec and `extract_unit_price_from_order` share. Task 2.1's "numeric
strings are rejected" now holds for the purchase arithmetic only; on the card a
decimal-digit string is the wire form (F2).

## 3. Provision intent, negotiation carriers, and codecs

- [x] 3.1 `domains/inference/src/arkhai_inference/negotiation/terms.py`: `InferenceProvisionTerms`
      (`kind: inference.v1`, `version: 1`, payload `{quantity ≥ 1, key: {mode,
      key_id?}}`) and `make_inference_provision_terms`, copied from the
      API-credits module with the kind changed. State in the module docstring
      that the shape is shared by design and that family ownership is decided by
      `compose-api-family-kit`.
- [x] 3.2 `domains/inference/src/arkhai_inference/schema.py`: `InferenceMessage`, `InferenceTerms`,
      `InferenceMaterialization` (adds the pinned `rate_card`), `InferenceReceipt`,
      `InferenceResult`, each `extra="forbid"`, each carrying `kind:
      inference.v1`, with the same joint-presence rule for settlement selection
      and canonical principals API credits enforces.
- [x] 3.3 `domains/inference/src/arkhai_inference/domain_runtime.py`: `INFERENCE_MARKET_DOMAIN =
      MarketDomainContract(identity=DomainIdentity("inference.v1"),
      contract_version=MARKET_DOMAIN_CONTRACT_VERSION, codecs=...)` and
      `market_domain()`.
- [x] 3.4 Conformance: `tests/test_domain_conformance.py` runs
      `assert_domain_conformance` with one valid and one invalid example per
      codec, including a materialization whose `rate_card` is absent (rejected)
      and one whose card is fractional (rejected).
- [x] 3.5 Focused tests for provision intent: quantity below one, existing key
      without `key_id`, wrong kind, wrong version.

Done 2026-09-27: `negotiation/terms.py`, the five carriers in `schema.py`,
`domain_runtime.py`; the contract passes `assert_domain_conformance` with an
empty capability set; 24 tests including eleven invalid-input codec cases.

Round 1 (F5): `quantity` is a strict integer; a new key names no `key_id` and
an existing key names a non-blank one; the maker no longer truncates through
`int()`. The API-credits original is left as it is by the owner's direction:
`compose-api-family-kit` extracts the shape into the shared kit and corrects
API credits there, replacing this copy with an import.

- [x] 3.6 Bind the family's purchase shape. `compose-api-family-kit` extracted
      the shape into `kit/api/src/arkhai_api/purchase.py` without the
      correction, so this change makes it there: a strict integer quantity, a
      new key naming no `key_id`, an existing key naming a non-blank one, and a
      maker that does not truncate; `kit/api/tests/unit/test_purchase.py`
      carries the refusals moved from the inference tests.
      `negotiation/terms.py` becomes `provision_terms_model("inference.v1")`,
      `domains/inference/pyproject.toml` declares `arkhai-api`, and the
      inference row in `docs/development/ARCHITECTURE.toml` declares
      `family = "api"`.

## 4. Usage record, charge derivation, and evidence

- [x] 4.1 `domains/inference/src/arkhai_inference/usage/models.py`: `UsageOutcome` literal
      (`completed`, `cancelled`, `failed`), `InferenceUsageRecord` (`model_id`,
      `key_id`, `request_id`, `prompt_tokens`, `completion_tokens`,
      `cached_prompt_tokens`, `image_units`, `outcome`; non-negative ints;
      `extra="forbid"`), and `derive_charge(record, rate_card) -> int`
      implementing the ceiling formula from `design.md` with zero for `failed`.
      Integer arithmetic only: compute the sum as a rational over `10**6` and
      take the ceiling without floats.
- [x] 4.2 Focused tests (`tests/test_usage.py`): the two spec scenarios
      (cancelled after 400 tokens → 1 credit; failed → 0); exact-million
      boundaries; all-zero record with a floor; cached tokens priced separately
      when a cached rate is present and ignored when absent; a property-style
      test that `derive_charge` never returns a float and never underflows.
- [x] 4.3 `domains/inference/src/arkhai_inference/usage/evidence.py`: `InferenceUsageEvidenceBodyV1`
      (protocol `arkhai.inference.usage-evidence.v1`, schema version `1`,
      `domain: inference`, the record, the pinned card, the derived charge,
      `grant_id`, `fulfillment_id`, `issuer`, and an optional opaque
      `attestation` envelope that verification ignores) with canonical-JSON
      digest and signing/verification helpers on the pattern of the API-credits
      issuance evidence module. Copied and renamed, not imported.
- [x] 4.4 Canary test (`tests/test_usage_evidence.py`): construct evidence with
      a sentinel bearer secret, prompt text, and completion text available to
      the producing code and assert none appears in the canonical bytes;
      verification rejects a tampered charge and an untrusted signer.

Done 2026-09-27: `usage/{models,evidence}.py`; 35 tests including the
secret/prompt/completion canary. Verification binds the body to the expected
grant facts (grant, fulfillment, key, model, pinned card, issuer) as the
API-credits verifier binds issuance to its accepted obligation, and bounds age
when the consumer supplies a retention window. The request charge is added to the ceiling of
the token sum, as the requirement and `design.md` state; the spec scenario's
worked number was corrected from 1 to 2. Cached tokens with no cached rate
contribute nothing, as the formula states.

Round 1 (F2, F4): the evidence `charge` is `Uint256Amount`, so a body on an
18-decimal card signs; a test signs and decodes at 10²¹. Verification binds the
body to the expected `request_id` as well as the grant facts; grant and request
together name one usage record, and the delta states a consumer debits that
pair once — the hold-and-settle path that enforces it is `meter-inference-usage`'s.

## 5. Registry filter specification

- [x] 5.1 `domains/inference/registry/filter-spec.yaml`, version 1, `schema: {id:
      inference, version: 1}`. `listing_shape` requires `listing_id`,
      `listing_resource`, `storefront_url`, and inside `listing_resource`
      requires `model_id` (non-empty), `artifact_ref`, `provenance` (`enum`),
      `served_model_name`, `context_length`,
      `quantization`, `architecture.modality`, `supported_parameters`,
      `endpoint.base_url`, `rate_card.prompt_credits_per_million`,
      `rate_card.completion_credits_per_million`, and `offering_mode`
      (`const: inference`). Settlement-option and accepted-escrow shapes copied
      from the API-credits specification. `quantization` is an `enum`. The
      `attestation` envelope is admitted by shape and declared by no filter.
      State in the `model_id` field description that the domain's derivation
      rule is a SHOULD, that a registry operator may narrow the field to an
      `enum` or pattern by policy, and that the registry never mints or
      resolves identifiers.
- [x] 5.2 Filters: `model_id`, `model_family`, `quantization`, `modality`
      (`$.listing_resource.architecture.modality`), `supported_parameter`
      (`$.listing_resource.supported_parameters[*]`), and `provenance` as `in`,
      fail-on-missing for required paths; `context_length_min` as `range` lower
      bound; `prompt_credits_max` and `completion_credits_max` as `range` upper
      bounds over the rate card's base-unit integers, each declaring
      `requires: [settlement_asset]` so the registry refuses an unpaired
      bound; no filter over
      `attestation`; `offering_mode` as `in`, fail-on-missing; the
      `token`, `token_exclude`, `settlement_mechanism`, and `settlement_asset`
      projections verbatim from the API-credits specification.
- [x] 5.3 `core/registry/tests/unit/test_filter_spec.py`: add
      `test_repo_inference_spec_loads` beside `test_repo_api_credits_spec_loads`,
      asserting schema identity `inference` version 1, that every filter path
      resolves against a sample listing built from Section 1's model, that a
      listing without `provenance` is refused at validation, and that no filter
      declaration names the `attestation` path.
- [x] 5.4 `core/registry/Dockerfile`: `COPY domains/inference/registry/filter-spec.yaml
      ./filter-spec-inference.yaml` in the builder stage and the matching
      `COPY --from=builder` in the runtime stage, beside the API-credits lines.
- [x] 5.5 **Integration.** Publish a valid inference listing to a registry
      started with `REGISTRY_FILTER_SPEC_PATH=/app/filter-spec-inference.yaml`
      through the registry client; query every declared filter, the test
      refusing a declaration it does not query; confirm a listing missing
      `rate_card` fails the dry run. The retired `offer_resource` key's
      refusal is specification-independent and already proven in
      `core/registry/tests/integration/test_settled_envelope_across_specs.py`.
      Use the existing registry integration fixtures.

Done 2026-09-27: `registry/filter-spec.yaml`, two `COPY` lines, the unit load
test, and `core/registry/tests/integration/test_inference_spec.py` (one
query per declared filter, the test failing on a declaration it does not
query; the dry run refuses each malformed card naming the field). Registry
unit 105, integration 125. The image was built and carries all three specifications. Finding: the
registry does not enforce the listing shape at publish by design, so the spec's
"rejected at publication" sentence was reattributed to the storefront codec and
the dry run.

Round 1 (F2, F3): the served shape requires `rate_card.asset` and declares the
amounts as decimal-digit strings; the two rate bounds compare `decimal_text`
and co-require the new `rate_card_asset` filter, the card's own asset, as the
compute specification pairs `asking_rate_max` with `asking_rate_asset`.
`settlement_asset` stays as the projection over options. The integration test
queries the new filter, refuses a bound paired only with `settlement_asset`,
publishes a 7 × 10²¹ card through the signed client and bounds it exactly, and
fails the dry run on a numeric rate and on a card without its asset.

## 6. Distribution and aggregate targets

- [x] 6.1 `domains/Makefile`: `dist-inference-domain` (wheel into `$(DIST_DIR)`
      with the `py3-none-any` assertion the other domain targets carry) and
      `test-inference`; add both to the `dist` and `test` aggregates.
- [x] 6.2 Root `Makefile`: `test-inference` delegating to `domains`, added to
      the root `test` aggregate so the aggregate contract stays complete
      coverage.
- [x] 6.3 `domains/inference/tests/test_distribution.py` and
      `test_distribution_install.py` on the API-credits pattern: the wheel
      carries every module; no `[tool.uv.sources]` editable override anywhere
      under `domains/inference/`; the contract imports from the built wheel in a
      clean environment and `market_domain().identity == "inference.v1"`.
- [x] 6.4 Run `make dist-domains` and `make test-inference` from a clean `.dist`
      and record the result.
- [x] 6.5 `.github/workflows/tests.yml` runs the domain's suite: `test-inference`
      is a member of `test-domains`, which the workflow's matrix runs, needing
      no hosted artifact.
- [x] 6.6 `make check-packaging` passes with the new project's lock and
      `reinit` target.

Done 2026-09-27: `domains/inference/Makefile`, `dist-inference-domain` and
`test-inference` in the domain and root aggregates, the wheel fixture with
structural and install tests; `make test-inference` from the root: 136 passed.

Round 1 checks (fix commit against `a733d920`): `make test-inference`, the
domain package's unit level, 169 passed; `make test-registry`, unit 129 and
integration 138 passed (the integration level: the real registry app and its
database through the typed client over ASGI transport); `openspec validate
--strict` valid for this change, `compose-inference-domain-stack`, and
`meter-inference-usage`; `make check-comment-hygiene`, `make check-doc-citations
CHANGE=add-inference-domain-contract`, and `make check-architecture-change` pass.
No dependency changed, so `make lock` and `make check-packaging` were not rerun.
`make test` (keep-going) ran every suite; the inference, registry, kit, core,
and buyer suites passed, and four suites failed in files this round does not
touch: `provisioning/compute/service` unit (`test_config.py`, the dotenv layer
ordering), `test-provisioning-iac` (`test_cleanup_script_relay_teardown.py`),
`test-release-tooling` (`scripts/tests/test_validate_slice.py`, the pipeline
marker variables), and `test-storefront` integration (`test_alkahest.py`, whose
`EnvTestManager` needs the development chain). The diff changes nothing under
those paths; validation characterises them. The fresh-context compliance check
of the diff found no must-fix item; it asked for, and this round made, the
uint256 upper bound on card amounts and the derived charge that the delta's
"uint256 domain" wording promised, the card's asset check on the pricing path
as well as the codec, and a true name for the rejection test; it noted that
the buyer plugin's sentences were restated as a requirement rather than moved
verbatim, which `design.md` now says. Declined: normalising a checksum-cased
option address against the card's asset (exact string comparison is the rule
across the filters and `SettlementOption.asset`), and tightening the served
shape against the leading-zero and whitespace strings the model canonicalises
(only a publisher bypassing the codec meets the shape).

Round 2 (implementation review 02, external). F1: usage evidence carries an
attestation reference — a short lowercase `kind`, `schema_version`, and a
`sha256` digest — never a payload, and a canary placed in any slot is refused;
the card's envelope keeps its opaque payload. F12: that payload must be
canonical JSON at validation. F15: `schema.py` binds the family's carriers from
`arkhai_api_contracts.carriers` (message, terms, receipt, result), and
`InferenceMaterialization` subclasses the family's materialization model with
`rate_card` (3.2's local carriers are replaced); `arkhai-api-contracts` is
declared. F3: the materialization refuses a card other than the carried accepted
listing's. F11: recording the accepted card on the grant moves to
`compose-inference-domain-stack`'s delta, and pricing consumption by it and
debiting each grant-and-request pair once to `meter-inference-usage`'s. F2 and
F10: an option advertises exactly one amount rate and an escrow at most one,
and the selected-option path runs the same check, the card's asset included. F7:
the wheel is in `manifests/published-distributions.json`, the PyPI workflow, and
`docs/guidance/repository/published-packages.md`. F4: the filter specification requires
`endpoint.api_style`. F14: a unit test checks both registry image stages copy
each repository filter specification. F5: the proposal, Migration Plan, and the
header above state the purchase-shape tightening and the new dependencies.

Evidence: domain-package unit `make test-inference` 176 passed; family kit
`make test-api` passed; `make test-apicredits` passed; registry unit and
integration `make -C core/registry test` passed (132 and 139), with the new
`api_style` dry-run case and Dockerfile check; release tooling 1135 passed, one
failure from the host's `make` lacking `--eval`. `make -k test`: every suite
passed except three named failures, each environmental and failing at the
round's base commit as well — `test-provisioning-iac`'s relay-teardown shell
tests, `test-storefront`'s `test_alkahest.py` (needs the development chain), and
that release-tooling case. `make check-packaging`, `make check-comment-hygiene`,
and `make check-change` passed. The fresh-context compliance check found five
must-fix items, all fixed: the reference's `kind` admitted free text; the
canary scenario for produced evidence had been replaced rather than kept; the
one-amount-rate and selected-option asset rules were in code but not the spec;
3.2 and the proposal did not record the carrier binding; and a promotion row
cited the requirement's old name. Of its suggestions it took the design
heading and wording fixes and a selected-option two-rate test; declined
renaming the family factory classes, whose names come from the family.

Round 3 (implementation review 03, external). F5: `InferenceMaterialization`
requires the accepted listing, unlike the family's handoff, and always compares
its card, so no handoff pins a card without the listing to hold it to; the spec
gains "Handoff omits the accepted listing". F7: `make test-inference` builds
`dist-api-contracts` first and runs `require-wheels`, as the family's targets
do. F6: the proposal declares the `api-family` modification and narrows the
non-goal. F8: "Buyer purchases a balance" ends at the reference payment; the
issued balance is the stack change's to prove. F4: the copy-first promotion
rows became one family-kit-first row. F1–F4 moved the corrected plan into the
plan branch, which this branch is rebased onto unchanged. F9: 5.5's
integration test loads the specification from the source tree, the unit test
checks both image stages' `COPY` lines, and the image was built and inspected by
hand once; that the packaged `/app/filter-spec-inference.yaml` loads in a
running registry is left to validation, whose pipeline builds the image.

Evidence: domain-package unit `make test-inference` 177 passed, and from a
fresh checkout with no `.dist` it built its wheels and passed; `make
check-packaging`, `make check-comment-hygiene`, and `make check-change` passed.
`make -k test`: every suite passed except the three environmental failures
round 2 recorded (`test-provisioning-iac`'s relay-teardown tests, which fail at
the base commit too; `test_alkahest.py`, which needs the development chain; and
the release-tooling case needing GNU make's `--eval`). The fresh-context
compliance check passed F5–F8 and found the plan branch still carried copy and
buyer-plugin text in `design.md`, `proposal.md`, and `tasks.md`, closeout parts
9 and 10 misdescribed, and one stale filter name here; all fixed.

## 7. Decision gates

- [x] 7.1 **Decision gate — `model_id` naming authority.** Decided
      2026-09-21 as a domain-owned canonical format; **revised 2026-09-24** on
      review and recorded in `design.md`, "Model identity is seller-asserted and
      convergent": the seller asserts `model_id`; the domain ships a derivation
      rule as a pure function and the spec says a listing SHOULD use it; the
      domain keeps no model list; a registry operator may make the rule a MUST
      for their registry through the filter specification and the registry
      never mints, resolves, or aliases identifiers; `quantization` is an
      enumerated field; a required, filterable `provenance` states
      `self-hosted` or `resold`, and resale is legitimate; an optional
      `model_owner` principal is the three-party hook, with no royalty field;
      `deployment_id` was rejected as a second name for `listing_id`. Sections
      1.3, 1.3a, 1.5, 5.1, 5.2, and 5.3 carry the resulting work.
- [x] 7.2 **Decision gate — credit denomination.** Decided 2026-09-24 and
      recorded in `design.md`, "One pricing layer": one credit is one base unit
      of the listing's settlement asset, the settlement option's per-credit rate
      is exactly one, `quantity` is base units purchased, and rate-card integers
      are prices in that asset. The alternative — an abstract credit each seller
      denominates — was rejected because it makes rate filters compare unlike
      units. Sections 2.1–2.3 and 5.2 carry the resulting work; the rate-bound
      pairing is a declared co-requirement in the filter specification.

*Fix (pre-closeout review 01 F1–F7), outside the plan's sections.* This note
governs where an earlier task or note above says otherwise:
- F1: a registry serving the inference specification refuses a malformed card
  at publication as well as in its dry run, as `registry-discovery` requires;
  the delta, the promotion record and the test module say so, and section 5's
  finding that the registry does not enforce the shape at publish no longer
  holds. Proven by
  `core/registry/tests/integration/test_inference_spec.py::test_a_malformed_card_is_refused_at_publication_and_not_stored`.
- F2: `listings/pricing.py` keeps `validate_listing_rates`, the codec's check,
  and `non_request_priced_rate`; the purchase-pricing helpers of tasks 2.2 and
  2.3 (`selected_unit_price`, `extract_unit_price_from_order`,
  `reference_payment`, `determine_strategy_from_order`) and
  `resource_is_inference` of task 1.3 are removed, since a storefront prices a
  purchase through the family selling library and nothing called them. An
  accepted escrow advertises exactly one amount rate, naming its field and
  unit as the selling library reads it, so no published escrow is priced by a
  configured floor. "Buyer purchases a balance" is proven on the live path by
  `compose-inference-domain-stack`'s storefront tests and its deal scenario.
- F3: the charge requirement states the image term, that prompt tokens
  exclude cached prompt tokens, and that an unnamed cached or image rate is
  zero; D17 says which image use is priced.
- F4: parts 8.5 and 8.6 are open again, part 8.10 is guidance placement, and
  the index row is current.
- F5: the removal of `endpoint` and `rate_card.asset` from the card is an
  unowned gap in the change index, named under D4 and D17.
- F6: `test_inference_spec.py::test_a_narrowed_vocabulary_refuses_another_model_identifier`.
- F7: the proposal's release rows, the design's first risk and task 6.5 state
  what the tree holds.

Evidence, at the fix commit's tree, on an arm64 macOS host:
- `make check-packaging`, `make check-repository` against `dev` for this
  change and for `compose-inference-domain-stack`, and both changes' strict
  OpenSpec validation passed.
- Unit: the inference domain's suite, 181 passed.
- Application integration: the registry's suite, 348 passed; the inference
  storefront's, 77; the inference service's, 31; the gateway service's, 45;
  the inference buyer's, 23; `kit/api/selling`, 239; the API-credits
  storefront's, 277.
- End to end, run locally and not by the pipeline: the inference lane, 1
  passed. The other three lanes were not rerun.
- A fresh-context check of the diff found eight points, all fixed: an escrow
  rate naming no field passed the codec and was unrated to the selling
  library; three task notes and one sentence of
  `compose-inference-domain-stack`'s design still described the removed
  helpers or the registry's earlier posture; a design sentence misplaced; the
  registry test's escrow stating no rate; a return value nothing read; and
  the producer rule's owner unnamed.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** Confirmed: `make check-comment-hygiene` passes,
      and the copied modules were read for references to the API-credits change
      history their docstrings may have carried across.
- [x] 8.2 **Import placement.** Confirmed: no function-level import this change
      adds lacks a genuine circular-import or lazy-load reason.
- [ ] 8.3 **Documentation compliance.** Pending post-review promotion: the
      `inference` capability's `spec.md` and `architecture.md` are created when
      the delta is synchronized at archival, per `AGENTS.md`'s rule that
      promotion follows code review. Re-check accepted decisions against
      `openspec/README.md`'s placement rules; confirm the domain-versus-extension
      rationale and the family-kit-first rule landed in
      the `inference` capability's `architecture.md` and the normative statements in
      the `inference` capability's `spec.md`, not only here. Promote only what
      this branch implements: the vocabulary, pricing, usage, evidence,
      attestation, and registry-discovery requirements, which is everything the
      delta now holds. Archival merges a change's whole delta, so the role
      behaviour `compose-inference-domain-stack` and `meter-inference-usage`
      build — "Bearer credential is delivery, not identity or payment
      authority", "Quota-backed publication", the buyer plugin's discovery, and
      "Admission authority is synchronous and singular" — was moved into those
      changes' own `specs/inference/spec.md` deltas in round 1 (F6) and
      promotes with them, so a reader of `openspec/specs` never meets a
      requirement nothing on `dev` satisfies. The "rejected before publication"
      scenarios stay: the listing codec enforces them since round 1 (F1).
- [x] 8.4 **Narrative compression.** Compress completed-task notes to final
      behavior, validation evidence, and promotion destinations; keep rejected
      alternatives in `design.md`.
- [ ] 8.5 **Roadmap currency.** Update Goal 9's current-state prose in
      `docs/development/ROADMAP.md` (the vocabulary now exists) and remove this
      change's row from its gap table; name the update in the promotion record.
- [ ] 8.6 **Campaign index currency.** Update this change's row and the
      campaign graph in `openspec/changes/README.md`; confirm every campaign
      link resolves to an existing directory.
- [x] 8.7 **Packaging.** `make check-packaging` passes: every lock matches
      its project and the wheelhouse, the new distribution is one package
      under `src/` installing editable, and the architecture check classifies
      `domains/inference` from its row in `docs/development/ARCHITECTURE.toml`
      with the token `inference.v1`. `make check-architecture-change
      CHANGE=add-inference-domain-contract` reports no owned exception or
      override row.
- [ ] 8.8 **End-to-end pipeline.** Not run. The development stack runs under
      amd64 emulation on this host, which the seller quickstart records as
      unsuitable for validation, and no continuous-integration run exists: the
      branch lives on a fork, where Actions does not run, and a fork pull
      request upstream receives no secrets. The registry integration suite and
      an image build ran green locally. This change adds no service and no
      scenario, so the nightly pipeline on `dev` is the regression check for
      the unchanged services; treat its validations as unrun until a run on a
      branch in the main repository is recorded here.
- [ ] 8.9 **Promotion.** Write the `inference` capability's `spec.md` and
      `architecture.md`, the `openspec/specs/README.md` row, the
      `docs/development/ARCHITECTURE.md` one-name and Terms entries, and the
      one sentence in the API-credits companion that the record below names;
      then complete the design-promotion record, last.
- [ ] 8.10 **Guidance placement.** Confirm what this change wrote under
      `docs/guidance/repository/` — the wheel's rows in
      `published-packages.md` — sits in the layer and file its subject
      belongs to, and run `make check-guidance`.
- [ ] 8.11 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=add-inference-domain-contract` and
      `change-workflow openspec validate add-inference-domain-contract --strict` and resolve
      every match. Both pass on the pre-promotion tree.
- [ ] 8.12 **Archival.** `change-workflow openspec archive add-inference-domain-contract -y`
      once every part above is done; update the campaign row to `archived` and
      the dependency graph in `openspec/changes/README.md`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The domain owns the shapes a buyer compares on — model card, rate card, usage record — not what a storefront sells or charges; the payment kit converts money, the storefront prices its balance, and a registry operator decides comparability | the `inference` capability's `architecture.md` — "Market shape"; one sentence in `openspec/specs/api-credits/architecture.md` — "Market shape" |
| One listing is one served model | the `inference` capability's `spec.md` — "One listing is one served model" |
| One credit is one base unit of the settlement asset; the settlement rate is one; the rate card names its asset and prices in integers of it, carried as decimal-digit strings on the wire; every option and escrow on the listing identifies that asset | the `inference` capability's `spec.md` — "Purchase is priced in settlement-asset base units", "Rate card is integer-valued and carried to issuance"; rationale in its `architecture.md` |
| The handoff to issuance carries the accepted listing's rate card; the grant records it and consumption is priced by it in the changes that build them | the `inference` capability's `spec.md` — "Rate card is integer-valued and carried to issuance"; the recording is `compose-inference-domain-stack`'s delta and the pricing `meter-inference-usage`'s, each promoting with its change |
| The request charge is added to the ceiling of the token sum; a failed upstream costs nothing | the `inference` capability's `spec.md` — "Usage record and deterministic charge derivation" |
| A malformed card is refused by the storefront's codec and by a registry serving the inference specification, at publication and in its dry run; the codec also holds the unit rate and the one-asset rule | the `inference` capability's `spec.md` — "One listing is one served model" |
| A record's prompt tokens exclude its cached prompt tokens; the producer that fills a record from an upstream usage block is `meter-inference-usage`'s | the `inference` capability's `spec.md` — "Usage record and deterministic charge derivation"; the producer is `meter-inference-usage`'s delta and promotes with it |
| Charge derivation is a pure function of record and card | the `inference` capability's `spec.md` — "Usage record and deterministic charge derivation" |
| Usage evidence is secret-free by format, its attestation a digest reference, and verification binds it to the grant and the request; debiting each pair once is `meter-inference-usage`'s delta | the `inference` capability's `spec.md` — "Usage evidence is secret-free" |
| Three identities; the bearer credential is delivery | rationale in the `inference` capability's `architecture.md`; the requirement is `compose-inference-domain-stack`'s delta and promotes with it |
| The authority is the singular synchronous admission decision; rating systems are downstream | rationale in the `inference` capability's `architecture.md`; the requirement is `meter-inference-usage`'s delta and promotes with it |
| Discovery under the `inference` schema identity | the `inference` capability's `spec.md` — "Discovery under the inference schema identity" |
| Quota-backed publication in version 1 as the backed value of the declared backing property, quota being a sales cap | trigger in the `inference` capability's `architecture.md` — "Current limits"; the requirement is `compose-inference-domain-stack`'s delta and promotes with it |
| No derived discovery price; a rate bound co-requires the card's asset (`rate_card_asset`) in the filter specification, so the registry refuses an unpaired bound | the `inference` capability's `spec.md` — "Discovery under the inference schema identity"; `architecture.md` — "Current limits" |
| Inference binds the family's purchase shape, which validates exactly the two documented key dispositions and a strict integer quantity for every binding domain | the `api-family` capability's `spec.md` — "The purchase shape admits two key dispositions and an exact quantity" |
| Attestation is reserved, unverified, and unfilterable in this version: an opaque canonical-JSON envelope on the card, a digest reference on the evidence | the `inference` capability's `spec.md` — "Attestation is reserved and unverified"; rationale in its `architecture.md` |
| The family kit first, the stack on it: inference binds the `api` family's purchase shape and carriers rather than copying API credits | `design.md` — "The family kit first, the stack on it"; the `api-family` capability's `spec.md` — "The api family shares one vocabulary and one kit"; `docs/development/ROADMAP.md` Goal 9 current state |
| `inference` joins the enumerated offering modes; **rate card** and **usage record** join the Terms table | `docs/development/ARCHITECTURE.md` — "One name per concept", "Terms" |
| Model identity is seller-asserted with a SHOULD derivation rule; the domain keeps no model list; quantization is an enumerated field; provenance is required and resale legitimate; a registry may curate but never mints; `model_owner` is the three-party hook with no royalty field | the `inference` capability's `spec.md` — "One listing is one served model"; rationale in its `architecture.md` |
