# Tasks — agreed evidence and early termination

Implementation tasks 1–15 are complete, including review 19–23 repairs.
Closeout 16.1–16.11 is complete: the verified current system is promoted and the
change is archived after owner review. Published contracts are vendored; deployed qualification and its
limits are recorded below. Hosted development mediation remains on an older revision.

Sections follow the design's implementation cadence. Sections 1–7 are round 1 (foundation,
wire and buyer side), except 7.5's explicitly round-2 end verification; section 8 joins round 1 once its schema and vectors are vendored
into `kit/arkhai-payments/schema/`. The per-part lifecycle revision is published;
including `partialPeriod`; the setup part is an ordinary once part the service clamps to zero length at approval and needs no further payments-contract confirmation; its return for non-delivery is mediation's, by the filing's `delivered` flag (12.3), not the payments contract's. The exact producer revision is recorded only in schema/SOURCE.md at 8.1.
Unsupported terms fail closed; once-only work does not wait for unsupported rate terms.
Sections 9–15 are round 2 (seller servicing and domain wiring); section 16 is the closeout.

Wire and persistence breaks, all forward-only (design.md, D5 and "Rollout"): the option's shape
becomes `price`, `settlement` and `lifecycle` in 2.5, so every option ID and Agreement's bytes
change, Alkahest and contact-exchange included, and every listing is republished; every hosted
mandate hash and test vector changes in section 8; `[Settlement.arkhai_payments].dispute_authority`
is rejected from section 3; `[Settlement.alkahest]`'s two release flags are migrated in section 4.

Paths: `src/` abbreviates each package's source root. Kits keep in-process contract fakes
generated from the same contract vectors for unit and library-integration tests; no kit or its
library tests depends on runnable-double tooling. `add-arkhai-payments-lane-double` owns the
runnable HTTP payments/mediation doubles for lanes and end-to-end runs. This change supplies
contracts, clients, adapters and signing fixtures: sections 1–2 (including 2.4's acknowledgement
model), 8.1, 9.1 and 12.1 (including models/signing fixtures) precede the corresponding
HTTP double. Section 2.4 owns the neutral acknowledgement binding/verifier over kit/identity;
13.1 signs storefront responses and embeds the contract-owned signed claim after 12.1/12.5. Mediation uses the payee-agreed delivery_end guards for either filer; section 7.5 runs in round 2
after 12.3 and 13.3. Convergence owns funding
timers and consuming servicing scenarios; `activate-per-period-compute-servicing` owns hosted
four-path e2e against the public test deployment (design.md, D15). Sections that change existing deal paths
name the existing scenarios that must keep passing. The buyer-termination fold additionally
extends those existing compute scenarios with delivery-only end and signed-report retrieval
stages; rate adapter stop/outage checks belong to `spot-deals-through-arkhai-payments`,
while convergence owns consuming servicing scenarios and activation owns hosted qualification.

Dependency gates for the folded end work: sections 2 and 10's final-request and site-report
contracts precede section 13's peer/read routes; sections 7 and 13 precede both domain CLI
paths. `unify-compute-delivery-path` consumes section 10's admission interface and must preserve
these early-end scenarios. Archive this foundation and `activate-compute-leases-at-the-site` first, then unify, then
`renewable-compute-lease-deadlines`, and unify before redesign-authenticated-requests; the
overlapping deltas that must be rebased in that order are `physical-provisioning` (this
foundation's event and outbox, unify's lifecycle adoption, then renewable's watchdog cause) and
`site-capacity` (this foundation's end report, the activation change's phase and transition,
then renewable's deadline); their later MODIFIED requirements must preserve every foundation clause and scenario
(including option-owned authority, reverse part/amount, normative holds and exclusive
end-service lease writes). `renewable-compute-lease-deadlines`
adds deadline-specific causes/phases later, not a gate on this report. Reuse
`replace-polling-with-authenticated-push`'s transport if it lands first; otherwise section 10
supplies the single-event outbox it later adopts. `buyers-use-the-storefront-client` does not
gate this end method. Rate end validation waits for `spot-deals-through-arkhai-payments`;
in-lane payments/mediation evidence additionally waits for `add-arkhai-payments-lane-double`,
with live hosted evidence gated on the deployed contract revision.

## 1. Kit areas and the dispute-interface architecture check

Delivers the buyer-side kit area, the dispute-kit kind and the `[[disputes]]` table, with the
check that enforces them, before any package relies on them. Implements D6 ("Packaging") and the
deal-lifecycle requirement "Dispute adapters resolve by dispute interface" (a dispute kit names
no payment mechanism). Files: `docs/development/ARCHITECTURE.toml`, `scripts/architecture.py`
and its tests under `scripts/tests/`.

- [x] 1.1 Add the buyer-side area and the dispute-kit kind to `ARCHITECTURE.toml`: a
      `[[disputes]]` table registering each dispute interface and its kit beside
      `[[mechanisms]]`, with no row yet (section 12 adds `arkhai.mediation.v1`), and the
      buyer-side area's dependency rule (foundation libraries and contracts only; composed by
      buyers, never by a storefront or a site). Verify: `make check-architecture` passes on
      the unchanged tree.
- [x] 1.2 Teach `scripts/architecture.py` the table: load `[[disputes]]`, grant each interface
      token to its kit, add interface tokens to the vocabulary check, refuse a kit scoped to both
      a mechanism and a dispute interface, refuse a dispute kit whose sources name a registered
      payment mechanism token, and enforce the buyer-side area's dependency rule. Verify: unit
      tests over fixture trees for each refusal and for an accepted dispute kit.

Verification point: the architecture script's unit tests; `make check-architecture`; `make test`.
End-to-end: none; the check runs in CI only.

## 2. Lifecycle contracts and the foundation kit

Delivers `kit/deal-lifecycle-contracts` and `kit/deal-lifecycle`: wire models, the term codec
and semantics, adapter protocols and tables, deal-level intents, and the evidence-store
interface. Implements D1–D3, D5 (the option's shape, terms, codec, semantics table, entitlements
as stop authorities), D6 (commands, outcomes, events, adapter families), D9 (evidence record shape) and
D10 (case payload, outcome shape, intents), and the deal-lifecycle requirements "Payment events
are per part", "An outcome is a list of per-part effects", "Requests are intents or interface
requests", "Lifecycle terms are part of the selected option", "The adjudication term names the
dispute authority", "Malformed terms are refused", "Dispute timing terms are bounded",
"Entitlements are the stop authorities", "Lifecycle commands have defined outcomes", "Dispute
writes are idempotent", "Adapters resolve per mechanism and arbiter", "Dispute adapters resolve
by dispute interface", "Evidence is keyed by negotiation" and "A dispute is one case payload".

- [x] 2.1 Create `kit/deal-lifecycle-contracts` (contracts kind): commands
      `{negotiation_id, kind, operation_key, at, payload}`, outcomes (`accepted`, `rejected`,
      `pending`, `unknown`), per-part payment events including `extend` and `lift` with
      `extension_ref` and `case_ref`, per-agreement dispute events, the filing answer with
      per-part `held` / `not_held` and reason, peer messages `commit` and `hint`, the case
      payload, evidence items, and route contracts and response models for section 13. Wire it
      into the build, `.dist` and locks. Verify: unit tests round-trip each model and refuse
      unknown kinds; `make check-packaging`.
- [x] 2.2 Create `kit/deal-lifecycle` (foundation library, on the contracts) with the term codec
      for `adjudication` (`dispute` as `{interface, origin, account, record_key, params}`),
      `early_termination` (no `exposure_seconds`; entitlements' and term end's `settles_through`
      values and `partialPeriod` mapping per D5, plus nonnegative minor-unit decimal-string `premature_stop_penalty`, absent/zero meaning none), positive-integer `delivery_deadline_seconds` (the "Delivery has a deadline" semantics; the compute builders in `negotiate-open-ended-compute-terms` emit it from the pool's tag) and reserved `bond`; malformed and bounded-term refusal
      (`case_hold_max_seconds` a nonnegative integer or `null`, minimums from an authority's
      advertisement copy); and the semantics table. Verify: unit tests for each refusal in the
      "Malformed terms are refused" and "Dispute timing terms are bounded" scenarios (the window
      shorter than the delivery deadline plus the authority's minimum included), and that
      a term change changes the option ID through the existing option-ID function.
- [x] 2.3 In `kit/deal-lifecycle`, define the payment-adapter and dispute-adapter protocols and
      their tables (payment by negotiation ID, mechanism and arbiter or oracle; dispute by
      `adjudication.dispute.interface`), injected by compositions; the deal-level dispute
      intent delivery_end {ended_at, delivered, cause: payee|payer}, filed by either party, never a payments event; derivation of each part's stop authorities from entitlements plus
      the agreement's dispute authority; operation-key handling (derived idempotency keys for
      part events, filings and appends; local refusal of a retry with changed content); and the
      evidence-store interface keyed by negotiation ID. Include neutral payment-adapter
      authorize(phase, evidence) and start_billing(operation_key, activated_delivery_evidence)
      with the shared reserve/commit/dispatch/activate/start/disclose enum and versioned secret-free
      identity/digest envelopes, including activation record reference and instant; once-only returns allow/no-op
      after commitment validation. Verify: unit tests for "A mechanism has
      no adapter for a command", "A deal names an interface with no adapter", "An interface has
      no buyer-end request", "A retry changes content" and the on-demand stop-authority scenario,
      using fake adapters. Include the protocol rule from D5 (a stop only under a stated entitlement entry; no notice waiver or
      early release), with fail-before-I/O refusal until vendored; no extra entitlement.

- [x] 2.4 Extend peer/route/read contracts with receipt-only end_delivery (no at), signed
      acknowledgement binding request identity, seller-recorded receipt, selected end,
      progress and verbatim site reports. In kit/deal-lifecycle implement the shared binding
      and verifier over kit/identity v2, usable by buyer/client/dispute kits without servicing
      dependency; 13.1 signs the route response and embeds the separately signed contract claim after 12.1/12.5. Include rejected authority view beside readable delivery
      when no adapter exists. Define one delivery_end intent for either filer and either cause, neither a payments event. Define receipt embedding of the contract-owned SignedDeliveryEndClaim; vendor-gate its concrete payload at 12.1. Verify refusal of supplied at, receipt preservation on retry,
      Agreement-principal signature binding and exact report bytes. Gates 7, 10 and 13.
- [x] 2.5 Reshape core's `SettlementOption` to `{option_id, price: {asset, rates}, settlement:
      {schema, ...}, lifecycle?}` per D5 ("The option's shape"), with the option ID the hash of
      the canonical payload of `price`, `settlement` and `lifecycle`, the last omitted when
      absent; move every builder (hosted, Alkahest, contact-exchange, API credits), the buyer's
      selection mirror and the registry carrier onto it, with no reader of the old `mechanism`,
      `asset`, `rates` or `params` keys left. Verify: each existing mechanism's deal
      negotiates, commits and is fulfilled under the new shape in its unit and
      application-integration suites; a client that does not recognize the shape refuses at
      selection, before approval or escrow funding, never during fulfillment; `e2e_deal`,
      `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` pass on republished listings.
  - [x] 2.5a Add internal price, settlement-schema/parameter and lifecycle accessors
        without changing serialized options or IDs. Route buyer admission and acceptance,
        negotiation policies, pricing and mechanism projections, fulfillment dispatch and
        persisted Agreement queries through the accessors. Files: core carriers and buyer;
        settlement-runtime, policy, Alkahest and contact-exchange adapters; VM, bare-metal
        and API-credit consumers. Keep the concurrently owned payments kit unchanged.
        The payments kit's Agreement and public-carrier readers also use the accessors;
        mandates consume the typed mechanism parameters. No permanent wire documentation
        changes in this step.
  - [x] 2.5b Flip the wire model and identity payload to optional `price`, `settlement`
        and optional `lifecycle`; update all builders, selection mirrors, the registry
        carrier, Agreement queries and fixtures together, including the payments kit once
        its parallel work is integrated. Move lifecycle identity coverage to its own key.
  - [x] 2.5c Remove obsolete keys and unused transitional accessors, then run the three
        named end-to-end suites on republished listings. Promote the wire contract to the
        settlement-configuration and negotiation-protocol specs at reviewed closeout;
        lifecycle ownership goes to the deal-lifecycle spec and architecture companion.

Verification point: unit tests in both kits; `make check-packaging`; `make check-architecture`;
`make test`. End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal`
on the republished listings of 2.5; nothing composes the kits yet.

### Sections 1–2 result

Neutral contracts, terms, adapter protocols and exact-byte evidence interfaces are implemented.
The option/selection wire cutover has no old-key readers and hashes lifecycle separately.
The published mediation projection gate is satisfied without Agreement rewriting;
provenance stays in `kit/arkhai-mediation/schema/SOURCE.md`. Every listing is republished.
Fresh lanes passed: VM 35 stages, bare-metal mock 39, API-credit hosted payments 3
(zero skips, real local authority). Full tests, typing, architecture, packaging, locks,
hygiene and strict validation passed. Earlier proxy/Docker prerequisites (#323/#324)
were resolved by the prescribed environment and Podman shim. Setup, balance/reversal
observations and readiness-tooling friction (#327):
`docs/attachments/settlement-option-envelope/index.md`. All owned resources were removed.
Promotion: settlement-configuration/negotiation-protocol deltas and lifecycle architecture.

## 3. Dispute authority configuration and registry recommendations

Delivers each role's authority list: `[[Dispute]]` preferences, `[[DisputeCredential]]`
bindings, registry-recommended authorities and the retired payments key. Implements D4
("Registries recommend; roles choose", "Reachable") and D6 ("Configuration"), and the
requirements "A role's authorities are its entries and its registry's recommendations", "With no
authorities, no hosted options" (configuration half), settlement-configuration's "Payments
configuration separates accounts and credentials", "Dispute authorities are configured as
preferences" and "Dispute credentials are bound by identity and no template ships an authority",
registry-discovery's "A registry may recommend dispute authorities", and deployment-state's
"Marketplace deployment config contains consumer data only". Files:
`kit/deal-lifecycle/src/` (typed entries and list resolution),
`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`,
`core/src/market_core/registry_descriptor.py`,
`core/registry/src/core_registry/registry_descriptor.py` and its configuration, the Helm registry
values and `helm/scripts/test-render.sh`, the buyer and storefront configuration templates
(`domains/vms/buyer/src/arkhai_vms_buyer/config_cli.py` and each role's `settings.toml` and
template writer), and `docs/development/DEPLOYMENT_AND_CONFIG.md`.

- [x] 3.1 Add typed `[[Dispute]]` entries (identity, `params`, advertisement copy, not-offered
      and not-accepted marks), `[[DisputeCredential]]` bindings (identity and an
      environment-variable reference) and `use_registry_dispute_authorities` (default true for a storefront, false for a buyer;
      the shipped buyer profiles and fixtures set it explicitly) in
      `kit/deal-lifecycle`, with resolution of a role's ordered list from its entries and a
      supplied registry recommendation list. Verify: unit tests for ordering, marks, the
      opt-out, credential lookup by identity, and that resolved credentials never appear in a
      rendered option or status model.
  - Verified: existing lifecycle suite (62 tests), runnable
    `kit/deal-lifecycle/examples/dispute_configuration.py` (ordering, marks,
    opt-in, full-identity credential binding and secret isolation), architecture,
    packaging, comment hygiene and pinned strict OpenSpec validation pass.
    No new permanent test functions added; fresh verification owns acceptance.
    Buyer template, committed development profiles and the shared hermetic
    e2e buyer writer explicitly opt into registry recommendations. Existing VM
    template tests (2) and parsing of the three committed profiles pass.

- [x] 3.2 Retire `[Settlement.arkhai_payments].dispute_authority`: validation rejects it with a
      diagnostic naming `[[Dispute]]`, and the VM buyer template loses its commented line.
      Verify: `kit/arkhai-payments/tests/test_settlement_config.py` covers "The retired dispute
      authority key is set"; a template-writer test per role asserts no `[[Dispute]]` entry and
      no authority account, origin or key ("A template is written").
  - Retired-key validation names root preferences, including an explicit null.
    Mandate policy and stored-data binding read the selected lifecycle authority;
    only acceptance-time fee policy is recovered from stored mandates. No legacy
    authority fallback remains. Role fixtures, shared e2e policy serialization,
    the VM template and generated Helm schemas use the new configuration.
  - Verified: payments suite (92, including typing/generated-contract checks),
    all buyer suites, e2e unit suite (315), VM payment first-use smoke, both
    storefront schema suites (33 + 11), Helm rendering, locks, packaging,
    architecture, comment hygiene and strict OpenSpec validation pass. No new
    test functions or weakened assertions. The final aggregate result is recorded
    in the section checkpoint and evidence packet.
- [x] 3.3 Add the optional recommended-authorities list to the registry descriptor carrier and
      its operator configuration, built from configuration only, with Helm values and render
      checks. Verify: the descriptor unit and integration suites named in
      `openspec/specs/registry-discovery/spec.md` ("Strict descriptor carriers…") gain "An
      operator recommends an authority" and "A registry recommends none" (library integration
      against the real registry app); `helm/scripts/test-render.sh` passes with and without the
      list.
  - Verified: descriptor unit/library-integration suites (9 tests), including
    configured recommendations through the signed typed client and omission
    when unconfigured; Helm render checks with and without recommendations;
    architecture, packaging, comment hygiene and strict OpenSpec pass.

- [x] 3.4 Fetch a registry's recommendations where roles already read its descriptor (buyer
      bootstrap and storefront publication), and report at startup when a role's list is empty.
      Verify: application-integration tests through the typed client: "A buyer uses its
      registry's recommendation", "A buyer has configured no authority" and the startup
      report of "No authority is available".
  - Buyer bootstrap and storefront startup now read signed, URL-pinned descriptors,
    retain independently resolved per-registry lists, and report empty lists.
    Local preferences/vetoes win by full identity; public buyer context contains
    authority projections only, not credential bindings. Publication resources
    expose the seller policy for the hosted builders in section 8.
  - Verified: lifecycle example/suite, storefront kit, core buyer/storefront,
    registry unit/integration, all three buyer suites, VM storefront unit and
    bare-metal/API-credit storefront suites; packaging, locks, architecture,
    comment hygiene and strict OpenSpec validation pass. Existing fixture bodies
    were adapted, with no assertions weakened and no test functions added.
    Full aggregate and end-to-end validation are recorded with the final checkpoint.
- [x] 3.5 Document `[[Dispute]]`, `[[DisputeCredential]]`, `use_registry_dispute_authorities`,
      the descriptor list and the retired key in `docs/development/DEPLOYMENT_AND_CONFIG.md`.
      Verify: `make check-doc-citations CHANGE=agreed-evidence-and-early-termination` reports
      nothing for the section.
  - The deployment guide now owns role defaults, full-identity ordering/vetoes,
    per-registry signed reads, empty-list diagnostics, advertisement minima,
    identity-bound credential references and retirement of the payments key.
    Payment/seller/e2e guides and release dependency cells agree. Documented TOML
    snippets parse and resolve their exact credential binding.
  - The section's historical citation check reported only the future lifecycle
    destinations tracked by #325, not a new broken implementation link. No
    placeholder was created. Reviewed 16.9 writes the real architecture
    companion and promotion record; normative deltas synchronize only at 16.11.

Verification point: unit suites of `kit/deal-lifecycle` and `kit/arkhai-payments`; the registry
descriptor suites (unit and library integration); the Helm render check; `make test`.
End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` must keep
passing (they start roles from rendered configuration); none exercises the new list.

### Sections 3 and 5 result

Authority entries, signed per-registry recommendations, local identity vetoes,
identity-bound credentials, explicit buyer opt-in, empty-list diagnostics and common
same-option query projections are wired across roles. Generated schemas, isolated
wheels and publication metadata agree. Full tests passed in 7m02s, including release
tooling/Helm, and packaging/architecture/locks/hygiene/strict validation passed.
Library/registry setup: `docs/attachments/aeet-sections-3-5/index.md`.
Configuration guide owns setup; normative deltas promote at archive.

## 4. Alkahest release models

Delivers `[Settlement.alkahest].release_models` in place of the two exclusive flags, one
Alkahest option per model, and the migration. Implements D5 ("Alkahest") and
settlement-configuration's "Alkahest release models are listed per option", "Explicit atomic
configuration migration" and "Each mechanism's option carries its own parameters". Files:
`kit/alkahest/src/market_alkahest/settlement_config.py`, `release_conditions.py`, the VM and
bare-metal storefronts' publication and migration modules
(`domains/vms/storefront/src/market_storefront/publication_migration.py`,
`settlement_composition.py`, and their bare-metal counterparts), `DEPLOYMENT_AND_CONFIG.md`.

- [x] 4.1 Replace `oracle_gated` and `interruptible` with `release_models` drawn from
      `recipient`, `oracle_gated` and `interruptible`, validating oracle settings against the
      listed models. Verify: `kit/alkahest` unit tests for each model and each refusal.
  - Verified: Alkahest unit suite, 447 passed. Configuration accepts ordered,
    nonempty unique model lists, rejects obsolete flags and oracle-address lists
    for unoffered models, and derives separate chain conditions for each model.
    Domain composition and option materialization follow in 4.2.
- [x] 4.2 Publish one Alkahest option per listed model in the VM and bare-metal storefronts, with
      no lifecycle terms (no Alkahest lifecycle adapter exists). Verify: application-integration
      test for `release_models = ["recipient", "interruptible"]` publishing two options without
      `adjudication` ("Builders emit terms only where they bind").
  - Verified: kit unit suite (447), VM unit/integration suites (1,189/501;
    corrected duplicate-list diagnostic re-drive passes), bare-metal storefront
    (522), and API-credit storefront (248). The VM application journey publishes
    recipient and interruptible options and negotiates the second through the
    real buyer plan validator; bare metal publishes recipient and oracle-gated
    choices. Each option pins its demand under settlement.accepted_escrow and
    has no lifecycle. Undeliverable models now refuse startup, as designed.
    Existing test intent follows that deliberate refusal change; no new test
    functions were added. Templates and generated Helm schemas use the list.
- [x] 4.3 Extend the dry-run and write migration to map the old flags to `release_models` and
      remove them. Verify: migration unit tests for each flag and for both flags absent.
  - Verified: shared configuration suite, 272 passed, including dry-run,
    each old flag, absent/false flags, atomic backup and byte-identical repeat.
    Bare-metal sellers now have a thin CLI over the same migration engine;
    first use covers preview, write, restrictive backup, repeat and conflict
    refusal. Fixture: docs/attachments/alkahest-release-models/legacy-recipient.toml.
- [x] 4.4 Document `release_models` in `DEPLOYMENT_AND_CONFIG.md`. Verify: doc citations check.
  - Configuration and readiness documentation describes the ordered model list,
    per-option demand, domain startup refusal and atomic migration. Citations in
    both changed permanent documents and the first-use packet resolve. The full
    change-scoped citation command still reports three planned closeout targets
    in the active design/tasks, tracked by GitHub issue 325; no placeholder
    permanent document was created. Reproduction and evidence:
    docs/attachments/alkahest-release-models/index.md.

Verification point: `kit/alkahest` unit suites; both storefronts' integration suites; `make test`.
End-to-end: `e2e_deal`, `e2e_non_erc20_settlement` and `e2e_bare_metal_deal` exercise Alkahest
publication and settlement and must keep passing.

### Section 4 result

Release-model publication, startup refusal and atomic migration are complete.
VM ERC20/native/ERC1155 lane: 37 passed; bare-metal mock: 39 passed.
Real-host scenario was readiness-gated (`BARE_METAL.REGISTRY_URL` absent), not qualified.
Full tests and package/document gates passed. Setup and fixture repairs:
`docs/attachments/alkahest-release-models/index.md`. Promotion: settlement-configuration
and the configuration guide; no Alkahest lifecycle adapter is claimed.

## 5. Common query fields

Delivers the lifecycle term projections as common settlement fields. Implements D5 ("Query
fields"), cli-query-language's "Settlement fields have common and mechanism-owned
namespaces" and settlement-configuration's "Mechanism clause fields stay in their namespace". Files: `core/src/market_core/query_dsl.py`,
`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`, the registry filter
specification and the buyer query client.

- [x] 5.1 Reserve `adjudication.dispute.interface`, `adjudication.dispute.account`,
      `early_termination.payer`, `early_termination.payee` and
      `early_termination.payee.notice_seconds` and `early_termination.premature_stop_penalty`
      (absent zero, asset-correlated minor units) as common fields projected by the
      `kit/deal-lifecycle` codec. Verify: unit tests in `core/tests/unit/test_query_dsl.py` and
      the registry's filter tests; library-integration test in the registry for "A buyer asks
      for buyer-stoppable options" and "A lifecycle term is filtered".

- Verified: common field compilation and same-option projection, asset-required
  penalty comparisons, absent zero/no entitlement, and registry typed-client
  filtering of retained lifecycle terms. Existing focused suites pass: lifecycle
  contracts and foundation, settlement-runtime, core query DSL, registry filter
  unit and library-integration suites. Positive lifecycle query cases seed the
  query boundary directly; publishing lifecycle-bearing options still waits on
  2.5b. No option bytes or IDs change here.
- The lifecycle foundation/contracts now declare the same Python 3.10–3.13
  range as their identity dependency and settlement-runtime consumer. Their
  code uses no newer syntax; without this, uv refuses the new dependency on the
  consumer's supported Python range. Locks were regenerated through `make lock`,
  including mechanically required downstream dependency records. Final focused
  results: contracts 37, foundation 62, settlement-runtime 175, core DSL 24,
  registry unit 129 and library-integration 128; payments 92 plus typing,
  generated models and contract vectors pass. Core typing, architecture,
  packaging, comment hygiene and strict OpenSpec pass. The first aggregate
  run exposed the introduction profile's intentionally changed exact-vocabulary
  expectation; its kept assertion now includes the common fields and the complete
  registry rerun passes. The aggregate subsequently reached API-credit wheel
  installation and release tooling; their resolved failures and final reruns
  are recorded in the sections 3/5 checkpoint above.

Verification point: the query DSL and filter unit suites; registry library-integration suite;
`make test`. End-to-end: none exercises the new fields.

## 6. Envelope capture and the buyer's evidence store

Delivers the envelope-capture seam at the signed transport boundary and `kit/deal-lifecycle-buyer`'s
evidence store, prune command and case export. Implements D9 and the requirements "Each party
keeps its commitment envelopes and authority records", "Envelopes are captured at the signed
transport boundary", "Evidence outlives the deal and its cases", "Pruning observes payouts first"
and "Evidence without lifecycle terms is kept" (buyer side). Files:
`core/buyer/src/core_buyer/negotiation_client.py` (_authenticated_json and public API),
`core/storefront-client/src/storefront_client/client.py` (other verified responses), the
storefront's signed-request verification path (`kit/identity/src/market_identity/verification.py`
and the negotiation controllers that consume it), new `kit/deal-lifecycle-buyer`, and
`core/buyer/src/core_buyer/` composition where the buyer profile root is passed.

- [x] 6.1 Add the injected capture sink to production negotiation's _authenticated_json,
      propagate it through the public negotiation API, core orchestration and both compute
      buyer callers, and capture raw bytes/proof headers before decoding discards them.
      Exercise an actual negotiation acceptance reaching the store before payment approval,
      not just a StorefrontClient stub. Add the seam to other buyer verified responses and the
      storefront's verified-request path, carrying proof headers, exact body and verification
      context before parsed payloads are returned. Default to no capture so existing callers are
      unchanged. Verify: unit tests that the seam receives exact bytes for a verified response
      and request and nothing for a refused one ("The buyer's transport verifies an
      acceptance").
- [x] 6.2 Create `kit/deal-lifecycle-buyer` (buyer-side area) with a file-backed evidence store
      under a root passed by the buyer composition beside the buyer profile, keyed by
      negotiation ID, keeping the seller's signed acceptance before `commit`. Verify: library
      integration test ("A buyer accepts").
- [x] 6.3 Add retention and the prune command: lifecycle deals kept per "Evidence outlives the
      deal and its cases", reading each deal through an injected reader first and deleting
      nothing it cannot read; deals with no lifecycle terms or no adapter, including today's
      Alkahest deals, kept. Verify: unit tests for each retention scenario with a fake reader;
      "A buyer prunes"; "An Alkahest deal's envelopes are kept".
- [x] 6.4 Add case export: one bundle with the commitment reference, terms, claim, requested
      outcome and ordered evidence items carrying exact bytes. Verify: unit test ("A buyer files
      a dispute" payload half).

Verification point: unit and library-integration suites of `kit/deal-lifecycle-buyer`; the
storefront-client and identity unit suites; `make check-architecture` (buyer-side area rule);
`make test`. End-to-end: `e2e_deal_buyer_cli` must keep passing with capture enabled in the
buyer CLI; none checks the stored envelopes.

### Section 6 result

Transactional profile-adjacent evidence captures exact envelopes before approval,
retains superseded commitments, prunes only after complete fresh observations and
exports cases. Compositions inject Agreement projections/readers; the kit imports no
core buyer. Buyer/core/client suites and package gates passed; later full aggregates
supersede early Docker failures. Current API/setup: `kit/deal-lifecycle-buyer/README.md`.
Promotion: lifecycle and buyer-orchestration companions.

## 7. Lifecycle client and the buyer half

Delivers `kit/deal-lifecycle-client` and the buyer half's dispatch: `submit` and `read` without
mechanism branching, `commit` and `hint`, case building around the dispute adapter, authority
acceptance at selection, and the domain buyer stages that inject them. Implements D4
("Reachable"), D6 (buyer half, counterpart table, peer messages), D7, D10 (filing and append from
the buyer) and the requirements "Only the dispute authority acts on a case" (buyer side), "A
filing's outcome is the authority's answer" (reporting), "Peer messages are hints until the
authority confirms them", "The buyer half hides the mechanism", "A buyer accepts an authority
only on an exact identity match", "With no authorities, no hosted options" (buyer half),
negotiation-protocol's "Each option names its dispute authority", and buyer-orchestration's
"Buyer lifecycle actions go through the buyer half" and "The typed client settles Agreement
deals apart from EVM deals". Files: new `kit/deal-lifecycle-client`, `kit/deal-lifecycle-buyer`,
`core/buyer/src/core_buyer/settlement.py` and `orchestration.py`,
`domains/vms/buyer/src/arkhai_vms_buyer/settlement_stages.py` and `settlement_composition.py`,
and the bare-metal buyer's counterparts.

- [x] 7.1 Create `kit/deal-lifecycle-client` for the buyer `commit` and `hint` routes (section
      13 serves them), verifying signed responses. Verify: unit tests against recorded
      responses.
- [x] 7.2 Implement the buyer half in `kit/deal-lifecycle-buyer`: payment commands to the payment
      adapter, `dispute` and `append` to the dispute adapter, outcomes reported as the
      counterpart's own, `read` merging payment events, open extensions and cases, `rejected`
      authority view for a mechanism with no adapter (delivery view remains readable), `hint`
      after a filing. Verify: library-integration tests
      with fake adapters for "A filed case requests a reverse", "The authority cannot complete an
      extension", "Parts differ", "A buyer reads a deal with no lifecycle adapter", "A buyer
      files after the window" and "A filing's response is lost".
- [x] 7.3 Refuse options at selection whose authority fails exact identity match, whose
      interface has no adapter, or whose authority does not advertise the option's payment
      mechanism, and prefer options in list order. Verify: unit tests for "A seller pairs the
      real account with its own origin", "A buyer meets an authority it has not accepted", "A
      seller offers two dispute authorities" and "A buyer prefers one authority".
- [x] 7.4 Compose the buyer half, its evidence store and the lifecycle client in the VM and
      bare-metal buyer stages; compute deals send `commit` after settlement instead of the seller
      settlement handoff where the mechanism has a lifecycle adapter, and Alkahest and API-credit
      paths are unchanged. Verify: application-integration tests through the typed client per
      domain that a hosted-mechanism deal stage reaches `commit` (with kit-owned vector-derived in-process payments and mediation contract fakes; no runnable tooling dependency)
      and an Alkahest deal stage is unchanged.
      Done in both domains: the bare-metal half under 15.2 (e2e_bare_metal_payment_deal reaches the canonical commit; e2e_bare_metal_mock_deal is unchanged) and the VM half under 14.5 (e2e_deal and e2e_deal_buyer_cli; Alkahest delivery is unchanged). Evidence: docs/attachments/bare-metal-lifecycle/index.md and docs/attachments/vm-end-classification/index.md.

- [x] 7.5 **Round 2, after 12.3 and 13.3:** add canonical client end_delivery(negotiation_id)
      and buyer-half end verification/capture. Round-1 dispatch remains fake-adapter work in 7.2.
      Stop at the payment authority first; on unknown/unreachable payments journal the stop and retry
      it under the same key (billing runs until it lands), send receipt-only surrender, and may also
      journal delivery_end(cause=payer), carrying the receipt's SignedDeliveryEndClaim in Filing.concurrence. Use acknowledged receipt time or retain observed time as contested, never a signed backdate. Gate concrete concurrence mapping on 12.1 and 12.3. Retry unavailable filings. Once-only/no-adapter surrender invents no refund. Verify with injected adapters
      for payment outage, both authorities down, no acknowledgement, supplied at rejection,
      stable-key retry, and separate delivery/payment/case progress. Receipt concurrence enables automatic ruling under the foundation's guards; otherwise triage.
      Rate stop/hint, nonzero notice, lost-stop response and seller billing re-drive belong to
      spot; this task does not gate round 1 or require spot completion.

Verification point: unit and library-integration suites of the client and buyer kits; the VM and
bare-metal buyer application-integration suites; `make test`. End-to-end: `e2e_deal`,
`e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal` must keep passing; none exercises a hosted
lifecycle deal.

### Section 7 result

Signed client, injected dispatch, stable keys, direct-authority/delivery reads and exact
authority selection are implemented. Both compute stages compose them (7.4/14.5/15.2).
First use, focused suites and full tests (7m20s) passed; package/typing gates passed.
Setup: `docs/attachments/lifecycle-buyer-foundation/index.md`.
Rate execution remains deferred; promotion: lifecycle and buyer-orchestration.

## 8. Hosted mandates, buyer mandate check and hosted option builders

Gated: starts once the payments contract revision is vendored (schema and vectors together) and
identified in `kit/arkhai-payments/schema/SOURCE.md`; until then every derived hosted mandate
fails the vendored schema. Delivers per-part authority and hold derivation from the terms, the
buyer's mandate check, hosted option builders that emit lifecycle terms, and the API-credit
roles' authority checks. Implements D5 (window, holds per part shape, extension authorities,
case-hold cap), D4 at publication, and the requirements "Builders emit terms only where they
bind", "The dispute window sets the earliest payout" (`once` derivation), "Case holds are
capped by terms", "Only the dispute authority extends and lifts", "With no authorities, no
hosted options" (storefront half), "Lifecycle servicing is composed by the compute domains"
(API-credit half), settlement-servicing's "The payments mandate is derived exactly from the
Agreement", storefront-publication's "Payment publication discloses mandate policy" and
"Lifecycle terms are published per option", and buyer-orchestration's "Payment buyers approve and
settle by negotiation". Files: `kit/arkhai-payments/schema/`, `src/market_arkhai_payments/mandates.py`,
`buyer.py`, `seller.py`, `test-vectors/`, the VM, bare-metal and API-credit storefronts'
`settlement_composition.py`, and the API-credit buyer.

- [x] 8.1 Derive seller stop entries only for entitlements (such as spot's notice entry), with
      existing reverse authority and no notice waiver, early release or restitution entry.
      Confirm that a payer stop retried under one key after an outage lands once with its notice.
      Spot implements rate commands; this foundation supplies the protocol and coherent vendoring.
      Vendor the contract revision (`extend` authorities key, `maxHoldExtension`,
      per-extension refs, per-part authorities with stop notice durations and `partialPeriod`,
      `end` with its own `partialPeriod`, `afterStop`
      holds; producer signed-snapshot and before/after-start vectors) and refresh vectors. Build one clock-injected payments authority engine in kit/arkhai-payments fixtures.
      The kit's in-process fake uses it directly; the HTTP double wraps it with controls and
      mediation composition. Supply installed resource APIs for selected schema/vector bytes,
      generated models and publication/hash metadata from built wheels. Generate resources from
      one canonical source; pin any missing capability's candidate bytes in this kit, not tooling.
      The lane-only proposed declaration selects the same candidate for publication, acceptance,
      derivation and qualification, never a union. Include producer integration-test evidence
      for chosen/end/reverse (not a real-HTTP drive), plus partial-reversal vectors before/after stop.
      Both consume the same vectors; no second authority algorithm or
      kit-to-tooling dependency. Verify: `test_receipt_fixture.py` and the
      vector conformance tests pass against the new content hash.
      Implemented: coherent published schema/vectors and generated wheel resources;
      `contracts.get_contract` exposes selected bytes/models/publication hashes.
      One clock-injected `fixtures.PaymentsAuthority` backs the fake and the
      installed conformance replay (four signed snapshots, nine scenario steps).
      No payments candidate is required; unavailable proposed selection refuses.
      The existing once derivation only migrates to per-part reverse authorities,
      empty stop/extend lists and a zero extension cap; lifecycle derivation remains
      in 8.2. Producer integration evidence and provenance: payments `schema/SOURCE.md`.
      Focused verification: 92 tests, typing, model/resource drift and all vectors
      pass; installed-wheel first use, architecture, packaging, comment hygiene and
      strict OpenSpec validation pass. Evidence and aggregate-run disposition:
      `docs/attachments/payments-contract-foundation/index.md`.
- [x] 8.2 Derive each part's authorities and holds from the terms: prepaid `once` end at term end,
      setup `once` end at the later of the Agreement start and approval, hold `{afterStop: dispute_window}`;
      each party's stop notice exactly its entitlement's notice_seconds; derive the dispute
      authority's {account, notice: PT0S, partialPeriod: chosen} entry here, not again in spot;
      entitlements' and term end's `settles_through` mapping to stop-authority and `end.partialPeriod`
      respectively per D5; compute term ends use returned. Fail closed when the vendored
      contract cannot express it (interim rate stops charged on both sides;
      recommendation: absolute end with a charged final partial period disclosed in the option). `extend` authorities and `reverse` for the
      agreement's dispute authority taken from the option; `maxHoldExtension` from
      `case_hold_max_seconds`. Verify: `test_mandates.py` cases for "A once deal's hold is
      derived", "A bounded case hold is derived", "An unbounded case hold is derived" and "A
      mandate's extend authorities are derived".
      Implemented: absolute once term ends (fractional ends round up), afterStop
      holds, exact authority-only extensions and nullable caps. `derive_part_terms`
      supplies the same setup and rate authority/end mapping to later builders;
      once-only derivation refuses early termination and bonds. Setup once parts
      in a rate-bearing option ignore its rate entitlements and retain no stops.
      Payments kit:
      92 tests, mypy, model/resource drift and producer vectors pass. A temporary
      diagnostic exercised zero/bounded/unbounded caps, setup end, and payer/payee/
      dispute rate entries with exact notice/treatment. Promotion remains closeout.
- [x] 8.3 Extend the buyer's mandate check to the derived authorities, holds and dispute
      authority. Verify:
      `test_buyer.py` cases including the payee-as-stop-authority refusal.
      Implemented: buyer re-derivation checks the complete per-part lifecycle
      policy, including option-owned authority identity/account, hold, cap and
      permissions. The kept buyer-policy assertion now exercises seller stop,
      shortened hold, cap and reverse/extend substitutions as well as fee changes;
      all 97 payments tests, typing, vectors and generated-resource checks pass.
- [x] 8.4 Emit `adjudication` from the storefront's first offered authority advertising the
      option's mechanism (or one option per offered authority), publish nothing hosted with an
      empty list, and refuse incompatible authorities at publication, in the VM, bare-metal and
      API-credit storefronts; the API-credit buyer checks options against its list. Verify:
      application-integration tests per storefront for "An authority does not serve the payment
      mechanism", "A zero case hold is below the minimum", "No authority is available" and "An
      API-credit storefront publishes a hosted option".

Implemented: all three storefront roots supply their offered authority lists and
installed mediation interface to the shared builder. The first offered authority
advertising payments supplies adjudication; empty policy emits no hosted option,
and incompatible interfaces, windows/caps and missing compute deadlines refuse.
API-credit buy/standalone negotiate filter exact registry-specific authority
identities/params, and approval rechecks them. Publication clauses explicitly
supply dispute_window_seconds; omission of case_hold_max_seconds is unbounded.
Since one listing's option set serves all its destination registries, publication
uses the ordered intersection of their resolved lists rather than importing one
registry's defaults into another. A locally configured authority appears in each
resolved list. The installed-wheel first-use entry point is
`docs/attachments/hosted-lifecycle-policy/first_use.py`.
Focused results: payments 97, VM storefront 1,189 unit and 501 integration,
API-credit storefront 248 and buyer 35 pass. Bare-metal storefront has 521 passing
cases plus the repaired snapshot-signing fixture case passing on focused rerun;
all 522 pass in the final aggregate.
All four new mediation dependencies and the e2e consumer were relocked. Mediation
is included once in the publication manifest/workflow and release table, and the
API-credit installation fixture builds its wheel. Release-tooling and deployment
packaging pass after these dependency-closure updates; packaging,
architecture, locks, hygiene and strict OpenSpec validation pass. The final full `make test` passes in 7m 2s with the shell-local Podman shim,
including 1,848 release-tooling cases and Helm assertions. Final packet:
`docs/attachments/hosted-lifecycle-policy/index.md`.

Verification point: `kit/arkhai-payments` unit and vector suites; the three storefronts'
application-integration suites; `make check-packaging` (vendored schema); `make test`.
End-to-end: `e2e_credits_payment_deal` exercises hosted mandate derivation and approval; it is
readiness-gated on a payments target and is evidence only where one is reachable.

## 9. Snapshot-proof verification

Delivers verification of snapshot proofs before any snapshot state is read, ahead of `watch`.
Implements the design's dependency item "Snapshot-proof verification in SCM" and D12
(authority records verified). Files: `kit/arkhai-payments/src/market_arkhai_payments/receipts.py`,
`test-vectors/`, the receipt-kit fixture.

- [x] 9.1 Verify snapshot proofs against configured current/retiring receipt identities with validity
      windows, embedded-receipt attestation and a caller-supplied minimum sequence; refuse
      unverified, cross-deal, mode-changed or regressing snapshots. Current-key snapshots may
      attest an embedded old receipt without discarding its original bytes.
      Verify: unit tests with a new snapshot vector and receipt-kit fixture for a valid,
      tampered and wrongly signed snapshot.

Implemented: the shared snapshot frame/verifier checks configured current and
bounded retiring identity pins at their validity instants, exact receipt/deal/
mandate/mode binding and the caller's minimum event sequence. Current snapshots
can attest an embedded configured historical receipt, retaining its proof.
Receipt history is operator-configurable as receipt_identities, with explicit
current service_identity membership. Buyer approval, seller receipt admission and
fully-reversed classification verify snapshots before consuming their state;
HTTP snapshot parsing does not coerce signed values. Seller consumers preserve
an injectable per-agreement snapshot-verifier factory, defaulting to the shared
rotation-aware verifier, so lifecycle adapters can share the same verification
policy. Receipt fixtures reuse the
production frame. Helm config schemas are regenerated. Payments' 97 existing
cases, typing, resource drift and all producer vectors pass; temporary diagnostics
cover tampered/wrong-key/mode/cursor and rotation paths, and the committed
installed-wheel first-use script reproduces those observations. Permanent
configuration docs describe the identity windows; normative promotion remains
closeout. Final aggregate results are in the evidence packet.

Verification point: `kit/arkhai-payments` unit and vector suites; `make test`. End-to-end: none.

## 10. Seller servicing kit: evidence store, end service and watch

Delivers `kit/deal-servicing`: the storefront evidence store, end service and its journal,
delivery admission ordered against the earliest final request, and `watch` loops with durable
cursors under `kit/storefront`'s loop controller, including journaled appends. Implements D6
(watch, cursors, seller half `list`), D8, D9 (seller side), D10 (journaled append, skipped
closed case) and the requirements "Outcome effects are acted on once", "Protection is what the
authority reports" (seller view), "Open extensions are observed per ref", "Any party may append
to a case", "An append to a closed case is skipped", "Filing is not a delivery ruling", "A seller's exceptional end is a dispute filing", "The seller half lists deals", "Dispute
authorities are named per deal", "Watch replays from a durable cursor per record", "A watch
cursor advances after its effect is journaled", "End service keeps the earliest final request",
"End service terminates or truncates, and journals each effect", "The earliest final request
governs delivery admission" (kit half), the seller half of the evidence requirements, and
market-composition's "Marketplace roles hold no payment ledger". Files: new `kit/deal-servicing`,
`kit/storefront/src/market_storefront_kit/composition.py` (loop registration).

- [x] 10.1 Create `kit/deal-servicing` with the storefront evidence store (seller envelopes on
      every acceptance path through the section 6 seam, administrator as author on
      administrative acceptance) and its retention. Verify: library-integration tests for "The
      seller accepts the buyer's opening", "An administrator accepts" and the retention
      scenarios. The SQLite evidence port and caller-session capture/acceptance seam
      retain exact envelopes, accepting author and frozen terms; retention requires
      complete watched payout/case/recovery observations. First-use example exercises
      verified opening/counteroffer/administrative messages, restart and retention.
      Existing foundation/contracts suites pass (62/37), as do architecture, packaging,
      comment hygiene and strict OpenSpec validation. No new acceptance tests were
      added under the implementation-worker testing boundary; domain wiring consumes
      the transport capture seam in sections 6, 14 and 15.
- [x] 10.2 Implement end service: earliest-wins final requests from authority, dispute and local
      sources, recorded whether or not a lease exists; journaled terminate or truncate effects
      through a narrow domain port. Own `admit(negotiation_id, phase, expected_revision) → admitted |
      ended(T), revision` over the caller's storefront database session, with durable revision/CAS
      ordering reservation, dispatch, activation and credential authorization against end recording.
      Own `record_end(final_request, filing_intent? | pending_classification?)`, journaling both atomically in that session;
      stale revisions retry admission and cannot authorize work. Add the pending-classification slot
      and resolve_correction(source_ref, expected_revision, evidence, classification, filing_intent?)
      atomic resolution in the same journal; use D8's closed evidence-based classification
      with non-delivery at the earlier of the term end and `delivery_deadline_seconds` after
      the later of the commitment instant and `start_utc` (verify: "The seller activates after
      the delivery deadline inside a long term"),
      preserving earlier never-delivered failures despite later clock/payee stops. Supply the neutral delivery
      authorization protocol and versioned secret-free evidence envelope from D6. End service
      alone exposes begin_billing(operation_key, activated_delivery_ref) and journals billing-start key/evidence before I/O; accept delivery's stable operation key
      and return an intent reference, never let the delivery record own a competing key.
      These are section-level prerequisites
      for unify's delivery consumer, not a whole-change cycle.
      Verify: unit tests with a fake domain port for "A ruling ends delivery before the lease
      exists", "The end overlaps delivery start" and "The storefront restarts between the end
      and provisioning". Caller-session revision/CAS, earliest-source ordering,
      atomic filing/pending-classification slots, fixed-basis correction resolution,
      deadline admission and one-owner billing intents are implemented. The committed
      first-use examples exercise persistence/restart, dispatched adoption, late earlier
      evidence without repeated termination, future-start correction and once no-op
      billing. Seventeen temporary diagnostic checks cover rollback, equal-time ordering,
      stale authorization, non-delivery despite a later lawful stop and unknown billing
      resolution. Packaging/architecture, hygiene and strict validation pass.
- [x] 10.3 Implement `watch`: one durable cursor per record (payment authority, dispute
      authority), advancing after the effect is journaled; delivery ends to end service once per
      effect ID; a counterparty's case journaled as the seller's append with an idempotency key
      and skipped for a confirmed closed case; record entries verified against the Agreement's
      `record_key`; open extensions tracked per ref; a buyer's `commit` or `hint` kept as evidence
      and answered by a read, never by a state change. Verify: library-integration tests with fake
      adapters for every `watch` and append scenario of the deal-lifecycle delta, including
      "A ruling is read while partly applied", "Two cases overlap", "The storefront crashes
      before appending" and "A case is filed and closed while the storefront is down" and "A forged hint arrives".
      Durable independent cursors and cached views retain extension references; effects
      and interface-built appends precede cursor advancement. The mediation adapter
      packages exact stored evidence, and uncertain appends replay their original key
      before closed-case skipping. A committed example uses the vendored mediation
      fake for lost responses, prepared/applied effects and a case closed during downtime;
      temporary diagnostics cover overlapping extensions and false hints. Foundation
      (62), mediation (40, including contract/generated/typing checks) and storefront
      (131) regressions pass. Shared storefront composition exposes controller-owned
      watch registration; domain composition remains in sections 14 and 15.
- [x] 10.4 Implement the seller half's `submit`, `read` and `list` (bounded pages, lifecycle
      states, open extensions and cases, repair required for a missing authority credential) and
      the delivery_end filing, journaled with an immediate attributed end and dispatched
      to the dispute adapter, with no stop or reverse of its own and no wait for a ruling. Verify:
      unit and library-integration tests for "A seller lists its deals", "An authority's
      credential is missing", "A seller stops offering an authority", "An administrator ends a once-only deal" and "A filing is not ruled".
      Immutable committed metadata, bounded keyset pages and merged watched views
      resolve pinned authority credentials independently of offered preferences.
      Operator ends retain actor/reason and atomically journal an immediate end
      plus the fixed-basis filing; dispatch replays unknown responses by key without
      payment commands or a ruling wait. The committed seller first-use example
      exercises empty/bounded pages, once-only running, credential repair, lost
      filing acknowledgement and restart with one case/physical effect. Foundation
      and mediation regressions, source typing, architecture, packaging, locks,
      hygiene and strict change validation pass. Domain route binding remains in 13–15.

- [x] 10.5 Persist final-request identities, actors, causes, instants and evidence references,
      including superseded requests and administrator identity/reason for operator ends,
      and expose earliest-end attribution and current physical
      progress through `read`. Accept verified site reports as final requests; journal required
      delivery_end(cause=payee) filings atomically with unentitled ends, including never-started
      delivery. Apply D8's fixed min(accepted start, failure observation) basis, with its
      future-start exception: journal now, file at Agreement start with that start as at,
      never future-date a filing. Replay preserves the original key and never resumes delivery.
      Consume D8's neutral classification hooks and correlated lawful ends; do not exempt
      late settlement without buyer evidence. Convergence owns timer classification,
      revised-remedy netting and consolidated rate scenarios. Journal receipt-time end_delivery
      even when payments is down; the storefront issues no billing stop, and the buyer half's
      journaled stop belongs to 7.5 and spot.
      Retain sources and effects under D9 rather than a core fixed floor. Files:
      `kit/deal-servicing`; gate: section 2.4. Verify: kit library-integration targets against
      real persistence for equal-time replay, a late earlier site report after teardown began,
      duplicate report delivery, pre-start failure/deferred filing across restart, and crash between
      end recording and filing intent; assert no
      repeated physical work and no storefront-owned financial end.
      Delivery ingress verifies the accepted buyer's envelope and atomically
      retains receipt time, exact request evidence and lawful surrender before
      returning, without authority I/O. Site ingress requires an injected domain
      verifier of the configured reservation/site binding, retains exact report
      bytes and journals a classified filing or pending slot in the same transaction.
      Existing journal attribution, fixed-basis/deferred filing, correlation and
      D9 pruning are reused. The committed ingress example exercises duplicate
      site delivery, exact-byte readback, restart-stable surrender, pre-start failure
      and one physical effect per deal. All first-use examples, source typing,
      architecture/packaging/locks, hygiene and strict change validation pass.
      Compute's concrete report codec/sender is 10.6; response signing/claim
      embedding and authenticated HTTP binding remain in 13–15.
- [x] 10.6 Implement the site report's independent acceptance boundary first: immutable event
      recording in the lease-ending transaction and a separate event-keyed outbox; signing,
      retry and authenticated lease-read recovery of the stored report. Park push on
      404/unsupported receiver while retaining pull; transient failures retry. Verify the
      coordinated site/storefront and buyer/storefront upgrade, not a legacy fallback. Cover expiry,
      termination, direct release, failure and force-release, preserving release guards and the
      existing capacity-released callback. Files: `kit/site/src/market_site/ledger.py` and its
      persistence/authority ports, `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`,
      `provisioning/compute/contracts` (event and lease models), `provisioning/compute/service`
      (`db/models.py`, migrations, `services/deal_event_sink.py`, lease read composition) and
      `provisioning/compute/client`. Gate: contract model before sender/receiver; no payment
      or dispute service required. Verify: site library-integration targets in
      `kit/site/tests/integration/test_ledger.py` for atomic transitions and deduplication;
      compute service application-integration targets for crash/restart, lost acknowledgement,
      signed push/pull byte preservation, direct release, failure and force-release. Exercise
      the existing lease lifecycle, lease API and capacity-release outbox suites; no sleeps or
      teardown-complete claim from an intent report.
      Implementation records site events and signed, event-keyed outbox entries in
      the same transaction. The configured site/reservation verifier consumes
      original signed payload bytes; authenticated lease views retain those reports
      independently of capacity-release acknowledgements. The committed service
      example covers all five causes, lost acknowledgement/restart, exact push/pull,
      caller attribution, unsupported-peer parking and held capacity after failure.
      Temporary diagnostics also cover production DI, atomic rollback, real-codec
      ingress, earlier late reports, unsigned 404 parking and cross-reservation refusal.
      Existing site/compute/client/service suites and full `make test` pass with the
      prescribed proxy environment and Podman shim. No new permanent tests were
      added; existing fixtures and mock targets follow the composed signer, expanded ports and new migration without weaker
      assertions. Domain receiver binding and deployed coordinated acceptance remain
      in 13–15, not a legacy fallback.

Verification point: unit and library-integration suites of `kit/deal-servicing`; `make
check-architecture`; `make test`. End-to-end: none; no storefront composes the kit yet.

### Section 10 result

Caller-session end/admission CAS, atomic correction/filing intents, independent cursors,
seller views, evidence and signed site event/outbox are implemented. Review-added
permanent suites run under ordinary CI discovery. Clean first use:
`make dist-ci && make -C kit/deal-servicing first-use`; producer:
`make -C provisioning/compute/service first-use-lease-end`. Both own temporary fixture
state. Full tests (7m11s), typing and package/document gates passed.
Promotion: lifecycle, site-capacity and physical-provisioning; deployed evidence follows.

## 11. Hosted payment adapter for once parts

Delivers the `arkhai.payments.v1` payment adapter: `read`, `watch` source, partial `reverse`,
open-extension observation, and reconciliation of unreported commitments. Implements D5, D6 and
D7 for hosted `once` parts, and the requirements "Adapters translate deal commands into per-part
events", "Refund is a reverse command; reconciliation finds unreported commitments",
settlement-servicing's "Only the seller refunds a held payment", deployment-state's "Domain
payment persistence is role-owned", and test-compatibility's "External payment qualification
names its target" (hold extensions are the payments service's evidence, cases the dispute
authority's; this change's suites claim neither). Files: `kit/arkhai-payments/src/market_arkhai_payments/`
(new adapter module, `seller.py`, `reconciliation.py`).

- [x] 11.1 Implement the payment adapter against the kit-owned vector-derived in-process payments contract fake (no runnable tooling dependency): per-part event
      translation, derived idempotency keys, `unknown` resolved by `read`, verified snapshots
      (section 9), open extensions per ref. Verify: library-integration tests for "A reverse's
      response is lost", "A ruling discounts a deal" (observation side), "Two outcomes reverse
      the same part" (observation side) and "A held part shows its extension".
- [x] 11.2 Route seller refunds through reverse and reconcile unreported commitments.
      The payment adapter sends no exceptional-end events: the seller's exit is the dispute
      filing, and the adapter sends only voluntary `reverse {part, amount}` with stable per-part
      keys and verified unknown-result recovery. Spot adds rate commands, not a seller
      self-penalty. Verify test_seller.py and test_reconciliation.py for voluntary reverses and
      crash replay.

Verification point: `kit/arkhai-payments` unit and library-integration suites against the
kit-owned in-process payments contract fake; `make test`. End-to-end: `e2e_credits_payment_deal`'s seller refund is
evidence where a payments target is reachable.

### Section 11 result

The once-only adapter verifies snapshots/cursor floors, observes extensions and performs
voluntary per-part reverses with same-key signed-read recovery. Reconciliation recovers
unreported commitments; it does not apply exceptional-end remedies. Payments suites,
typing, vectors, installed-wheel first use and full tests (7m03s) passed.
Setup: `docs/attachments/once-payment-adapter/index.md`.
Promotion: lifecycle/settlement-servicing; no rate or deployed HTTP result is claimed here.

## 12. Arkhai mediation dispute kit

Delivers `kit/arkhai-mediation`, the first dispute kit: the `arkhai.mediation.v1` adapter, its
client and the vendored contract, with an in-process contract fake and signing fixtures shared by contract vector with the HTTP double. Implements D4, D6 ("Adapters"), D10
and the design's "Arkhai mediation" dependency items as the client side, and the requirements
"Disputes are per agreement and separate from payment", "Requests are intents or interface
requests" (mapping), "A filing's outcome is the authority's answer", "A late case moves no
paid-out money" (client side) and "Dispute writes are idempotent". Files: new
`kit/arkhai-mediation` (`schema/SOURCE.md`, adapter, client, signing fixtures),
`docs/development/ARCHITECTURE.toml` (`[[disputes]]` row).

- [x] 12.1 Vendor the published arkhai.mediation.v1 delivery_end revision with SOURCE provenance, installed schema/model/vector metadata APIs, shared signing fixtures, and the dispute-kit registration. The exact producer revision is recorded only in `kit/arkhai-mediation/schema/SOURCE.md`. Includes DeliveryEndClaim, SignedDeliveryEndClaim, Filing/Append.concurrence, ruling basis, respondent read models and both ed25519/eip191 canonical-frame vectors. Schema/record/claim vectors round-trip, reproduce signatures and verify from the built wheel; architecture, packaging, typing, model drift, comment hygiene and strict OpenSpec checks pass. Mapping/guard/netting vectors are preserved as producer data; SCM performs no monetary computation. No candidate or live service evidence is claimed. Tasks 12.3–12.5 no longer await publication but remain implementation work.

- [x] 12.2 Implement the adapter and client: file, append and read at the Agreement's origin with
      credentials bound by identity; build and validate free-form requests; return the authority's answers, per-part
      `held` / `not_held`, errors and `pending` as lifecycle outcomes; verify record entries.
      Verify: library-integration tests against the kit-owned vector-derived in-process mediation contract fake (no runnable tooling dependency) for "Two cases on one
      deal", "Parts differ", "A part was wholly reversed", "Payout wins against the extension",
      "A late case ends delivery" (filing half), "A filing's response is lost", "The case closes
      during the append" and "The claimant adds evidence" (payee claimant under mediation append authorization).
      Implemented as a stateless async client and injected adapter, with an identity-bound
      credential reference, signed record verification, stable operation-derived keys and
      exact response-byte capture. The 12 library-integration cases, producer conformance,
      model drift and mypy checks pass; the committed `make -C kit/arkhai-mediation demo`
      exercises lost-response recovery and a payee claimant append. Architecture, packaging,
      comment hygiene and pinned strict OpenSpec validation pass. No hosted target is used.
      The typed contract/claim API is available; delivery-end intent mapping (12.3),
      respondent client/polling (12.4) and receipt embedding (12.5) remain unchecked.
      Full `make test` reached 607 passing provisioning units and 453 passing integration
      cases, then hit #323's existing non-loopback fixture/proxy failure. The separate
      closed-loopback fixture repair passed all 454 provisioning integration cases;
      later aggregate targets were not reached and no full-suite pass is claimed.
      Evidence and clean-checkout first use: `docs/attachments/agreed-evidence-mediation/index.md`.

- [x] 12.3 Map the single delivery_end claim for either party through kit/arkhai-mediation, using 12.1's vendored schema. Sign/verify SignedDeliveryEndClaim against Agreement.seller and mandate.deal using the canonical identity frame and both schemes. Buyer filings carry receipt concurrence; seller filings remain cause=payee with no seller stop/reverse. Verify automatic receipt-backed payer claims, matching later concurrence, signature/digest/claim mismatch, missing/chosen payer entries, pre-start times and repeat mechanical rulings going to operators. Preserve notice/treatment and net accepted/pending/lost-response stops. Qualify cause=payee returned stops, held earnings, unserved non-setup once shares and capped penalty; cause=payer keeps non-setup once and pays no penalty; setup returns iff delivered=false in either cause. Only authority applies effects. Keep semantic filing/adoption identity; prior mechanical rulings force revision to operator, with prior effects resolved/netted before additional remedies.
      Qualified all 14 producer ruling traces through both the client and lifecycle
      dispatch, with the vector-derived replay fake and shared PaymentsAuthority.
      Canonical signed records, receipts, payment events, per-call snapshots and
      final state match exactly, including pending/scheduled stops, operator netting
      and lost-response recovery. The adapter maps claims and attaches verified
      receipt concurrence; only the authority sends payment effects. Both claim
      signature schemes reproduce the published frames. The 40 library-integration
      cases, model drift, mypy, architecture, packaging, comment hygiene and pinned
      strict OpenSpec checks pass, including installed-wheel replay of the 2.3 MB
      vector resource. No SettlementOption reader changed and no live qualification
      is claimed. Reproduction and boundaries:
      `docs/attachments/agreed-evidence-mediation/index.md`.
- [x] 12.4 Add the adapter/client respondent read for GET /respondent?after=<cursor>&limit=n, its cases/next_after/has_more result and cursor persistence. In kit/deal-servicing poll each accepted authority with seller credentials: journal an exact SignedDeliveryEndClaim when ended_at/delivered/cause match durable available/end records, otherwise contesting items; append as mandate.to with stable key before advancing cursor. Any append answers the listing; restart must not lose an answer. Dead/non-SCM respondents stay triaged without a silence default. Verify unanswered/restart/append-close races and signed ruling basis values.
- [x] 12.5 In lifecycle receipt construction (13.1/13.3), embed the self-contained SignedDeliveryEndClaim(cause=payer, delivered=true) at durable receipt time. Same-key retries keep identical claim/proof; the buyer half (7.5) verifies and preserves it for Filing.concurrence. Verify a real shipped receipt against both canonical signature vectors and the adapter; no standalone end_acknowledgement claim or competing frame.

Verification point: `kit/arkhai-mediation` unit and library-integration suites; `make
check-architecture`; `make check-packaging`; `make test`. End-to-end: none; live mediation is not
reachable from public CI.

## 13. Lifecycle routes and seller budget diagnostics

Delivers the storefront's lifecycle routes (seller `submit`, `read`, `list` under the
administrator principal; buyer `commit` and `hint` as the negotiation's buyer, signed responses)
and seller budget diagnostics. Implements D6 (routes) and D8 (seller budget), and the requirements
"Lifecycle routes are authenticated per role" and "Term values agree with the Agreement and the
seller's budget". Files: `kit/deal-servicing` (router factory),
`kit/deal-lifecycle-contracts` (route contracts), `kit/storefront` composition.

- [x] 13.1 Implement the routes as a router factory the storefronts mount, never relaying a
      buyer's authority command. Sign end_delivery responses using kit/identity v2 under
      the Agreement's seller principal; consume 2.4's neutral binding/verifier, never host a
      verifier buyer/dispute kits must import from servicing. Verify application-integration
      through the typed client for authentication, signature binding and relay refusal.
- [x] 13.2 Emit seller diagnostics when reserve-ahead or payer notice does not cover the configured
      polling/watchdog/teardown budget; these are recommendations, not codec/publication refusals.
      Warn on runtime shortfall and never stop lifecycle loops. Verify the budget diagnostic
      and continued-loop scenarios.

- [x] 13.3 Serve `end_delivery` directly as the accepted buyer's peer message, keyed by
      negotiation ID, without an authority read; reject supplied at (past or future) and
      outside-settlement stages. Record own durable receipt; no billing stop is sent;
      same-key retry retains receipt. Return signed acknowledgement with cause/source/progress;
      expose stored site-signed reports verbatim on the buyer-authenticated lifecycle read.
      Files: `kit/deal-servicing` router and `kit/deal-lifecycle-contracts`; gate: sections 2.4
      and 10.5. Verify: application-integration targets through the canonical typed client for
      wrong buyer, first-request backdating, supplied future at, introduction refusal,
      payment outage at receipt, before-fulfillment end, same-key retry during
      teardown and access control on exact report bytes. No buyer authority-command relay.

Verification point: application-integration suites; `make test`. End-to-end: none.

### Sections 12–13 result

Signed role-authenticated routes, non-gating diagnostics, receipt-time surrender and exact
owner-only report reads are implemented. Respondent discovery precedes watch and
journals sign-or-contest answers. Receipts embed adapter-owned claims; buyer recovery
resolves uncertain surrender before fixing a filing and separates authority/delivery
progress. Full tests (7m54s), typing and package/document gates passed.
Setup: `docs/attachments/lifecycle-routes/index.md` and
`docs/attachments/agreed-evidence-mediation/index.md`.
Promotion: lifecycle/buyer-orchestration; rate execution is deferred.

## 14. VM wiring

Delivers the VM storefront's composition of the seller half, evidence store and `watch`, its
entitlement-aware admin interrupt route, terminal settlement and delivery admission through end service, and
second-precision lease ends. Implements D8 for VM and the requirements "Lifecycle servicing is
composed by the compute domains" (VM), "The earliest final request governs delivery admission"
(VM paths), vm-storefront-fulfillment's "Full settlement convergence ownership" and "VM lease ends
keep the requested instant", and market-composition's "Deals compose negotiate, settle, and
provision stages". Files: `domains/vms/storefront/src/market_storefront/`
(`settlement_composition.py` including `truncate_lease_for_terminal_settlement`,
`services/fulfillment_service.py`, `payment_settlement.py`, `controllers/admin_controller.py`,
`startup.py`), `domains/vms/domain` lease models.

- [x] 14.1 Compose the servicing kit, the hosted payment adapter and the mediation adapter in the
      VM storefront; enable seller envelope capture in the negotiation controllers. Verify:
      application-integration test that a hosted VM deal appears in `list` and its acceptance
      envelope is stored.
- [x] 14.2 Route terminal settlement and refund-driven ends through end service, and order
      delivery start and reconciliation against the earliest final request. Verify:
      application-integration tests through the typed client with kit-owned vector-derived in-process payments and mediation
      contract fakes (no runnable tooling dependency) for "A seller's hardware fails", "A buyer tears down" scenarios in the VM
      delta, and the admission scenarios on the VM path.
- [x] 14.3 Keep the requested instant in VM lease ends (second precision). Verify: unit and
      integration tests in the VM fulfillment suites for the delta's scenarios.
- [x] 14.4 Route admin interrupts through the seller half: submit notice stop when the accepted
      option grants the payee an entitlement, otherwise journal delivery end and file
      delivery_end(cause=payee) through the dispute adapter. Keep administrator
      identity and reason. Verify both branches: authority notice governs entitled delivery end;
      without entitlement end service drives delivery immediately and the filing retries independently.

- [x] 14.5 Mount the peer end/read route and authenticated site-report receiver in the VM
      storefront; terminate now through `terminate_vm_lease`/hold release, not a watchdog kick.
      Add the VM buyer end verb through the buyer half and canonical client. Files:
      `domains/vms/storefront` fulfillment services, callback/router composition and startup;
      `domains/vms/buyer` command and stage composition. Gates: sections 7.5, 10.6 and 13.3.
      Verify: VM application-integration targets with real persistence for accepted-site
      signature checks, duplicate callback, end before provisioning and teardown progress;
      buyer application-integration targets for canonical client dispatch and evidence capture.
      Extend `e2e_deal`/`e2e_deal_buyer_cli` buyer-end stages to read signed site bytes and await
      proven capacity release, readiness-gated through the existing lane tooling.
  - [x] 14.5a Application wiring: mount and authenticate site reports, recover through
        the signed typed lease read, retain exact proof and connect capacity-return
        callback progress. Preserve immediate physical dispatch from 14.2.
  - [x] 14.5b Buyer wiring: compose retained evidence and the buyer half/client, use
        canonical commit for hosted settlement, and expose receipt-time `market end`
        with separate financial, receipt, case and proven-capacity progress.
  - [x] 14.5c End-to-end wiring/qualification: extend the VM end/report stages in
        `e2e_deal` and `e2e_deal_buyer_cli`; run the fresh branch-built stack through
        the Podman shim with real local payments and mediation. Keep 14.5 unchecked
        until this acceptance boundary is observed; 7.4 remains parent-owned.
  - [x] 14.5d Failure-source continuation: classify verified VM site evidence against
        accepted timing and recorded physical commands, correlate lawful ends, re-drive
        pending correction slots in the same journal, and route committed-deal failure
        release through end service. Files: `end_classification.py`, `deal_lifecycle.py`,
        `delivery_lifecycle.py` and `failure_actions.py` under the VM storefront.
        Verify with the existing VM regressions and committed first-use encounters for
        delayed lawful evidence, signed withdrawal, direct failure-policy dispatch and
        callback-only delivered-capacity progress. Deployed end/report acceptance stays
        in 14.5c; no rate/funding-timer classification is claimed.

Verification point: the VM storefront's unit and application-integration suites; `make test`.
End-to-end: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_vm_introduction` must keep passing;
the first two gain delivery-only end/report stages, not hosted rate-part stop qualification.

### Section 14 result and qualification

VM composition binds acceptance evidence, verified commitments, adapters and authenticated
routes. Admission gates reserve/dispatch/activation/disclosure; terminal/refund/failure
ends share the journal and terminate now. Administrator dispatch follows accepted rights,
otherwise records its attributed end before independent teardown/filing. Site push/pull
retains proof; only capacity-return proof reports released. `market end --from <run>`
keeps receipt/current-delivery and payment/case progress distinct. Seconds are preserved.
Setup and focused evidence:
- `docs/attachments/vm-lifecycle-wiring/index.md`
- `docs/attachments/vm-end-admission/index.md`
- `docs/attachments/vm-admin-interrupt/index.md`
- `docs/attachments/vm-site-report/index.md`
- `docs/attachments/vm-end-classification/index.md`

Fresh images at `5874088d1`, empty owned volumes and real local payments/mediation
passed readiness. VM deal 38/38 and CLI deal 30/30 passed with zero skips; both retain
lease-expiry checks and add repeated surrender, signed report before teardown completion
and callback-only capacity return. These Alkahest journeys qualify delivery, not rate or
ruling execution. Full tests passed in 7m19s; harness 316 and package/document gates
passed. All owned deployments were removed. 14.5 and 7.4 are complete.
Promotion: lifecycle, VM fulfillment and buyer orchestration.

## 15. Bare-metal wiring

Delivers the bare-metal storefront's composition and its teardown and terminal settlement
through end service, with delivery admission ordered against the end. Implements D8 for bare metal
and the bare-metal half of the section 14 requirements, including "A buyer tears down bare metal".
Files: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` (`api.py`
`teardown_fulfillment`, `fulfillment_service.py`, `settlement_stages.py`,
`settlement_composition.py`, `sqlite_client.py` refund intent).

- [x] 15.1 Compose the servicing kit and adapters, route teardown and terminal settlement through
      end service, and order admission against the end. Verify: application-integration tests
      for "A buyer tears down bare metal" and the admission scenarios on the bare-metal path.

- [x] 15.2 Fold the buyer teardown route into `end_delivery` and move `market bare-metal
      teardown` from its domain-only transport to the canonical lifecycle client through the
      buyer half. Retire the unbegun-fulfillment refusal: release undelivered holds, or adopt
      dispatched fulfillment and terminate. Mount accepted-site report receipt and lifecycle
      read exactly as for VM. Files: `domains/bare_metal/storefront` API, fulfillment service
      and composition; `domains/bare_metal/buyer` teardown command and transport; gates:
      sections 7.5, 10.6 and 13.3. Verify: bare-metal application-integration targets for wrong
      buyer/site, before-dispatch and create-in-flight ends, repeated teardown and exact report
      reads. Extend existing `e2e_bare_metal_mock_deal`/`e2e_bare_metal_deal` teardown stages to
      use the shared client, retrieve the signed end report and distinguish it from proven
      access revocation/capacity return. Rate stop/case scenarios wait for the rate adapter.

Verification point: the bare-metal storefront's unit and application-integration suites;
`make test`. End-to-end: `e2e_bare_metal_deal` and `e2e_bare_metal_mock_deal` (teardown path)
must keep passing.

### Section 15 result and qualification

Bare metal composes the same end/admission/evidence services. In-flight reserve/create
is adopted before termination; physical recovery rotates bounded pages independently
of hosted publication. Approval fixes commitment atomically; disclosure rechecks admission.
Canonical commit/teardown and accepted-site signed push/pull keep delivery and proven
release distinct. Recovery uses retained terms, not current admission policy.
Setup, first-use race modes and exact deployed revisions:
`docs/attachments/bare-metal-lifecycle/index.md`.
Fresh owned mock-provisioned stack and real local authorities passed readiness:
mock deal 39 stages and hosted payment deal 3 stages, zero skips; full tests/package
gates passed. All owned resources were removed. No real host was available; rate-stop
and ruling execution are deferred. 15.1/15.2 and 7.4 are complete.
Promotion: lifecycle, buyer-orchestration, physical-provisioning and site-capacity.

## 16. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits
documentation only; a part needing code returns the change to implementation.

- [x] 16.1 **Comment hygiene.** Run `make check-comment-hygiene` and read the comments the change
      added for provenance; anything found returns the change to implementation.
- [x] 16.2 **Import placement.** Confirm the imports each section added are at module level
      unless a recorded reason keeps one local; one that should move returns the change to
      implementation.
- [x] 16.3 **Documentation compliance.** Re-check D1–D15 against the placement rules, in
      particular that the dispute authority's and payments service's behaviour appears only as
      context in `deal-lifecycle/architecture.md` ("External authorities"), not as SCM
      requirements.
- [x] 16.4 **Narrative compression.** Compress completed-task notes to final behaviour, evidence,
      deferred work and destinations.
- [x] 16.5 **Roadmap currency.** Update Goals 6 and 8's current state and remove or mark landed
      this change's post-commitment lifecycle and buyer-end/report gaps in
      `docs/development/ROADMAP.md`; name both updates in the promotion record.
- [x] 16.6 **Campaign index currency.** Update this change's row in `openspec/changes/README.md`
      and the campaign graph (`spot-deals-through-arkhai-payments`, `move-settle-out-of-core`,
      `automate-seller-spot` build on it), including the folded buyer-end/report boundary and
      its delivery/deadline dependents; run `make check-change-index`.
- [x] 16.7 **Packaging.** Run `make check-packaging` and `make
      check-architecture-change CHANGE=agreed-evidence-and-early-termination` and resolve every
      failure; no architecture exception row may remain owned by this change.
- [x] 16.8 **End-to-end pipeline.** Record the pipeline run, its result, and that `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_non_erc20_settlement` and `e2e_credits_payment_deal` passed or were readiness-gated;
      record buyer delivery-only ends, site-report retrieval and subsequent proven capacity return
      in the existing compute scenarios. The hosted rate lifecycle e2e is owned by
      `activate-per-period-compute-servicing`, with convergence owning consuming servicing scenarios
      and in-lane double evidence labelled separately
      from hosted qualification.
- [x] 16.9 **Promotion.** Write the permanent documents and the design-promotion record:
      `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Authority
      boundaries" with D4's independent per-deal authority and D6's counterpart table, "Kit
      areas", "Registry self-description", major flows); `docs/development/ARCHITECTURE.toml`;
      new capability companion `deal-lifecycle/architecture.md` under `openspec/specs/`
      (D5–D10 rationale, "External authorities", from this change's `design.md`) and its `openspec/specs/README.md` index entries; companions
      `settlement-servicing/architecture.md` ("Capacity coupling", "Current limits",
      "Charge-first payment settlement"), `storefront-publication/architecture.md` ("Arkhai
      payment options"), `deployment-state/architecture.md`, `test-compatibility/architecture.md`,
      `buyer-orchestration/architecture.md` (canonical end verbs and stop-or-case evidence),
      `physical-provisioning/architecture.md` and `site-capacity/architecture.md` (intended end,
      outbox, pull recovery, immediate termination versus future truncation and separate
      capacity release), and `api-credits/architecture.md` ("Payment
      composition and recovery"); `docs/development/DEPLOYMENT_AND_CONFIG.md` (seller budget
      diagnostics, beside sections 3 and 4's entries). The archive writes the delta-covered
      `spec.md` files: `deal-lifecycle` (new), `buyer-orchestration`, `cli-query-language`,
      `deployment-state`, `market-composition`, `negotiation-protocol`, `registry-discovery`,
      `settlement-configuration`, `settlement-servicing`, `storefront-publication`,
      `test-compatibility`, `vm-storefront-fulfillment`, `physical-provisioning`, `site-capacity`.
      Update `ARCHITECTURE.md`'s "Site authority", "Fulfillment status and results" and "Release"
      to distinguish intended-end reports from the capacity-released callback. Promote D8's
      retained attribution and one delivery instant, and D9's site-report retention, into
      `deal-lifecycle/spec.md` and its architecture companion; no core financial-end record.
- [x] 16.10 **Documentation citations.** Run `make check-doc-citations
      CHANGE=agreed-evidence-and-early-termination` and resolve every match; then
      `openspec validate agreed-evidence-and-early-termination --strict`.
- [x] 16.11 **Archival.** `openspec archive agreed-evidence-and-early-termination -y`, merging the
      deltas; link the index row to the archive.

## Implementation review 19/20 disposition — domain

| Finding | Final disposition |
|---|---|
| S-F2 / O-F7 | `9061c2062`, `171b08a6a`: shared compute classification correlates release/termination/truncation and preserves controlling evidence; ambiguity stays pending. |
| S-F3 | `2ca4537c7`: retained mandate/ownership drives bare-metal recovery, not current admission policy. |
| O-F8 | `6172aaac0`: opaque accepted accounts map to Agreement principals and pinned dispute signer. |
| O-F9 | `d9e4ddfa2`: both watches compose retention eligibility from payout/case/recovery; no production prune trigger. |
| O-F16 | `ba051e273`, `d125afb02`: unchanged cycles avoid admission churn; post-release full history reconciliation retires polling. |
| O-F17 | `b905dacdd`: callback-proven release comment. |
| O-F1 domain | `83e899ebb`: permanent CI tests cover acceptance/list, admission/end races, admin dispatch, signed ingress/capture and proven release. Local end precedes independent teardown/filing. |
| O-F18 | `eac70ec3d`: fresh hosted VM commit/replay/servicing/end-case/refund/release, 4 stages passed, zero skips. Initial missing mediation history permits first filing only. |

Focused/full suites and package/document gates passed. Setup and regression sensitivity:
`docs/attachments/aeet-review-domain-repairs/index.md`,
`docs/attachments/aeet-domain-permanent-tests/index.md`,
`docs/attachments/aeet-vm-hosted/index.md`.
Once-only qualification is not rate/ruling-execution or real-host qualification.

## Closeout validation

- 16.1: `make check-comment-hygiene` passes on the closeout base `64f647d53`.
  Reviewed added production comments and docstrings against the implementation
  diff from `c7dd275c5`; they describe current invariants, not change provenance.
  No code edit is needed or made by closeout.

- 16.2: AST/diff inspection finds one added function-local production import:
  `alkahest_option_builder` imports `release_conditions` after configuration
  initialization. The latter imports `AlkahestSettlementConfig` and constants
  from `settlement_config`; module-level relocation would close that cycle.
  Its local rationale is explicit. Other added production imports are at module
  level; implementation review and the full-suite evidence cover execution.
  No import relocation is needed at documentation-only closeout.

- 16.3: D1–D15 placement checked against `openspec/README.md` directly.
  The lifecycle delta now states SCM's observation, derivation, signing and
  delegation obligations rather than prescribing external mediation remedies.
  External hold/ruling policy is contextual material for the lifecycle companion.
  D1–D4/D12–D14 cross-system boundaries belong in repository architecture;
  D5–D10 models and limits in lifecycle architecture and owning subsystem deltas;
  D11 triage is external context; D15 scope/deferrals remain change history plus
  current limitations. Deployment choices belong in the configuration guide;
  rollout chronology, rejected alternatives and review rationale remain in design.
  No external service implementation or SCM code is changed.

- 16.4: completed checkpoint/disposition narratives compressed; evidence packets,
  review IDs and final dispositions retained. Design keeps durable rationale and
  rejected alternatives; stale intermediate remaining-work lists are removed.
- 16.5: `docs/development/ROADMAP.md` Goals 6 and 8 now distinguish implemented
  once-only lifecycle/buyer-end/site-report work from rate/delivery/deadline and
  deployed qualification gaps. Known retention/cursor/domain/rotation limits remain
  explicit; API-credit dispute servicing remains unowned.

- 16.6: campaign row is `in closeout`; graph names the implemented folded
  buyer-end/report boundary, delivery/deadline consumers, settle extraction and
  seller automation. Dependency columns remain intact until archive cleanup.
  `make check-change-index` passes.

- 16.7: fresh-wheelhouse `make check-packaging` passes (lock/install/Python/
  layout and layer/scope/dependency/kind checks); `make check-architecture-change
  CHANGE=agreed-evidence-and-early-termination` confirms no owned exception or
  override. `make check-agent-skills` also passes. No package or code edit required.

- 16.8: full shim-backed `make test` passes in 7m55s on `0d861e80c` with
  ALL_PROXY/all_proxy unset and NO_PROXY/no_proxy limited to loopback. Includes
  package/application, harness unit, release-tooling and Helm checks (one existing
  optional RL skip). Deployed scenario results and real-host readiness gate,
  signed-report-before-teardown/proven-return evidence, reproduction and explicit
  unrun checks: `docs/attachments/aeet-closeout/index.md`. No new deployment or
  rate/ruling-execution qualification is claimed.

- 16.9: repository architecture, lifecycle companion and nine owning companions,
  configuration/testing guidance, capability index and promotion record are written.
  The record explicitly preserves D12/O-F7/O-F9/O-F4 and deployed qualification
  limits; normative delta synchronization remains exclusively 16.11. A direct
  path/link/heading audit over changed Markdown checks 385 references, all resolve.
  `make check-change` (including repository-pinned strict validation) and the
  installed seller `first-use` entry pass. No production code changes.

- 16.10: restored the design citations temporarily repointed by `0c86746f2` to
  `openspec/specs/deal-lifecycle/architecture.md` and replaced stale promotion
  status with the actual destinations. Scoped `make check-doc-citations` passes
  across 17 documents; unscoped passes across 448, with no exception or checker
  change. `openspec validate agreed-evidence-and-early-termination --strict`
  and repository-pinned strict validation pass. Final `make check-change`,
  architecture-change and fresh-wheelhouse packaging pass. Commented the result
  on [#325](https://github.com/arkhai-io/simple-compute-market/issues/325#issuecomment-6587134575).
  Three small documentation repairs were committed separately: `fafa9d1c0`
  corrects the pending-end filing README; `54948d61e` shortens four overlong
  requirement summaries without dropping obligations; `e5497f1c4` distinguishes
  external/generated/planned paths from branch-file citations. The required
  tracker reader failed before GitHub backend selection; repository-native `gh`
  succeeds and unresolved tooling friction is filed as
  [#329](https://github.com/arkhai-io/simple-compute-market/issues/329).
- 16.11 then ran in `87e978790`, after owner review: the change is archived with its
  deltas synchronized into `openspec/specs/`.

## Design promotion record

Architecture/configuration/index promotion is written on this branch. Permanent
prose describes the implemented system, with external monetary policy contextual
rather than prescribed as SCM behavior. The fourteen delta-covered normative
specifications were synchronized by the 16.11 archive, not merged by hand.
In particular, the new capability's normative `openspec/specs/deal-lifecycle/spec.md`
was generated from the change's `specs/deal-lifecycle/spec.md` at archival, and the
capability index links it beside the architecture companion.

| Accepted decision | Permanent location |
|---|---|
| D1–D3 protocol ends at mechanism commitment; exact derivation and later evidence | `docs/development/ARCHITECTURE.md#composition-from-above-and-below`; `openspec/specs/deal-lifecycle/architecture.md#commitment-and-authority`; buyer-orchestration delta |
| D4 independent per-deal authority, full identity/params admission and registry-specific consent | `docs/development/ARCHITECTURE.md#authority-boundaries`, `#registry-self-description`; `openspec/specs/deal-lifecycle/architecture.md#commitment-and-authority`; negotiation-protocol, registry-discovery and settlement-configuration deltas |
| D5 option price/settlement/lifecycle envelope, canonical identity, same-option query projections, per-part events, independent approval/hold windows and rights-derived authority/cap | `openspec/specs/deal-lifecycle/architecture.md#parts-and-terms`; `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement`; `openspec/specs/storefront-publication/architecture.md#arkhai-payment-options`; settlement-configuration, cli-query-language, negotiation-protocol and settlement-servicing deltas |
| D5 Alkahest release-model list and option-owned conditions; undeliverable model readiness blocker and explicit migration | `docs/development/DEPLOYMENT_AND_CONFIG.md#alkahest-release-models`; `docs/development/ARCHITECTURE.md` readiness boundary; settlement-configuration delta; `openspec/specs/settlement-configuration/architecture.md#readiness-publication-and-selection`; `openspec/specs/storefront-publication/architecture.md#settlement-option-reconciliation`; `openspec/specs/market-composition/architecture.md`. A configured section, enabled or not, listing a model its domain cannot deliver refuses startup, as implemented by `require_deliverable_release_models`; the closeout reviews' F1 reconciled the retained unready-only requirement, companions and guide that had said otherwise |
| D6 adapter/role boundaries, buyer-side and independent dispute kits, counterpart answer ownership | `docs/development/ARCHITECTURE.md#kit-areas`, `#post-commitment-counterparts`; `docs/development/ARCHITECTURE.toml` independent dispute registry/scope (existing enforcement retained); `openspec/specs/deal-lifecycle/architecture.md#package-and-counterpart-boundaries` |
| D7 verified authority records, separate cursors and current outcomes; pinned ruling actor and opaque account mapping | `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission`; `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement` |
| D8 one attributed delivery end, all sources retained, atomic admission/end/classification/filing journal, no core financial-end record | `openspec/specs/deal-lifecycle/architecture.md#one-end-instant-transactional-admission`; `openspec/specs/settlement-servicing/architecture.md#capacity-coupling`; deal-lifecycle and vm-storefront-fulfillment deltas |
| D8 receipt-time surrender, signed embedded claim, same-key recovery, canonical compute verbs and distinct payment/case progress | `openspec/specs/buyer-orchestration/architecture.md#delivery-only-ends-and-case-evidence`; `openspec/specs/deal-lifecycle/architecture.md#buyer-surrender-and-cases`; buyer-orchestration delta |
| D8 intended end before teardown, transactional event/outbox, original signed push/pull after signer changes, peer parking/resumption, terminate-now versus second-precision future truncate and separate proven return | `openspec/specs/site-capacity/architecture.md#intended-end-evidence`; `openspec/specs/physical-provisioning/architecture.md#lease-end-report-delivery`; `docs/development/ARCHITECTURE.md` Site authority/Fulfillment status and results/Release; site-capacity, physical-provisioning and vm-storefront-fulfillment deltas |
| D8 seller capacity budget diagnostics warn and continue, not a second payment term or buyer guarantee | `docs/development/DEPLOYMENT_AND_CONFIG.md#seller-servicing-budget-diagnostics` beside the settlement/dispute entries; current library inputs and absent role-level budget table stated explicitly |
| D9 exact acceptance/peer/site/authority bytes, three evidence classes and conservative frozen-window retention | `openspec/specs/deal-lifecycle/architecture.md#site-evidence-and-retention`; `openspec/specs/buyer-orchestration/architecture.md#delivery-only-ends-and-case-evidence`; `openspec/specs/deployment-state/architecture.md#lifecycle-state-and-coordinated-rollout`; deal-lifecycle delta |
| D10 original semantic filing ownership/adoption, fixed claims, one delivery_end for either filer, respondent sign-or-contest, setup treatment and capped held-earnings remedy | `openspec/specs/deal-lifecycle/architecture.md#buyer-surrender-and-cases`, `#external-authorities`; `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement`; deal-lifecycle and settlement-servicing deltas. Authority remedies are context only |
| D11 triage fallback; unsigned/contested/unanswered claims never rule by silence | `openspec/specs/deal-lifecycle/architecture.md#external-authorities` (external context), with SCM observation/delegation obligations in the deal-lifecycle delta |
| D12 adversarial buyer protection and accepted mid-deal dispute origin/key rotation limit | `docs/development/ARCHITECTURE.md#post-commitment-counterparts`; `openspec/specs/deal-lifecycle/architecture.md#current-limits`; `docs/development/DEPLOYMENT_AND_CONFIG.md#dispute-authority-preferences`; `openspec/specs/deployment-state/architecture.md#lifecycle-state-and-coordinated-rollout` |
| D13 neutral alternative, current Alkahest risk and absent specialized arbiter/adapter | `docs/development/ARCHITECTURE.md#post-commitment-counterparts`; `openspec/specs/deal-lifecycle/architecture.md#current-limits` |
| D14 information placement and compute commit versus API-credit settle | `docs/development/ARCHITECTURE.md#composition-from-above-and-below`; `openspec/specs/buyer-orchestration/architecture.md`; market-composition and buyer-orchestration deltas |
| D15 current scope and deferrals: no rate-stop/funding/ruling execution or real-host qualification, hosted-development mediation on an older revision, API credits compatible but not serviced | `openspec/specs/deal-lifecycle/architecture.md#current-limits`; `openspec/specs/settlement-servicing/architecture.md#current-limits`; `openspec/specs/api-credits/architecture.md#payment-composition-and-recovery`; `openspec/specs/test-compatibility/architecture.md#lifecycle-contract-evidence`; `docs/development/ROADMAP.md` Goals 6 and 8 |
| Ordered authority preferences/credentials and publication's registry-list intersection | `docs/development/DEPLOYMENT_AND_CONFIG.md#dispute-authority-preferences`; `openspec/specs/storefront-publication/architecture.md#arkhai-payment-options`; settlement-configuration and registry-discovery deltas |
| Verified snapshots and bounded current/retiring receipt pins; one shared clock-injected payment fixture engine and independent mediation vectors | `openspec/specs/settlement-servicing/architecture.md#charge-first-payment-settlement`; `openspec/specs/test-compatibility/architecture.md#lifecycle-contract-evidence`; `docs/development/TESTING.md#payment-receipts-in-tests`; existing deployment receipt-identity guide and payment/mediation kit READMEs |
| Verified-evidence transaction fixes approval commitment once; bounded physical recovery independent of publication; accepted payee-right administrator dispatch | `openspec/specs/vm-storefront-fulfillment/architecture.md#delivery-end-and-post-release-history`; deal-lifecycle and vm-storefront-fulfillment deltas |
| S-N3 full post-release history marker: nonempty read fully ingested after proven release, checked across restart | `openspec/specs/vm-storefront-fulfillment/architecture.md#delivery-end-and-post-release-history` |
| O-F7 accepted respondent-lifetime and term-end composition differences; O-F9 no production prune trigger; O-F4 unresolved unanswered case holds its per-deal cursor | `openspec/specs/deal-lifecycle/architecture.md#current-limits`; `openspec/specs/settlement-servicing/architecture.md#current-limits`; VM fulfillment companion records the domain differences |
| Goal 6/Goal 8 current-state and gap ownership; campaign dependency gates remain until archival | `docs/development/ROADMAP.md` Goals 6 and 8; `openspec/changes/README.md` row and graph (16.5/16.6); `openspec/specs/README.md` capability/authority index |
| Published lifecycle distribution dependency order | Existing `docs/development/RELEASING.md` and `manifests/published-distributions.json`; packaging check passes without further edits |

Archive-owned normative destinations (all deltas already present under this change):
new deal-lifecycle capability, buyer-orchestration, cli-query-language,
deployment-state, market-composition, negotiation-protocol, registry-discovery,
settlement-configuration, settlement-servicing, storefront-publication,
test-compatibility, vm-storefront-fulfillment, physical-provisioning and site-capacity.
Each archive-generated `spec.md` receives its own delta, including D8 attribution
and D9 site-report retention. Companion promotion does not substitute for that merge.

## Implementation review 19/20 disposition — kits

| Finding | Final disposition |
|---|---|
| S-F1 / O-F2 | `33d777ba0`, `3531af8b0`, `15c0d39f8`: durable original writer, one signed equivalent case, correlated failure echoes; E-N1 makes unresolved ownership retryable. Unsupported/ambiguous revisions require repair. |
| S-F4 / S-F5 | `f0b7f5ce2`: current outcomes separate from verified history; full-snapshot floors include empty records. |
| O-F3 / O-F4 / O-F8 / O-F10 | `243ed8c51`: respondent owns answers; local repairs retry fairly, ruling actor is pinned signer, unlocked authority I/O precedes off-loop CAS/local writes. Per-deal dispute cursor still holds at unresolvable unanswered cases. |
| O-F5 / O-F6 | `ac139c842`, `3531af8b0`: resolve uncertain surrender before filing; only selected surrender concurs or auto-files. |
| O-F9 | `8bb7bb8eb`: complete payout projection, conservative observer, refresh-before-prune API; no production storefront pruning trigger. |
| O-F11 | `3531af8b0`: terminal refusal/per-filing progress survive restart. |
| O-F12 | `eccc87ea1`, `d65e98e86`, `1d713730c`: adapter-owned credential-independent claims and schema-free ingress binding reads. |
| O-F13 | `211e29f7b`: unused duplicate helpers removed; real public-surface assertions retained. |
| O-F14 / O-F15 | `3531af8b0`: fixed Agreement-start non-delivery basis; validate before consuming key. |
| O-F16 | `cf580bb6f`: unchanged admission does not write revision. |
| O-F1 kits | `4510feb50`, `299adfd7c`, `ac139c842`: permanent servicing/client tests in aggregates; first-use outcomes assert. |

Regression sensitivity, typing, package/document gates and full tests passed (combined
chain 7m41s; parallel integration `1d713730c` 7m26s). Reproduction:
`docs/attachments/aeet-servicing-review-fixes/index.md`,
`docs/attachments/aeet-review-19-20-fix-a/index.md`,
`docs/attachments/aeet-fix-a-integration/index.md`.
Current API: `kit/deal-servicing/README.md`; review rationale is in design.

## Re-review 21/22 disposition

| Finding | Final disposition |
|---|---|
| S-N1 | `e7113a1ca`: lazy buyer ports forward case adoption without eager credentials; reconstructed real-port recovery retains one case. |
| S-N2 / E-N6 | `746b51c7e`, `18e7f42df`: validate/adopt controlling classification/filing in the same journal without rewriting source. |
| E-N1 | `5e8d291fe`: unresolved original writer is pending, not terminal rejected. |
| E-N2 | Classified selected ends suppress later unnecessary filings; pending-source exception is N1 below. Earlier late evidence can require an unsupported revision. |
| E-N3 / O-F6 | `2833b79ee`: contest payer claim over superseded surrender. |
| E-N5 | `b6c30ef80`: skip foreign commitments; rotate local repairs fairly. |
| E-N7 | `772ee3327`: operator reports its own filing, one diagnostic prefix, receipt-backed buyer recovery without unreachable fields. |
| S-N3 / O-F16 | `d125afb02`: successful nonempty post-release full history read and durable marker retire VM polling; a partial push cannot certify completeness. |
| E-N4 / O-F10 | `233fbfb6d`: ingress/cycles/local end/registration database units off-loop; borrowed sessions remain synchronous; N2 completes capture. |
| O-F7 | `fd6fe6d53`: shared compute command/request matching, pending correction and actor policy. Respondent lifetime and term-end differences remain promotion limits. |
| S-N4 / O-F1 | `66a824ee1`: CI producer tests prove atomic rollback/dedup, all causes, crash/lost ack, exact signed push/pull after rotation, parking/reconfiguration/resumption. |

Fixture recursion was repaired separately in `908323b2e`, then service integration 458
passed. Combined `0143c1ea9` validation: full tests 7m27s, kit typing and all package/document
gates; compute 14, VM 1196 unit (one optional RL skip)/523 integration, bare-metal
storefront 540, service 607 unit/458 integration. Reproduction:
`docs/attachments/aeet-fix2-kit-buyer/index.md`,
`docs/attachments/aeet-rereview-domain/index.md`.
No standalone domain mypy or hosted requalification is claimed by these repairs.

## Confirmation review 23 disposition — N1–N3

`fd85d9873` fixes all three findings; each retained regression fails on the reviewed
source and passes after repair:
- N1: only classified selected ends suppress later seller filings; pending site evidence
  retains the filing in both arrival orders, with replay/read visibility.
- N2: VM capture uses the database-worker transaction boundary; busy-writer regression
  preserves event-loop progress, both envelopes and accepted expiry.
- N3: cycle fixture mirrors the producer's `release_failed` cause.

Servicing 63 plus typing and focused VM 28 passed. Package/document gates passed.
Full shim-backed tests at `fd85d9873` passed in 7m54s: VM 1196 unit (one optional skip)/524
integration, kit typing, provisioning/domains, release tooling and Helm checks.
Setup and sensitivity evidence: `docs/attachments/aeet-fix3/index.md`.
No hosted deployment was rerun. Pending-source/worker rationale is recorded in
`openspec/specs/deal-lifecycle/architecture.md` and the servicing companion;
no authority or remedy policy is added.

## Closeout review 24/25 disposition

Reviews 24 (internal) and 25 (external) read the archive at `87e978790`. Their
findings were answered by a documentation reconciliation on this branch with no
behaviour change; the two API-credit comments the owner authorized are the only code
edits. Whether the change advances to archive cleanup is the triage owner's decision
and is not recorded here.

| Finding | Disposition |
|---|---|
| 24 F1 / 25 F1 (blocking) — undeliverable release model: unready versus startup refusal | Fixed. The implemented refusal (`require_deliverable_release_models`, enabled or not) is the one contract: the unready-only requirement and its disabled-section scenario no longer cover release models, an explicit refusal scenario is added, and `storefront-publication/spec.md`, the settlement-configuration, storefront-publication and market-composition companions, `DEPLOYMENT_AND_CONFIG.md`, `ROADMAP.md`, the bare-metal quickstart and the D5 promotion row now say so. The API-credit startup and composition comments describe the refusal |
| 24 F2 / 25 F7 — task number and past-event condition in the lifecycle spec | Fixed. The delivery-end requirement cites the mediation kit's vendored contract and `kit/arkhai-mediation/schema/SOURCE.md`; the setup-preset gate states the current qualification condition |
| 25 F2 — refund scenario contradicts the opt-in refund failure action | Fixed. The scenario permits `reverse` only for a seller-authenticated request or the enabled pre-delivery refund action, and again refuses a buyer-triggered reverse |
| 25 F3 — scenarios prescribing external authorities' outcomes | Fixed. Lifecycle and servicing scenarios state what SCM files, preserves, sends or observes; the penalty-cap and never-delivered rate arithmetic is kept as context in `deal-lifecycle/architecture.md#external-authorities` |
| 25 F4 — ROADMAP says not yet archived | Fixed in Goal 8's current state. The Goal 6 and Goal 8 "in closeout" gap rows stay accurate until triage; archive cleanup must mark them landed when the index row becomes `archived`, since the index procedure does not cover ROADMAP |
| 25 F5 — deployed lanes predate the review 19–23 repairs | Rerun on fresh images built from `87e978790`, after the review 19–23 repairs, with no skips; recorded in `docs/attachments/aeet-final-qualification/index.md`; later commits are documentation-only |
| 25 F6 — `converge-ongoing-compute-leases` would drop the rejected-filing rule | Recorded in that change's index row; its delta is not rewritten here. Its design reverification owes the clause and both omitted scenarios |
| 25 F8 — records still say archival is withheld | Fixed by appended notes in 16.10, the closeout packet's scope section and the design Status |
| 25 F9 — vacuous "The full policy is enforced" scenarios | Fixed rather than left for `shorten-long-requirements`: each restated-requirement scenario (nineteen, counting THENs that restate the requirement under another title) is replaced by a concrete case, overflow obligations move to separately named requirements under 500 characters, and original headings are kept. `spot-deals-through-arkhai-payments` and `unify-compute-delivery-path` MODIFY two of those requirements; their index rows note the split |
| 25 F10 — no pre-closeout review or 19–23 triage records | Recorded: no `NN-pre-closeout.md`, `NN-validation.md` or 19–23 `.triage.md` exists. The pre-closeout review and merge step were replaced by reviews 19–23 and the disposition sections above, and the branch integrates onto `goal-8-implementation-basis` rather than through the workflow's merge step. No earlier triage record is reconstructed |
