# Tasks — agreed evidence and early termination

Reconciled design-stage plan, updated 2026-10-29 after triage of reviews 17 and 18.
No implementation is implied by unchecked tasks. Depends on no open
change for design or planning. Implementation depends on two external contracts (design.md,
"Dependencies on the hosted payments service"): the published payments partialPeriod contract revision, ready to vendor at 8.1
(hold extensions, per-part start/stop and authorities with notice
durations, per-part `end` and `afterStop` holds, one re-vendor) gates section 8, and the `arkhai.mediation.v1`
contract gates live use of section 12's adapter but not its implementation against the test
double.

Sections follow the design's implementation cadence. Sections 1–7 are round 1 (foundation,
wire and buyer side), except 7.5's explicitly round-2 end verification; section 8 joins round 1 once its schema and vectors are vendored
into `kit/arkhai-payments/schema/`. The per-part lifecycle revision is published;
including `partialPeriod`; the setup part is an ordinary once part and needs no further contract confirmation. The exact producer revision is recorded only in schema/SOURCE.md at 8.1.
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
13.1 only signs storefront responses. Mediation mechanically rules only qualifying seller self-penalties; section 7.5 runs in round 2
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
these early-end scenarios. Archive this foundation first, renewable before unify, and unify before redesign-authenticated-requests;
their later MODIFIED requirements must preserve every foundation clause and scenario
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

- [ ] 1.1 Add the buyer-side area and the dispute-kit kind to `ARCHITECTURE.toml`: a
      `[[disputes]]` table registering each dispute interface and its kit beside
      `[[mechanisms]]`, with no row yet (section 12 adds `arkhai.mediation.v1`), and the
      buyer-side area's dependency rule (foundation libraries and contracts only; composed by
      buyers, never by a storefront or a site). Verify: `make check-architecture` passes on
      the unchanged tree.
- [ ] 1.2 Teach `scripts/architecture.py` the table: load `[[disputes]]`, grant each interface
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

- [ ] 2.1 Create `kit/deal-lifecycle-contracts` (contracts kind): commands
      `{negotiation_id, kind, operation_key, at, payload}`, outcomes (`accepted`, `rejected`,
      `pending`, `unknown`), per-part payment events including `extend` and `lift` with
      `extension_ref` and `case_ref`, per-agreement dispute events, the filing answer with
      per-part `held` / `not_held` and reason, peer messages `commit` and `hint`, the case
      payload, evidence items, and route contracts and response models for section 13. Wire it
      into the build, `.dist` and locks. Verify: unit tests round-trip each model and refuse
      unknown kinds; `make check-packaging`.
- [ ] 2.2 Create `kit/deal-lifecycle` (foundation library, on the contracts) with the term codec
      for `adjudication` (`dispute` as `{interface, origin, account, record_key, params}`),
      `early_termination` (no `exposure_seconds`; entitlements' and term end's `settles_through`
      values and `partialPeriod` mapping per D5, plus nonnegative minor-unit decimal-string `premature_stop_penalty`, absent/zero meaning none), positive-integer `delivery_deadline_seconds` (the "Delivery has a deadline" semantics; the compute builders in `negotiate-open-ended-compute-terms` emit it from the pool's tag) and reserved `bond`; malformed and bounded-term refusal
      (`case_hold_max_seconds` a nonnegative integer or `null`, minimums from an authority's
      advertisement copy); and the semantics table. Verify: unit tests for each refusal in the
      "Malformed terms are refused" and "Dispute timing terms are bounded" scenarios (the window
      shorter than the delivery deadline plus the authority's minimum included), and that
      a term change changes the option ID through the existing option-ID function.
- [ ] 2.3 In `kit/deal-lifecycle`, define the payment-adapter and dispute-adapter protocols and
      their tables (payment by negotiation ID, mechanism and arbiter or oracle; dispute by
      `adjudication.dispute.interface`), injected by compositions; the deal-level dispute
      intents exceptional_end(at) (seller-filed, never a payments event kind or field) and
      buyer_end(at) (buyer-filed); derivation of each part's stop authorities from entitlements plus
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

- [ ] 2.4 Extend peer/route/read contracts with receipt-only end_delivery (no at), signed
      acknowledgement binding request identity, seller-recorded receipt, selected end,
      progress and verbatim site reports. In kit/deal-lifecycle implement the shared binding
      and verifier over kit/identity v2, usable by buyer/client/dispute kits without servicing
      dependency; 13.1 only signs. Include rejected authority view beside readable delivery
      when no adapter exists. Define buyer_end(at) as the buyer-filed and exceptional_end(at) as the seller-filed
      dispute intent, neither a payments event. Verify refusal of supplied at, receipt preservation on retry,
      Agreement-principal signature binding and exact report bytes. Gates 7, 10 and 13.
- [ ] 2.5 Reshape core's `SettlementOption` to `{option_id, price: {asset, rates}, settlement:
      {schema, ...}, lifecycle?}` per D5 ("The option's shape"), with the option ID the hash of
      the canonical payload of `price`, `settlement` and `lifecycle`, the last omitted when
      absent; move every builder (hosted, Alkahest, contact-exchange, API credits), the buyer's
      selection mirror and the registry carrier onto it, with no reader of the old `mechanism`,
      `asset`, `rates` or `params` keys left. Verify: each existing mechanism's deal
      negotiates, commits and is fulfilled under the new shape in its unit and
      application-integration suites; a client that does not recognize the shape refuses at
      selection, before approval or escrow funding, never during fulfillment; `e2e_deal`,
      `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` pass on republished listings.

Verification point: unit tests in both kits; `make check-packaging`; `make check-architecture`;
`make test`. End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal`
on the republished listings of 2.5; nothing composes the kits yet.

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

- [ ] 3.1 Add typed `[[Dispute]]` entries (identity, `params`, advertisement copy, not-offered
      and not-accepted marks), `[[DisputeCredential]]` bindings (identity and an
      environment-variable reference) and `use_registry_dispute_authorities` (default true for a storefront, false for a buyer;
      the shipped buyer profiles and fixtures set it explicitly) in
      `kit/deal-lifecycle`, with resolution of a role's ordered list from its entries and a
      supplied registry recommendation list. Verify: unit tests for ordering, marks, the
      opt-out, credential lookup by identity, and that resolved credentials never appear in a
      rendered option or status model.
- [ ] 3.2 Retire `[Settlement.arkhai_payments].dispute_authority`: validation rejects it with a
      diagnostic naming `[[Dispute]]`, and the VM buyer template loses its commented line.
      Verify: `kit/arkhai-payments/tests/test_settlement_config.py` covers "The retired dispute
      authority key is set"; a template-writer test per role asserts no `[[Dispute]]` entry and
      no authority account, origin or key ("A template is written").
- [ ] 3.3 Add the optional recommended-authorities list to the registry descriptor carrier and
      its operator configuration, built from configuration only, with Helm values and render
      checks. Verify: the descriptor unit and integration suites named in
      `openspec/specs/registry-discovery/spec.md` ("Strict descriptor carriers…") gain "An
      operator recommends an authority" and "A registry recommends none" (library integration
      against the real registry app); `helm/scripts/test-render.sh` passes with and without the
      list.
- [ ] 3.4 Fetch a registry's recommendations where roles already read its descriptor (buyer
      bootstrap and storefront publication), and report at startup when a role's list is empty.
      Verify: application-integration tests through the typed client: "A buyer uses its
      registry's recommendation", "A buyer has configured no authority" and the startup
      report of "No authority is available".
- [ ] 3.5 Document `[[Dispute]]`, `[[DisputeCredential]]`, `use_registry_dispute_authorities`,
      the descriptor list and the retired key in `docs/development/DEPLOYMENT_AND_CONFIG.md`.
      Verify: `make check-doc-citations CHANGE=agreed-evidence-and-early-termination` reports
      nothing for the section.

Verification point: unit suites of `kit/deal-lifecycle` and `kit/arkhai-payments`; the registry
descriptor suites (unit and library integration); the Helm render check; `make test`.
End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` must keep
passing (they start roles from rendered configuration); none exercises the new list.

## 4. Alkahest release models

Delivers `[Settlement.alkahest].release_models` in place of the two exclusive flags, one
Alkahest option per model, and the migration. Implements D5 ("Alkahest") and
settlement-configuration's "Alkahest release models are listed per option", "Explicit atomic
configuration migration" and "Each mechanism's option carries its own parameters". Files:
`kit/alkahest/src/market_alkahest/settlement_config.py`, `release_conditions.py`, the VM and
bare-metal storefronts' publication and migration modules
(`domains/vms/storefront/src/market_storefront/publication_migration.py`,
`settlement_composition.py`, and their bare-metal counterparts), `DEPLOYMENT_AND_CONFIG.md`.

- [ ] 4.1 Replace `oracle_gated` and `interruptible` with `release_models` drawn from
      `recipient`, `oracle_gated` and `interruptible`, validating oracle settings against the
      listed models. Verify: `kit/alkahest` unit tests for each model and each refusal.
- [ ] 4.2 Publish one Alkahest option per listed model in the VM and bare-metal storefronts, with
      no lifecycle terms (no Alkahest lifecycle adapter exists). Verify: application-integration
      test for `release_models = ["recipient", "interruptible"]` publishing two options without
      `adjudication` ("Builders emit terms only where they bind").
- [ ] 4.3 Extend the dry-run and write migration to map the old flags to `release_models` and
      remove them. Verify: migration unit tests for each flag and for both flags absent.
- [ ] 4.4 Document `release_models` in `DEPLOYMENT_AND_CONFIG.md`. Verify: doc citations check.

Verification point: `kit/alkahest` unit suites; both storefronts' integration suites; `make test`.
End-to-end: `e2e_deal`, `e2e_non_erc20_settlement` and `e2e_bare_metal_deal` exercise Alkahest
publication and settlement and must keep passing.

## 5. Common query fields

Delivers the lifecycle term projections as common settlement fields. Implements D5 ("Query
fields"), cli-query-language's "Settlement fields have common and mechanism-owned
namespaces" and settlement-configuration's "Mechanism clause fields stay in their namespace". Files: `core/src/market_core/query_dsl.py`,
`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`, the registry filter
specification and the buyer query client.

- [ ] 5.1 Reserve `adjudication.dispute.interface`, `adjudication.dispute.account`,
      `early_termination.payer`, `early_termination.payee` and
      `early_termination.payee.notice_seconds` and `early_termination.premature_stop_penalty`
      (absent zero, asset-correlated minor units) as common fields projected by the
      `kit/deal-lifecycle` codec. Verify: unit tests in `core/tests/unit/test_query_dsl.py` and
      the registry's filter tests; library-integration test in the registry for "A buyer asks
      for buyer-stoppable options" and "A lifecycle term is filtered".

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

- [ ] 6.1 Add the injected capture sink to production negotiation's _authenticated_json,
      propagate it through the public negotiation API, core orchestration and both compute
      buyer callers, and capture raw bytes/proof headers before decoding discards them.
      Exercise an actual negotiation acceptance reaching the store before payment approval,
      not just a StorefrontClient stub. Add the seam to other buyer verified responses and the
      storefront's verified-request path, carrying proof headers, exact body and verification
      context before parsed payloads are returned. Default to no capture so existing callers are
      unchanged. Verify: unit tests that the seam receives exact bytes for a verified response
      and request and nothing for a refused one ("The buyer's transport verifies an
      acceptance").
- [ ] 6.2 Create `kit/deal-lifecycle-buyer` (buyer-side area) with a file-backed evidence store
      under a root passed by the buyer composition beside the buyer profile, keyed by
      negotiation ID, keeping the seller's signed acceptance before `commit`. Verify: library
      integration test ("A buyer accepts").
- [ ] 6.3 Add retention and the prune command: lifecycle deals kept per "Evidence outlives the
      deal and its cases", reading each deal through an injected reader first and deleting
      nothing it cannot read; deals with no lifecycle terms or no adapter, including today's
      Alkahest deals, kept. Verify: unit tests for each retention scenario with a fake reader;
      "A buyer prunes"; "An Alkahest deal's envelopes are kept".
- [ ] 6.4 Add case export: one bundle with the commitment reference, terms, claim, requested
      outcome and ordered evidence items carrying exact bytes. Verify: unit test ("A buyer files
      a dispute" payload half).

Verification point: unit and library-integration suites of `kit/deal-lifecycle-buyer`; the
storefront-client and identity unit suites; `make check-architecture` (buyer-side area rule);
`make test`. End-to-end: `e2e_deal_buyer_cli` must keep passing with capture enabled in the
buyer CLI; none checks the stored envelopes.

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

- [ ] 7.1 Create `kit/deal-lifecycle-client` for the buyer `commit` and `hint` routes (section
      13 serves them), verifying signed responses. Verify: unit tests against recorded
      responses.
- [ ] 7.2 Implement the buyer half in `kit/deal-lifecycle-buyer`: payment commands to the payment
      adapter, `dispute` and `append` to the dispute adapter, outcomes reported as the
      counterpart's own, `read` merging payment events, open extensions and cases, `rejected`
      authority view for a mechanism with no adapter (delivery view remains readable), `hint`
      after a filing. Verify: library-integration tests
      with fake adapters for "A filed case requests a reverse", "The authority cannot complete an
      extension", "Parts differ", "A buyer reads a deal with no lifecycle adapter", "A buyer
      files after the window" and "A filing's response is lost".
- [ ] 7.3 Refuse options at selection whose authority fails exact identity match, whose
      interface has no adapter, or whose authority does not advertise the option's payment
      mechanism, and prefer options in list order. Verify: unit tests for "A seller pairs the
      real account with its own origin", "A buyer meets an authority it has not accepted", "A
      seller offers two dispute authorities" and "A buyer prefers one authority".
- [ ] 7.4 Compose the buyer half, its evidence store and the lifecycle client in the VM and
      bare-metal buyer stages; compute deals send `commit` after settlement instead of the seller
      settlement handoff where the mechanism has a lifecycle adapter, and Alkahest and API-credit
      paths are unchanged. Verify: application-integration tests through the typed client per
      domain that a hosted-mechanism deal stage reaches `commit` (with kit-owned vector-derived in-process payments and mediation contract fakes; no runnable tooling dependency)
      and an Alkahest deal stage is unchanged.

- [ ] 7.5 **Round 2, after 12.3 and 13.3:** add canonical client end_delivery(negotiation_id)
      and buyer-half end verification/capture. Round-1 dispatch remains fake-adapter work in 7.2.
      Stop at the payment authority first; on unknown/unreachable payments journal the stop and retry
      it under the same key (billing runs until it lands), send receipt-only surrender, and may also
      journal buyer_end(at) with retained request and any acknowledgement; use acknowledged
      receipt when available, otherwise contested observed time, never a seller-signed backdate.
      Retry unavailable filings. Once-only/no-adapter surrender invents no refund. Verify with injected adapters
      for payment outage, both authorities down, no acknowledgement, supplied at rejection,
      stable-key retry, and separate delivery/payment/case progress. No automatic ruling.
      Rate stop/hint, nonzero notice, lost-stop response and seller billing re-drive belong to
      spot; this task does not gate round 1 or require spot completion.

Verification point: unit and library-integration suites of the client and buyer kits; the VM and
bare-metal buyer application-integration suites; `make test`. End-to-end: `e2e_deal`,
`e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal` must keep passing; none exercises a hosted
lifecycle deal.

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

- [ ] 8.1 Derive seller stop entries only for entitlements (such as spot's notice entry), with
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
- [ ] 8.2 Derive each part's authorities and holds from the terms: prepaid `once` end at term end,
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
- [ ] 8.3 Extend the buyer's mandate check to the derived authorities, holds and dispute
      authority. Verify:
      `test_buyer.py` cases including the payee-as-stop-authority refusal.
- [ ] 8.4 Emit `adjudication` from the storefront's first offered authority advertising the
      option's mechanism (or one option per offered authority), publish nothing hosted with an
      empty list, and refuse incompatible authorities at publication, in the VM, bare-metal and
      API-credit storefronts; the API-credit buyer checks options against its list. Verify:
      application-integration tests per storefront for "An authority does not serve the payment
      mechanism", "A zero case hold is below the minimum", "No authority is available" and "An
      API-credit storefront publishes a hosted option".

Verification point: `kit/arkhai-payments` unit and vector suites; the three storefronts'
application-integration suites; `make check-packaging` (vendored schema); `make test`.
End-to-end: `e2e_credits_payment_deal` exercises hosted mandate derivation and approval; it is
readiness-gated on a payments target and is evidence only where one is reachable.

## 9. Snapshot-proof verification

Delivers verification of snapshot proofs before any snapshot state is read, ahead of `watch`.
Implements the design's dependency item "Snapshot-proof verification in SCM" and D12
(authority records verified). Files: `kit/arkhai-payments/src/market_arkhai_payments/receipts.py`,
`test-vectors/`, the receipt-kit fixture.

- [ ] 9.1 Verify snapshot proofs against configured current/retiring receipt identities with validity
      windows, embedded-receipt attestation and a caller-supplied minimum sequence; refuse
      unverified, cross-deal, mode-changed or regressing snapshots. Current-key snapshots may
      attest an embedded old receipt without discarding its original bytes.
      Verify: unit tests with a new snapshot vector and receipt-kit fixture for a valid,
      tampered and wrongly signed snapshot.

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

- [ ] 10.1 Create `kit/deal-servicing` with the storefront evidence store (seller envelopes on
      every acceptance path through the section 6 seam, administrator as author on
      administrative acceptance) and its retention. Verify: library-integration tests for "The
      seller accepts the buyer's opening", "An administrator accepts" and the retention
      scenarios.
- [ ] 10.2 Implement end service: earliest-wins final requests from authority, dispute and local
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
      and provisioning".
- [ ] 10.3 Implement `watch`: one durable cursor per record (payment authority, dispute
      authority), advancing after the effect is journaled; delivery ends to end service once per
      effect ID; a counterparty's case journaled as the seller's append with an idempotency key
      and skipped for a confirmed closed case; record entries verified against the Agreement's
      `record_key`; open extensions tracked per ref; a buyer's `commit` or `hint` kept as evidence
      and answered by a read, never by a state change. Verify: library-integration tests with fake
      adapters for every `watch` and append scenario of the deal-lifecycle delta, including
      "A ruling is read while partly applied", "Two cases overlap", "The storefront crashes
      before appending" and "A case is filed and closed while the storefront is down" and "A forged hint arrives".
- [ ] 10.4 Implement the seller half's `submit`, `read` and `list` (bounded pages, lifecycle
      states, open extensions and cases, repair required for a missing authority credential) and
      the exceptional_end filing, journaled with an immediate attributed end and dispatched
      to the dispute adapter, with no stop or reverse of its own and no wait for a ruling. Verify:
      unit and library-integration tests for "A seller lists its deals", "An authority's
      credential is missing", "A seller stops offering an authority", "An administrator ends a once-only deal" and "A filing is not ruled".

- [ ] 10.5 Persist final-request identities, actors, causes, instants and evidence references,
      including superseded requests and administrator identity/reason for operator ends,
      and expose earliest-end attribution and current physical
      progress through `read`. Accept verified site reports as final requests; journal required
      exceptional_end(at) filings atomically with unentitled ends, including never-started
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
- [ ] 10.6 Implement the site report's independent acceptance boundary first: immutable event
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

Verification point: unit and library-integration suites of `kit/deal-servicing`; `make
check-architecture`; `make test`. End-to-end: none; no storefront composes the kit yet.

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

- [ ] 11.1 Implement the payment adapter against the kit-owned vector-derived in-process payments contract fake (no runnable tooling dependency): per-part event
      translation, derived idempotency keys, `unknown` resolved by `read`, verified snapshots
      (section 9), open extensions per ref. Verify: library-integration tests for "A reverse's
      response is lost", "A ruling discounts a deal" (observation side), "Two outcomes reverse
      the same part" (observation side) and "A held part shows its extension".
- [ ] 11.2 Route seller refunds through reverse and reconcile unreported commitments.
      The payment adapter sends no exceptional-end events: the seller's exit is the dispute
      filing, and the adapter sends only voluntary `reverse {part, amount}` with stable per-part
      keys and verified unknown-result recovery. Spot adds rate commands, not a seller
      self-penalty. Verify test_seller.py and test_reconciliation.py for voluntary reverses and
      crash replay.

Verification point: `kit/arkhai-payments` unit and library-integration suites against the
kit-owned in-process payments contract fake; `make test`. End-to-end: `e2e_credits_payment_deal`'s seller refund is
evidence where a payments target is reachable.

## 12. Arkhai mediation dispute kit

Delivers `kit/arkhai-mediation`, the first dispute kit: the `arkhai.mediation.v1` adapter, its
client and the vendored contract, with an in-process contract fake and signing fixtures shared by contract vector with the HTTP double. Implements D4, D6 ("Adapters"), D10
and the design's "Arkhai mediation" dependency items as the client side, and the requirements
"Disputes are per agreement and separate from payment", "Requests are intents or interface
requests" (mapping), "A filing's outcome is the authority's answer", "A late case moves no
paid-out money" (client side) and "Dispute writes are idempotent". Files: new
`kit/arkhai-mediation` (`schema/SOURCE.md`, adapter, client, signing fixtures),
`docs/development/ARCHITECTURE.toml` (`[[disputes]]` row).

- [ ] 12.1 Vendor the `arkhai.mediation.v1` contract as published, or, until it is, a draft
      marked unpublished in `SOURCE.md` with live use refused; register the interface in
      `[[disputes]]`. Supply contract models and record-signing fixtures here, before adapter work
      in 12.2; supply installed selected schema/vector/model APIs with publication/hash metadata
      and built-wheel resource checks, from one canonical source. Both the kit fake and
      runnable-double tooling consume these vector-backed fixtures, including revision/netting vectors. Verify: `make check-architecture` accepts the kit and refuses a payment
      mechanism token in it.
- [ ] 12.2 Implement the adapter and client: file, append and read at the Agreement's origin with
      credentials bound by identity; build and validate free-form requests; return the authority's answers, per-part
      `held` / `not_held`, errors and `pending` as lifecycle outcomes; verify record entries.
      Verify: library-integration tests against the kit-owned vector-derived in-process mediation contract fake (no runnable tooling dependency) for "Two cases on one
      deal", "Parts differ", "A part was wholly reversed", "Payout wins against the extension",
      "A late case ends delivery" (filing half), "A filing's response is lost", "The case closes
      during the append" and "The claimant adds evidence".

- [ ] 12.3 Map `buyer_end(at)` (buyer-filed) and `exceptional_end(at)` (payee-filed) through the
      mediation adapter's published request vocabulary, preserving the signed buyer request and
      seller acknowledgement as evidence. Files:
      `kit/arkhai-mediation` adapter and contract. Gate: section 2.4 and the confirmed
      mediation contract for live use. Verify: library-integration targets for unavailable
      authority/retry, exact Agreement in case verified against mandate deal hash with neither
      attachment deposited, and every buyer_end case entering human triage, acknowledgement or not.
      Confirm payer notice/partialPeriod and netting recorded stops (including unknown-but-landed
      stop) in the published mapping. The only mechanical ruling is the standard self-penalty for a
      payee-filed exceptional_end at least as strong: stop rate parts now returned through mediation's
      own `chosen` entry, reverse earnings since at and unserved once shares (setup all if undelivered),
      then reverse min(premature_stop_penalty, earned amounts still held) across parts in mandate order;
      bond award is reserved for hosted bonds; weaker requests enter triage. Verify the standard and weaker requests. Bind the semantic filing identity and same-intent
      discovery/adoption across online/operator callers without a concurrent-writer duplicate.
      Qualify revised/linked-case mapping with prior ruling/effect references and netting;
      unresolved original effects resolve first, unsupported mapping is repair required.

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

- [ ] 13.1 Implement the routes as a router factory the storefronts mount, never relaying a
      buyer's authority command. Sign end_delivery responses using kit/identity v2 under
      the Agreement's seller principal; consume 2.4's neutral binding/verifier, never host a
      verifier buyer/dispute kits must import from servicing. Verify application-integration
      through the typed client for authentication, signature binding and relay refusal.
- [ ] 13.2 Emit seller diagnostics when reserve-ahead or payer notice does not cover the configured
      polling/watchdog/teardown budget; these are recommendations, not codec/publication refusals.
      Warn on runtime shortfall and never stop lifecycle loops. Verify the budget diagnostic
      and continued-loop scenarios.

- [ ] 13.3 Serve `end_delivery` directly as the accepted buyer's peer message, keyed by
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

- [ ] 14.1 Compose the servicing kit, the hosted payment adapter and the mediation adapter in the
      VM storefront; enable seller envelope capture in the negotiation controllers. Verify:
      application-integration test that a hosted VM deal appears in `list` and its acceptance
      envelope is stored.
- [ ] 14.2 Route terminal settlement and refund-driven ends through end service, and order
      delivery start and reconciliation against the earliest final request. Verify:
      application-integration tests through the typed client with kit-owned vector-derived in-process payments and mediation
      contract fakes (no runnable tooling dependency) for "A seller's hardware fails", "A buyer tears down" scenarios in the VM
      delta, and the admission scenarios on the VM path.
- [ ] 14.3 Keep the requested instant in VM lease ends (second precision). Verify: unit and
      integration tests in the VM fulfillment suites for the delta's scenarios.
- [ ] 14.4 Route admin interrupts through the seller half: submit notice stop when the accepted
      option grants the payee an entitlement, otherwise journal delivery end and file
      exceptional_end(now) through the dispute adapter. Keep administrator
      identity and reason. Verify both branches: authority notice governs entitled delivery end;
      without entitlement end service drives delivery immediately and the filing retries independently.

- [ ] 14.5 Mount the peer end/read route and authenticated site-report receiver in the VM
      storefront; terminate now through `terminate_vm_lease`/hold release, not a watchdog kick.
      Add the VM buyer end verb through the buyer half and canonical client. Files:
      `domains/vms/storefront` fulfillment services, callback/router composition and startup;
      `domains/vms/buyer` command and stage composition. Gates: sections 7.5, 10.6 and 13.3.
      Verify: VM application-integration targets with real persistence for accepted-site
      signature checks, duplicate callback, end before provisioning and teardown progress;
      buyer application-integration targets for canonical client dispatch and evidence capture.
      Extend `e2e_deal`/`e2e_deal_buyer_cli` buyer-end stages to read signed site bytes and await
      proven capacity release, readiness-gated through the existing lane tooling.

Verification point: the VM storefront's unit and application-integration suites; `make test`.
End-to-end: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_vm_introduction` must keep passing;
the first two gain delivery-only end/report stages, not hosted rate-part stop qualification.

## 15. Bare-metal wiring

Delivers the bare-metal storefront's composition and its teardown and terminal settlement
through end service, with delivery admission ordered against the end. Implements D8 for bare metal
and the bare-metal half of the section 14 requirements, including "A buyer tears down bare metal".
Files: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` (`api.py`
`teardown_fulfillment`, `fulfillment_service.py`, `settlement_stages.py`,
`settlement_composition.py`, `sqlite_client.py` refund intent).

- [ ] 15.1 Compose the servicing kit and adapters, route teardown and terminal settlement through
      end service, and order admission against the end. Verify: application-integration tests
      for "A buyer tears down bare metal" and the admission scenarios on the bare-metal path.

- [ ] 15.2 Fold the buyer teardown route into `end_delivery` and move `market bare-metal
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

## 16. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits
documentation only; a part needing code returns the change to implementation.

- [ ] 16.1 **Comment hygiene.** Run `make check-comment-hygiene` and read the comments the change
      added for provenance; anything found returns the change to implementation.
- [ ] 16.2 **Import placement.** Confirm the imports each section added are at module level
      unless a recorded reason keeps one local; one that should move returns the change to
      implementation.
- [ ] 16.3 **Documentation compliance.** Re-check D1–D15 against the placement rules, in
      particular that the dispute authority's and payments service's behaviour appears only as
      context in `deal-lifecycle/architecture.md` ("External authorities"), not as SCM
      requirements.
- [ ] 16.4 **Narrative compression.** Compress completed-task notes to final behaviour, evidence,
      deferred work and destinations.
- [ ] 16.5 **Roadmap currency.** Update Goals 6 and 8's current state and remove or mark landed
      this change's post-commitment lifecycle and buyer-end/report gaps in
      `docs/development/ROADMAP.md`; name both updates in the promotion record.
- [ ] 16.6 **Campaign index currency.** Update this change's row in `openspec/changes/README.md`
      and the campaign graph (`spot-deals-through-arkhai-payments`, `move-settle-out-of-core`,
      `automate-seller-spot` build on it), including the folded buyer-end/report boundary and
      its delivery/deadline dependents; run `make check-change-index`.
- [ ] 16.7 **Packaging.** Run `make check-packaging` and `make
      check-architecture-change CHANGE=agreed-evidence-and-early-termination` and resolve every
      failure; no architecture exception row may remain owned by this change.
- [ ] 16.8 **End-to-end pipeline.** Record the pipeline run, its result, and that `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_non_erc20_settlement` and `e2e_credits_payment_deal` passed or were readiness-gated;
      record buyer delivery-only ends, site-report retrieval and subsequent proven capacity return
      in the existing compute scenarios. The hosted rate lifecycle e2e is owned by
      `activate-per-period-compute-servicing`, with convergence owning consuming servicing scenarios
      and in-lane double evidence labelled separately
      from hosted qualification.
- [ ] 16.9 **Promotion.** Write the permanent documents and the design-promotion record:
      `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Authority
      boundaries" with D4's independent per-deal authority and D6's counterpart table, "Kit
      areas", "Registry self-description", major flows); `docs/development/ARCHITECTURE.toml`;
      new `openspec/specs/deal-lifecycle/architecture.md` (D5–D10 rationale, "External
      authorities") and its `openspec/specs/README.md` index entries; companions
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
- [ ] 16.10 **Documentation citations.** Run `make check-doc-citations
      CHANGE=agreed-evidence-and-early-termination` and resolve every match; then
      `openspec validate agreed-evidence-and-early-termination --strict`.
- [ ] 16.11 **Archival.** `openspec archive agreed-evidence-and-early-termination -y`, merging the
      deltas; link the index row to the archive.

## Design promotion record

Planned destinations below; promotion is not performed during this design reconciliation.
The remaining D1–D15 destinations are listed in proposal.md and task 16.9.

| Accepted decision | Permanent location |
|---|---|
| D6 neutral authorization/evidence envelope, sole end-service billing-start intent; D8 cause classification, pre-start timing exception and revised-remedy netting | New `deal-lifecycle` spec/architecture and settlement-servicing spec/architecture at closeout |
| D8 receipt-only canonical end, buyer stop with retry, stop-or-case and both CLI paths | `openspec/specs/buyer-orchestration/spec.md` and `architecture.md` |
| D5 premature-stop penalty codec and D10 capped held-earnings remedy; D10 one mechanical ruling for the seller self-penalty; D8 exceptional_end filing and stable keys; D9 retained signed evidence; D10 case-carried Agreement and human triage | New `deal-lifecycle` capability's spec and architecture companion (created at archive/closeout) |
| D8 site-signed intended-end report, transactional event/outbox and recovery | `openspec/specs/site-capacity/spec.md`, `openspec/specs/physical-provisioning/spec.md` and their architecture companions |
| D8 intended end versus proven release; terminate versus future truncate | `docs/development/ARCHITECTURE.md`, "Site authority", "Fulfillment status and results", "Release"; `openspec/specs/site-capacity/architecture.md` |
| D8 VM buyer end and second-precision lease effects | `openspec/specs/vm-storefront-fulfillment/spec.md` |
