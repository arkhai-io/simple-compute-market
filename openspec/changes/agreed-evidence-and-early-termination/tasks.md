# Tasks — agreed evidence and early termination

Planned 2026-10-27 from the design advanced by the eighth design round
(`reviews/15-design.triage.md`, `reviews/16-design-external.triage.md`). Depends on no open
change for design or planning. Implementation depends on two external contracts (design.md,
"Dependencies on the hosted payments service"): the payments service's hold-extension contract
(`hold-floor`, amended to per-extension refs) gates section 8, and the `arkhai.mediation.v1`
contract gates live use of section 12's adapter but not its implementation against the test
double.

Sections follow the design's implementation cadence. Sections 1–7 are round 1 (foundation,
wire and buyer side); section 8 joins round 1 only if the hold-extension contract is vendored
in `kit/arkhai-payments/schema/` when round 1 starts, and otherwise opens round 2; sections
9–15 are round 2 (seller servicing and domain wiring); section 16 is the closeout.

Wire and persistence breaks, all forward-only (design.md, D5 and "Rollout"): options carrying
`adjudication` or `early_termination` have new option IDs and Agreement bytes; every hosted
mandate hash and test vector changes in section 8; `[Settlement.arkhai_payments].dispute_authority`
is rejected from section 3; `[Settlement.alkahest]`'s two release flags are migrated in section 4.

Paths: `src/` abbreviates each package's source root. "Payments test double" is the double at
the `kit/arkhai-payments` client boundary, and "mediation test double" the one section 12 adds
at the `kit/arkhai-mediation` boundary (`docs/development/TESTING.md`, "Private Service
Dependencies"). No end-to-end scenario exercises lifecycle behaviour in this change: the hosted
four-path e2e against the payments service's public test deployment is owned by
`spot-deals-through-arkhai-payments` (design.md, D15). Sections that change existing deal paths
name the existing scenarios that must keep passing.

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
interface. Implements D1–D3, D5 (terms, codec, semantics table, entitlements as stop
authorities), D6 (commands, outcomes, events, adapter families), D9 (evidence record shape) and
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
      `early_termination` and reserved `bond`; malformed and bounded-term refusal
      (`case_hold_max_seconds` a nonnegative integer or `null`, minimums from an authority's
      advertisement copy); and the semantics table. Verify: unit tests for each refusal in the
      "Malformed terms are refused" and "Dispute timing terms are bounded" scenarios, and that
      a term change changes the option ID through the existing option-ID function.
- [ ] 2.3 In `kit/deal-lifecycle`, define the payment-adapter and dispute-adapter protocols and
      their tables (payment by negotiation ID, mechanism and arbiter or oracle; dispute by
      `adjudication.dispute.interface`), injected by compositions; the deal-level intent
      `exceptional_end(at)`; derivation of each part's stop authorities from entitlements plus
      the agreement's dispute authority; operation-key handling (derived idempotency keys for
      part events, filings and appends; local refusal of a retry with changed content); and the
      evidence-store interface keyed by negotiation ID. Verify: unit tests for "A mechanism has
      no adapter for a command", "A deal names an interface with no adapter", "An interface has
      no exceptional end", "A retry changes content" and the on-demand stop-authority scenario,
      using fake adapters.

Verification point: unit tests in both kits; `make check-packaging`; `make check-architecture`;
`make test`. End-to-end: none; nothing composes the kits yet.

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
      environment-variable reference) and `use_registry_dispute_authorities` (default true) in
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
      registry's recommendation" and the startup report of "No authority is available".
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
      `early_termination.payee.notice_seconds` as common fields projected by the
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
`core/storefront-client/src/storefront_client/client.py` (verified-response path), the
storefront's signed-request verification path (`kit/identity/src/market_identity/verification.py`
and the negotiation controllers that consume it), new `kit/deal-lifecycle-buyer`, and
`core/buyer/src/core_buyer/` composition where the buyer profile root is passed.

- [ ] 6.1 Add an injected envelope-capture seam to the buyer's verified-response path and to the
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
      for a mechanism with no adapter, `hint` after a filing. Verify: library-integration tests
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
      domain that a hosted-mechanism deal stage reaches `commit` (with the payments test double)
      and an Alkahest deal stage is unchanged.

Verification point: unit and library-integration suites of the client and buyer kits; the VM and
bare-metal buyer application-integration suites; `make test`. End-to-end: `e2e_deal`,
`e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal` must keep passing; none exercises a hosted
lifecycle deal.

## 8. Hosted mandates, buyer mandate check and hosted option builders

Gated: starts only once the payments service's hold-extension contract is vendored and
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

- [ ] 8.1 Vendor the hold-extension contract (`extend` authorities key, `maxHoldExtension`,
      per-extension refs) and refresh vectors. Verify: `test_receipt_fixture.py` and the
      vector conformance tests pass against the new content hash.
- [ ] 8.2 Derive each part's authorities and holds from the terms: `once` hold from the expected
      approval time to the term end plus the window; `extend` authorities and `reverse` for the
      agreement's dispute authority taken from the option; `maxHoldExtension` from
      `case_hold_max_seconds`. Verify: `test_mandates.py` cases for "A once deal's hold is
      derived", "A bounded case hold is derived", "An unbounded case hold is derived" and "A
      mandate's extend authorities are derived".
- [ ] 8.3 Extend the buyer's mandate check to the derived authorities, holds and dispute
      authority, and report a payments-service refusal of the authority. Verify:
      `test_buyer.py` cases including "The payments service refuses the authority" and the
      payee-as-stop-authority refusal.
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

- [ ] 9.1 Verify snapshot proofs against the receipt identity and refuse unverified snapshots.
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
to a case", "An append to a closed case is skipped", "Mechanical rulings are the authority's
policy", "A seller's exceptional end is an intent", "The seller half lists deals", "Dispute
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
      through a narrow domain port; an admission port the domain calls before delivery start.
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
      the exceptional-end command filing `exceptional_end(now)` with no per-part amounts. Verify:
      unit and library-integration tests for "A seller lists its deals", "An authority's
      credential is missing", "A seller stops offering an authority", "An administrator files an
      exceptional end" and "A filing is not ruled".

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

- [ ] 11.1 Implement the payment adapter against the payments test double: per-part event
      translation, derived idempotency keys, `unknown` resolved by `read`, verified snapshots
      (section 9), open extensions per ref. Verify: library-integration tests for "A reverse's
      response is lost", "A ruling discounts a deal" (observation side), "Two outcomes reverse
      the same part" (observation side) and "A held part shows its extension".
- [ ] 11.2 Route seller refunds through `reverse` commands and reconcile commitments the buyer
      never reported. Verify: `test_seller.py` and `test_reconciliation.py` cases.

Verification point: `kit/arkhai-payments` unit and library-integration suites against the
payments test double; `make test`. End-to-end: `e2e_credits_payment_deal`'s seller refund is
evidence where a payments target is reachable.

## 12. Arkhai mediation dispute kit

Delivers `kit/arkhai-mediation`, the first dispute kit: the `arkhai.mediation.v1` adapter, its
client, the vendored contract and the mediation test double. Implements D4, D6 ("Adapters"), D10
and the design's "Arkhai mediation" dependency items as the client side, and the requirements
"Disputes are per agreement and separate from payment", "Requests are intents or interface
requests" (mapping), "A filing's outcome is the authority's answer", "A late case moves no
paid-out money" (client side) and "Dispute writes are idempotent". Files: new
`kit/arkhai-mediation` (`schema/SOURCE.md`, adapter, client, test double),
`docs/development/ARCHITECTURE.toml` (`[[disputes]]` row).

- [ ] 12.1 Vendor the `arkhai.mediation.v1` contract as published, or, until it is, a draft
      marked unpublished in `SOURCE.md` with live use refused; register the interface in
      `[[disputes]]`. Verify: `make check-architecture` accepts the kit and refuses a payment
      mechanism token in it.
- [ ] 12.2 Implement the adapter and client: file, append and read at the Agreement's origin with
      credentials bound by identity; map `exceptional_end(at)` to the standard self-penalty
      request; build and validate free-form requests; return the authority's answers, per-part
      `held` / `not_held`, errors and `pending` as lifecycle outcomes; verify record entries.
      Verify: library-integration tests against the mediation test double for "Two cases on one
      deal", "Parts differ", "A part was wholly reversed", "Payout wins against the extension",
      "A late case ends delivery" (filing half), "A filing's response is lost", "The case closes
      during the append" and "The claimant adds evidence".

Verification point: `kit/arkhai-mediation` unit and library-integration suites; `make
check-architecture`; `make check-packaging`; `make test`. End-to-end: none; live mediation is not
reachable from public CI.

## 13. Lifecycle routes and exposure checks

Delivers the storefront's lifecycle routes (seller `submit`, `read`, `list` under the
administrator principal; buyer `commit` and `hint` as the negotiation's buyer, signed responses)
and the exposure-budget checks. Implements D6 (routes) and D5 (budget), and the requirements
"Lifecycle routes are authenticated per role" and "Term values agree with the Agreement and the
seller's budget". Files: `kit/deal-servicing` (router factory),
`kit/deal-lifecycle-contracts` (route contracts), `kit/storefront` composition.

- [ ] 13.1 Implement the routes as a router factory the storefronts mount, never relaying a
      buyer's authority command. Verify: application-integration tests through the typed client
      for authentication per role, signed responses and refusal of a relayed authority command.
- [ ] 13.2 Refuse at publication and acceptance an option whose exposure is below the polling
      interval plus watchdog and teardown budget, and a configuration change that would put an
      active deal over its exposure. Verify: application-integration test for the 290-second
      scenario.

Verification point: application-integration suites; `make test`. End-to-end: none.

## 14. VM wiring

Delivers the VM storefront's composition of the seller half, evidence store and `watch`, its
admin exceptional-end route, terminal settlement and delivery admission through end service, and
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
      application-integration tests through the typed client with the payments and mediation
      test doubles for "A seller's hardware fails", "A buyer tears down" scenarios in the VM
      delta, and the admission scenarios on the VM path.
- [ ] 14.3 Keep the requested instant in VM lease ends (second precision). Verify: unit and
      integration tests in the VM fulfillment suites for the delta's scenarios.
- [ ] 14.4 Add the admin exceptional-end route through the seller half. Verify:
      application-integration test that the route files `exceptional_end(now)` and the lease
      changes only once the ruling is read.

Verification point: the VM storefront's unit and application-integration suites; `make test`.
End-to-end: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_vm_introduction` must keep passing; none
exercises a hosted lifecycle end.

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
- [ ] 16.5 **Roadmap currency.** Update Goal 6's current state and remove or mark landed the gap
      row "Post-commitment lifecycle…" in `docs/development/ROADMAP.md`; name it in the
      promotion record.
- [ ] 16.6 **Campaign index currency.** Update this change's row in `openspec/changes/README.md`
      and the campaign graph (`spot-deals-through-arkhai-payments`, `move-settle-out-of-core`,
      `automate-seller-spot` build on it); run `make check-change-index`.
- [ ] 16.7 **Packaging.** Run `make check-packaging` and `make
      check-architecture-change CHANGE=agreed-evidence-and-early-termination` and resolve every
      failure; no architecture exception row may remain owned by this change.
- [ ] 16.8 **End-to-end pipeline.** Record the pipeline run, its result, and that `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_non_erc20_settlement` and `e2e_credits_payment_deal` passed or were readiness-gated;
      the hosted lifecycle e2e is owned by `spot-deals-through-arkhai-payments`.
- [ ] 16.9 **Promotion.** Write the permanent documents and the design-promotion record:
      `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Authority
      boundaries" with D4's independent per-deal authority and D6's counterpart table, "Kit
      areas", "Registry self-description", major flows); `docs/development/ARCHITECTURE.toml`;
      new `openspec/specs/deal-lifecycle/architecture.md` (D5–D10 rationale, "External
      authorities") and its `openspec/specs/README.md` index entries; companions
      `settlement-servicing/architecture.md` ("Capacity coupling", "Current limits",
      "Charge-first payment settlement"), `storefront-publication/architecture.md` ("Arkhai
      payment options"), `deployment-state/architecture.md`, `test-compatibility/architecture.md`,
      `buyer-orchestration/architecture.md` and `api-credits/architecture.md` ("Payment
      composition and recovery"); `docs/development/DEPLOYMENT_AND_CONFIG.md` (exposure budget
      settings, beside sections 3 and 4's entries). The archive writes the delta-covered
      `spec.md` files: `deal-lifecycle` (new), `buyer-orchestration`, `cli-query-language`,
      `deployment-state`, `market-composition`, `negotiation-protocol`, `registry-discovery`,
      `settlement-configuration`, `settlement-servicing`, `storefront-publication`,
      `test-compatibility`, `vm-storefront-fulfillment`.
- [ ] 16.10 **Documentation citations.** Run `make check-doc-citations
      CHANGE=agreed-evidence-and-early-termination` and resolve every match; then
      `openspec validate agreed-evidence-and-early-termination --strict`.
- [ ] 16.11 **Archival.** `openspec archive agreed-evidence-and-early-termination -y`, merging the
      deltas; link the index row to the archive.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
