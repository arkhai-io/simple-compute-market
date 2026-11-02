# Tasks — agreed evidence and early termination

Reconciled design-stage plan, updated 2026-10-29 after triage of reviews 17 and 18; amended 2026-11-02 for one payee-agreed delivery_end claim and the published mediation revision.
No implementation is implied by unchecked tasks. Depends on no open
change for design or planning. Implementation depends on two external contracts (design.md,
"Dependencies on the hosted payments service"): the published payments partialPeriod contract revision, ready to vendor at 8.1
(hold extensions, per-part start/stop and authorities with notice
durations, per-part `end` and `afterStop` holds, one re-vendor) gates section 8, and the arkhai.mediation.v1 delivery_end revision (claim/signature/concurrence/respondent listing) is now published and vendored at 12.1. Receipt embedding, buyer concurrence, respondent HTTP polling and setup-bearing presets still require their implementation tasks; the hosted service remains on the older contract and live qualification is pending.

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

### Settlement-option accessor checkpoint (2026-11-02)

- At the 2.5a checkpoint, Payments Agreement and public-carrier readers used
  core accessors while serialized options and IDs stayed unchanged. Mandate
  derivation consumes typed mechanism parameters, not the public carrier.
- The producer gate is satisfied by the published `option-envelope-projection`
  revision, recorded only in `kit/arkhai-mediation/schema/SOURCE.md`. Its schema,
  mapping and regenerated vectors support the D5 option without rewriting the
  Agreement. Models are regenerated and contract, drift, typing and all 40
  mediation integration/trace cases pass; no gate xfail or skip remains.
- 2.5b and the cleanup portion of 2.5c use optional `price`, required `settlement`
  with flat `schema`-tagged parameters, and optional `lifecycle`. Selection mirrors
  the settlement envelope with buyer-owned parameters; registry filters and
  persisted Agreement queries read the new paths. Lifecycle identity coverage
  hashes its own key. Alkahest has no lifecycle terms; introductions have no
  price. All listings must be republished because their option IDs change.
- The earlier no-runtime blocker (#324) was overcome with the verified Podman
  shim for owned end-to-end lane runs. Current results are recorded below.
  The active plan's future lifecycle architecture citation is tracked in #325.

### Settlement-option wire cutover verification (2026-11-02)

- 2.5b and 2.5c's wire/cleanup work are implemented. The producer projection
  gate is satisfied, with no compatibility projection and no gate-related
  xfail or skip. The exact producer revision is recorded only in the mediation
  kit's `schema/SOURCE.md`; generated-model drift, contract, typing and all
  40 mediation cases, including 12.3's 14 ruling-trace replays, pass.
- Required proxy settings: unset `ALL_PROXY` and `all_proxy`; set `NO_PROXY`
  and `no_proxy` to `localhost,127.0.0.1`. `make check-architecture`,
  `make check-packaging`, `make check-comment-hygiene`, full `make test`,
  core typing and pinned OpenSpec strict validation pass. Aggregate tooling
  tests used a standalone Docker Compose binary for config rendering, not
  a daemon or a replacement payment service.
- Fresh branch-built lane stacks republished their listings. `e2e_deal`:
  **35 passed**. `e2e_bare_metal_mock_deal`: **39 passed**.
  `e2e_credits_payment_deal`: the first run blocked/skipped all 3 cases because
  `PAYMENTS.SERVICE_URL` was absent. The follow-up at SCM revision
  `9e4fe5aff3b001a187576ac24cf9364eac55664d` configured a real local Arkhai
  payments service with Formance/Postgres and republished the API-credit listings:
  **3 passed, 0 skipped**, in 5.14 seconds. Baseline/held/replayed/refunded HTTP
  balance observations confirm the 3,000,000 USD/6 debit, unchanged replay and
  full seller reversal; buyer funds are restored and `feePaid=0`. Host, buyer
  and seller payment readiness passed before pytest. **2.5 is complete**.
  Operator-side readiness tooling needed the new `settlement.schema` path;
  its disposable adaptation and follow-up #327 are recorded in the packet.
  No SCM code or scenario assertion changed for this qualification.
- Every owned lane container, volume and network was removed, and native Anvil
  children left by scenarios were stopped. No external resource is left running.
- The payment smoke example reaches provisioning and ready delivery under the
  new envelope; it is an injected in-process self-check, not a live payment run.
  Existing test assertions were migrated without dropping acceptance cases;
  no new acceptance tests were added. Optional section 4 is not included.
- Evidence and runnable setup: `docs/attachments/settlement-option-envelope/index.md`.
  Reviewed-closeout promotion remains in the active settlement-configuration
  and negotiation-protocol deltas, with lifecycle ownership in deal-lifecycle.

### Implementation checkpoint (2026-11-02)

- Implemented and committed 1.1–2.4 in order. The contracts and foundation wheels
  are in the kit build/test aggregates. No service composes these kits yet, and
  existing settlement-option wire bytes remain unchanged.
- Remaining in the sections 1–2 assignment: all of 2.5, including every option
  builder/consumer, the selection mirror and registry carrier, republishing, and
  the three named end-to-end suites. No partial wire cutover has been made.
- Focused verification passes: architecture fixture trees (73 tests), lifecycle
  contracts (37 tests), lifecycle foundation (62 tests). `make check-architecture`,
  `make check-packaging`, `make check-comment-hygiene` and pinned OpenSpec 1.14.0
  strict validation pass. `make test` has been run repeatedly but has not passed
  end-to-end in this environment; the unresolved setup boundary is tracked in
  [#323](https://github.com/arkhai-io/simple-compute-market/issues/323).
- The first full-suite attempt inherited a SOCKS proxy without `socksio`; removing
  proxy variables exposed a malformed IPv6 entry in inherited `NO_PROXY`.
  Both stopped at the same provisioning-client tests. A proxy-free rerun passed
  those 607 unit tests and the provisioning integration tests, but was stopped
  while storefront dependency resolution made no progress. The located fixture
  defect is fixed separately: the sign-only test now injects an HTTP mock
  transport, so it neither initializes ambient proxy transports nor performs I/O.
  Its six tests pass under the original environment with assertions preserved.
  The same ambient-proxy defect also affected the VM degraded-startup scenario;
  its existing loop-registry fixture now removes proxy variables so its loopback
  refusal boundary stays real and deterministic (two tests pass). Both fixture
  repairs preserve all kept assertions. A subsequent full rerun retained the normal
  dependency-download environment and passed VM storefront integration
  (501 tests) but stopped at 55 bare-metal storefront setup failures with the same
  missing SOCKS transport. A further run preserving HTTP/HTTPS proxies, removing
  ALL_PROXY and limiting NO_PROXY to loopback passed 607 provisioning unit tests
  but stopped at `test_storefront_checks_reflect_configured_url` (453 other
  provisioning integration tests passed). Later aggregate targets were not reached.
  No end-to-end suite was run: the 2.5 wire cutover and republish are still pending.
- Choices: instants in the neutral wire are Unix seconds; disputed signed bodies
  remain base64-carried exact bytes. The delivery-end intent is neutral and has
  either cause. The acknowledgement's signed-claim slot currently accepts only
  omission/null; concrete mediation claims and signatures fail closed until 12.1.
  Capability support comes from injected installed-contract declarations, empty
  by default. The term-identity test uses the existing option-ID helper with
  encoded terms as opaque parameters; 2.5 must move it to the new lifecycle key.
- Reproduce the library surface from a clean checkout with `make dist`, then
  `make -C kit/deal-lifecycle-contracts test` and `make -C kit/deal-lifecycle test`.
  This is library-only setup, with deterministic test principals and injected
  adapters, no deployed target, seed, external credentials or resident server.

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
  - The scoped citation command reports only the three pre-existing future
    lifecycle spec/architecture destinations tracked by #325; no new citation
    is unresolved. No placeholder spec was created. Normative promotion remains
    the reviewed closeout work at 16.9.

Verification point: unit suites of `kit/deal-lifecycle` and `kit/arkhai-payments`; the registry
descriptor suites (unit and library integration); the Helm render check; `make test`.
End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` must keep
passing (they start roles from rendered configuration); none exercises the new list.

### Sections 3 and 5 implementation checkpoint (2026-11-02)

- Completed 3.1, 3.3 and 5.1. The authority configuration library, explicit buyer
  profile opt-ins, signed descriptor recommendations, and common query
  projections are committed. No option wire bytes or IDs change.
- Remaining: 3.2 retires the payments authority key; 3.4 composes role lists,
  fetches registry recommendations and reports empty lists; 3.5 documents that
  role-level configuration. Section 4 is intentionally untouched.
- 3.2 has a sequencing dependency on 2.5b: the current payments
  `mandate_policy_for_agreement` and `PaymentApproval` require the configuration
  authority, while the pre-flip option's lifecycle accessor returns no terms.
  Removing that input now would break every hosted commitment or require a
  competing temporary authority wire. Keep the existing path until the
  Agreement can carry its authority under the designed lifecycle key.
- For 3.4, current buyer bootstrap reads the signed filter specification, not
  the descriptor, and storefront registry clients use configured trust pins
  without fetching it. The role wiring must add descriptor reads and retain
  per-registry recommendation lists; it cannot reuse an existing fetch.
- Reproduction and observed readiness are recorded in
  `docs/attachments/aeet-sections-3-5/index.md`. The library example and selected
  registry typed-client integration run pass from rebuilt wheel installs
  (12 registry tests). This is an implementer self-check, not independent
  acceptance or a deployed end-to-end scenario.
- The aggregate exposed an isolated API-credit wheel fixture missing the two
  new lifecycle dependencies. Its wheel list is repaired and all three
  isolated installation tests pass. The public distribution manifest,
  publication workflow and release guide also include both lifecycle packages;
  their 272 contract checks pass.
- Docker CLI absence reproduces the tracked release-tooling prerequisite
  failure [#324](https://github.com/arkhai-io/simple-compute-market/issues/324).
  A temporary Docker 28.3.3 / Compose 2.39.4 tool directory is used only for
  daemon-free configuration rendering and removed after its command.
  `make test-deployment-packaging` then passes: 1,838 release-tooling tests and
  all Helm structural/render assertions. No container daemon, deployment or
  end-to-end scenario is started. The aggregate was exercised in segments after
  repairs; there is no single all-green `make test` invocation.

### Role integration checkpoint (2026-11-02)

- Supersedes the remaining-work list in the earlier sections 3/5 checkpoint:
  3.2, 3.4 and 3.5 are implemented; 3.1, 3.3 and 5.1 remain complete.
- Reproducible owned-target setup, first-use observations and exact limitations
  are in `docs/attachments/aeet-sections-3-5/index.md`. The configuration example,
  signed registry application integration and local VM payment smoke pass.
- Existing test fixtures were adapted, without weakening assertions or adding
  permanent test functions. Generated storefront/umbrella schemas and release
  dependency documentation reflect the changed configuration and imports.
- Final full `make test` passes in one invocation (2026-11-02, 7m 2s), with
  the per-shell Podman shim and #323's proxy environment. This includes 1,843
  release-tooling tests and Helm render/structural checks. Locks, packaging,
  architecture, comment hygiene, strict OpenSpec validation and focused role
  suites also pass.
- The scoped citation check has only #325's three future lifecycle-document
  matches. End-to-end lanes and independent acceptance are unrun by this worker;
  hosted option construction and exact authority admission remain section 8.
  No shared deployment or resident external resource was created.

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

### Section 4 verification checkpoint (2026-11-02)

- All four implementation tasks are committed. Full `make test` passes with the
  local Podman shim and proxy exclusions; architecture, packaging, locks,
  comment hygiene and strict OpenSpec validation pass.
- The VM container lane passes 37 stages covering ERC20, native-token and ERC1155
  settlement. The bare-metal mock lane passes 39 stages. Its selected real-host
  scenario skips: `BARE_METAL.REGISTRY_URL is not configured`; no real whole host
  or role-scoped SSH credential is available, so that qualification remains
  unobserved, not passed.
- Full change-scoped citations retain the already recorded pre-closeout failure
  (GitHub issue 325); changed permanent-document citations resolve. No check or
  acceptance boundary was weakened. The packet above carries reproducible
  first-use setup, observations and the two small fixture repairs.
- The roadmap and campaign remain in implementation; this section changes no
  dependency or campaign status. Subsystem-spec promotion remains at 16.9.

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

### Buyer evidence implementation checkpoint (2026-11-02)

- `kit/deal-lifecycle-buyer` provides a transactional file store, a synchronous capture sink, superseded commitment/acceptance bindings, complete-observation retention, composable prune/export commands and exact-byte case export. VM and bare-metal CLI negotiation paths pass the profile-adjacent store; payment and VM escrow paths record references once known.
- The command factory accepts an injected fresh reader and an exact-Agreement-to-terms projection. The projection belongs to the buyer composition and uses the option accessor; the buyer-side kit imports neither core buyer nor the core Agreement carrier. Domain lifecycle command registration and live authority-reader composition remain in 7.4.
- The production HTTP negotiation integration reopens the store in the pre-payment acceptance callback. Retention covers running deals, recovery, every payout, open/closed cases, uncommitted expiry, missing terms/adapters, unavailable reads and concurrent capture. Export drives both composed commands and preserves superseded Agreements and binary evidence.
- Focused checks: buyer evidence 18 passed; core buyer 159 passed; storefront client 68 passed; core storefront 225 passed; VM buyer 213 passed; bare-metal buyer 16 passed. `make check-architecture`, `make check-packaging`, `make check-comment-hygiene` and strict OpenSpec validation pass. Full-suite and end-to-end results are recorded separately; no live hosted or deployment-qualified end-to-end evidence is claimed here.
- Publication metadata includes the buyer evidence distribution and its lifecycle/contracts dependencies in dependency order, with workflow filters and release-guide rows. The full `make test` run reached release tooling: six publication-metadata failures were repaired; the remaining compose-isolation check cannot run because this host has no Docker executable. The release-tooling suite excluding that Docker-dependent file and the Helm render suite pass, as do the focused publication matrix and required architecture, packaging, comment-hygiene and strict OpenSpec checks. No Docker-backed end-to-end result is claimed.
- Durable behavior and rationale are scheduled for `openspec/specs/deal-lifecycle/spec.md` and its architecture companion, with buyer composition details in `openspec/specs/buyer-orchestration/architecture.md`, at 16.9. `kit/deal-lifecycle-buyer/README.md` documents the installed API and reproducible first use now.

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

### Lifecycle buyer foundation checkpoint (2026-11-02)

- 7.1 provides the signed, publisher-pinned async lifecycle client for commit, hint and delivery reads, using the shared route declarations and exact-envelope capture. 7.2 provides injected buyer payment/dispute dispatch, durable same-key/content guards, interface-owned append packaging, separate hint observation and merged direct-authority/delivery reads. No payment remedy is applied by the buyer half.
- 7.3 composes exact authority admission in VM, bare-metal and API-credit fresh selection. The neutral core buyer receives only an option-preference callback; it does not bind a lifecycle kit. Registry-specific policy is preserved through compatibility/explain paths, explicit bare-metal option IDs cannot bypass admission, and preference precedes option-ID ordering within the selected mechanism and clause.
- Client and buyer first-use examples pass, as does the production VM authority-selection example. Existing suites pass: lifecycle 62, buyer evidence 18, core buyer 159, storefront client 68, VM buyer 213, bare-metal buyer 16 and API-credit buyer 35. Existing negotiation fixtures now supply accepted lifecycle authorities; no permanent test function was added or assertion weakened.
- Fresh wheel builds, dependency-closure relocks, architecture, packaging, lock currency, comment hygiene, configured core typing and pinned strict OpenSpec validation pass. The complete `make test` aggregate passes in 7m20s with the prescribed proxy settings and Podman shim, after supplying accepted authority setup to existing bare-metal/API-credit CLI integration fixtures without weakening assertions. Signed peer acknowledgements without payload negotiation IDs are retained by their signed resource. Committed first-use setup, aggregate evidence and deployment limitations are recorded in `docs/attachments/lifecycle-buyer-foundation/index.md`.
- 7.4–7.5 remain deferred pending section 13: no compute lifecycle-stage handoff, canonical end-delivery verb, stop/outage journal or live lifecycle authority is claimed. Permanent contract/rationale promotion remains 16.9, to `openspec/specs/deal-lifecycle/spec.md`, its architecture companion and the buyer-orchestration documents.

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

### Section 10 implementation checkpoint (2026-11-02)

- Whole tasks 10.1–10.6 are implemented and checked above. Reproduce library first
  use from committed setup with `make dist-ci && make -C kit/deal-servicing first-use`.
  Each example owns a temporary SQLite database and public deterministic fixture
  principals; no deployment, credentials, seed files or resident service are required.
- Seller submit/read/list, pinned-authority credential repair, durable filing replay,
  authenticated site ingress and receipt-time buyer surrender are implemented.
  `make -C provisioning/compute/service first-use-lease-end` exercises the concrete
  site report, transactional outbox and authenticated lease-read projection with
  temporary state; its setup is documented beside the example. No resident server
  or private configuration is required.
- Adapter integration: the neutral dispute protocol now exposes build_append; the
  mediation kit owns its evidence packaging. Domain compositions must still bind
  verified payment-stop classification, complete retention observations, exact client
  response capture and the shared storefront watch-step registration. These hooks
  fail conservatively when absent; no payment ledger or mechanism-specific parsing
  was added to the servicing kit. No public option bytes or IDs changed.
- Focused regressions pass: foundation 62, contracts 37, mediation 40, storefront
  131, site 304, compute contracts 111, compute 244, storefront client 68 and
  compute service 607 unit/454 integration. The servicing examples and source
  typing pass. No permanent tests were added; existing setups were adapted for
  the new composition without removing or weakening assertions. Architecture,
  packaging, locks, comment hygiene and pinned strict OpenSpec validation pass.
- The earlier 10.1–10.3 aggregate attempt stopped at the Docker prerequisite,
  recorded in [#324](https://github.com/arkhai-io/simple-compute-market/issues/324#issuecomment-6570225578).
  The prescribed Podman shim now runs that check. The subsequent aggregate reached
  release tooling and found duplicate lifecycle publication entries; their separate
  repair passes all 1847 release-tooling tests. A fresh complete `make test` passes
  (7m11s), including Helm structural/render checks, with the prescribed proxy
  environment and Podman shim. No browser/deployed end-to-end run is claimed:
  domain composition is still owned by 13–15.

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

### Section 11 adapter checkpoint (2026-11-02)

- 11.1 supplies the once-only payment adapter, stable per-part reverse keys,
  required injected snapshot verification and cursor floor, signed-read recovery,
  and per-ref/case extension observation. The current-pin helper is available;
  rotation-aware verification is composed through the same required port.
- Existing payments suites: 92 pass; typing, generated resources, producer vectors,
  architecture, packaging, locks, comment hygiene and strict OpenSpec validation pass.
  Runnable first use and observation-side case effects are recorded in
  `docs/attachments/once-payment-adapter/index.md`. No new acceptance test was added.
- 11.2 routes seller refunds through verified per-part voluntary reverse commands.
  Reconciliation recovers the authority's recorded amounts after a lost answer and
  crash replay; the first-use fixture records exactly one refund per part. Legacy
  whole-part reversals are projected from signed cumulative state, not guessed.
- Full `make test` passes (7m03s) with the prescribed proxy environment and shell-local
  Podman shim, including release-tooling and Helm checks. The payments kit, editable
  first-use target and isolated installed-wheel replay pass. No external resource is
  left running. No hosted or real-HTTP payment qualification is claimed.
- Permanent documentation promotion remains at reviewed closeout in deal-lifecycle
  and settlement-servicing; no rate or exceptional-end payment command was added.

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

### Lifecycle route and cooperative ending checkpoint (2026-11-02)

- 13.1–13.3 provide the mountable, signed role-authenticated router, non-gating seller budget diagnostics, receipt-time surrender and owner-only exact site-report reads. The composition injects the accepted Agreement binding, its seller signer, the administrator trust set and its existing authority-verifying commit/hint implementation. No domain mounting is included.
- 12.4 provides bounded respondent discovery bound to signed filing records, persisted pages/cursors, exact journaled sign-or-contest answers and lost-append recovery. Compose one poller per accepted authority/account with payee credentials before deal watch; both adopt the same case-keyed append journal.
- 12.5 stores the owning adapter's reusable SignedDeliveryEndClaim atomically with receipt/end recording. 7.5 adds canonical client end_delivery and buyer stop/surrender/filing progress with durable same-key retries, offline Agreement-bound receipt verification, exact concurrence and contested observed-time fallback. Compose FileEvidenceStore.end_journal and the exact Agreement principals into the buyer half; authorized pruning clears its retained plans.
- Focused suites, source typing, built-wheel first-use examples, architecture, packaging, locks, comment hygiene and pinned strict validation pass. The old null-only claim test now preserves the available interface-owned claim; no permanent test was added. The full `make test` aggregate also passes in 7m54s with the prescribed proxy settings and shell-local Podman shim, including release tooling and Helm render/structural checks. Citation checking reports only the three known #325 destinations. First-use setup and boundaries: `docs/attachments/lifecycle-routes/index.md`. Sections 7.4, 14 and 15 still own domain stages/CLI/wiring; rate execution and live authority qualification remain their owning changes. Permanent promotion remains 16.9 to the lifecycle, buyer-orchestration and market-composition specifications and architecture companions.

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

### VM implementation checkpoint (2026-11-02)

- 14.1 composes the VM seller half, evidence store, once-payment and mediation
  adapters, signed lifecycle list/read/commit/hint routes, and respondent-before-
  watch servicing. Verified commitments register from their original receipts,
  including revalidated recovery. Negotiation responses retain both exact
  envelopes and proof context. The physical end/ingress ports remain 14.2/14.5.
- 14.3 preserves seconds in administrator and terminal-settlement lease ends;
  historical minute-format inputs remain readable. Commit: `e3a142381`.
- Verification: 28 precision cases, 57 existing payment/negotiation integration
  cases, the committed payment first-use example, architecture, packaging,
  locks, comment hygiene and pinned strict validation pass. No permanent test
  function was added. Setup/evidence and first-use boundaries:
  `docs/attachments/vm-lifecycle-wiring/index.md`.
- Early verification exposed optional composition stubs without lifecycle,
  a static pause-route collision with the new dynamic route, and diagnostic
  assumptions about JSON formatting/header casing; all are repaired. A separate
  publication fix (`90de651de`) replaces the duplicate mediation entries with
  the missing servicing kit and documents dependency closure once.
- Remaining: 14.2, 14.4, 14.5 and the VM half of 7.4. No buyer stage or CLI has
  been changed; keep 7.4 unchecked. Domain end-to-end setup with real local
  payments/mediation and end/report scenario extensions is unrun, not waived.
  The full aggregate result is recorded in the evidence packet. Permanent
  promotion remains 16.9; no shared kit or bare-metal source was changed.

### VM physical-end implementation checkpoint (2026-11-02)

- 14.2 connects terminal settlement and confirmed refunds to the shared end
  journal and VM physical port. Refund completion and its final request share
  one transaction. Reservation, dispatch, activation and credential checkpoints
  order admission in their own write transaction; recovery uses the same gates.
  Due ends deny subsequent disclosure. Undispatched capacity is released and a
  delivered VM is terminated now, not by a watchdog kick.
- The mounted end route now has its VM ingress/end ports and owning receipt
  claim signer. Signing uses read-only accepted/delivery snapshots inside the
  ingress transaction; a nested writer caused a local first-use lock error and
  was removed. The first-use fixture now names the real installed mediation
  interface rather than an unrelated fixture interface. Missing claim kind was
  caught by that first use and corrected. Physical retry is independent of
  authority failure; future ends without reservations remain pending.
- Existing fixture setups now provide committed admission and current lease
  windows. Kept refund/terminal assertions follow the deliberate behavior:
  refund during provisioning prevents disclosure, and terminal active leases
  request immediate termination. No permanent test function was added.
- Evidence and runnable setup: `docs/attachments/vm-end-admission/index.md`.
  The 1,690 existing VM unit/application-integration cases, mounted first use,
  fresh wheels, architecture, packaging, locks, comments and pinned strict
  validation pass. Full `make test` passes with the shell-local Podman shim;
  the final checks/first-use/aggregate pipeline completed in 7m42s. The scoped
  citation check reports only the three known future destinations in #325.
- The first aggregate reached release tooling and found an inherited
  bare-metal release-table omission. Separate repair `edd52a728` adds the three
  declared lifecycle dependencies once; all 1,858 release-tooling cases pass.
- Remaining: 14.4, the authenticated site-report receiver/pull recovery and
  callback release progress in 14.5, failure-source classification/correlation,
  the VM buyer stages/CLI and the VM half of 7.4. Keep 7.4 unchecked. Existing
  administrator interrupt and failure-policy release paths still need the
  seller-half/end-service dispatch owned by that continuation. No fresh-stack
  VM e2e, real local payment/mediation qualification or end/report e2e extension
  is claimed. No shared package or sibling-domain source was changed.
  Permanent promotion remains 16.9.

### VM administrator dispatch continuation checkpoint (2026-11-02)

- 14.4 routes hosted negotiation interrupts through the seller half. Accepted
  payee rights select a notice stop; otherwise the attributed receipt-time end
  and payee filing are journaled atomically, with physical drive concurrent with
  the filing so authority loss does not delay teardown. Administrator and reason
  are retained for both branches. Stable keys reject changed attribution;
  hosted requests reject supplied times and payout amounts. The existing
  Alkahest splitter-backed escrow path is unchanged.
- First use mounts the real administrator router, identity middleware, SQLite
  and signed client. The vector-derived mediation peer records one case before
  deliberately losing its response; same-key recovery returns that case. An
  injected future payment adapter demonstrates no local end before the effective
  authority stop and no self-penalty. This is dispatch/order evidence, not rate
  mandate or live-rate qualification. The existing payment example also shows
  physical drive with a missing mediation credential and durable filing repair.
- Evidence and clean-checkout entry points:
  `docs/attachments/vm-admin-interrupt/index.md`. The 72 existing focused cases,
  architecture, packaging, locks, comments and pinned strict validation pass.
  Full `make test` passes in 8m10s with the shell-local Podman shim and proxy
  exclusions, including release tooling and Helm checks. Citation checking
  reports only the three known future destinations in #325.
  No new permanent test function or weakened assertion; the payment fixture
  now supplies the installed mediation interface's vector-derived authority.
- First-use attempts caught a response lookup using the thread row's absent
  listing_id; the route now uses the accepted Agreement. The initial temporary
  diagnostic also lacked the explicit storefront-domain environment supplied by
  test setup; the committed entry point includes it. Neither failure is carried.
- Remaining 14.5: authenticated site-report receiver/pull recovery and callback
  release progress; failure-source classification/correlation and the direct
  failure-policy release path; VM buyer stages/CLI and the VM half of 7.4.
  Keep 7.4 unchecked. No fresh-stack e2e, real local payments/mediation journey
  or end/report stage extension is claimed. Shared-kit/client and provisioning
  sources are unchanged; no sibling-domain work was touched. Promotion remains
  16.9 to the lifecycle spec/architecture and VM fulfillment documents.

### VM site/buyer application-wiring checkpoint (2026-11-02)

- 14.5a mounts the compute callback contract under site-bound service-peer
  authentication, verifies the inner site proof against the durable reservation
  and accepted site, and preserves immutable site payloads through push and
  signed typed lease-read recovery. Capacity-return callbacks alone advance a
  delivered deal to released; intended ends stay distinct from proven return.
- 14.5b composes the VM buyer half with the canonical lifecycle client, profile-
  local evidence/end journal and Agreement-bound payment/mediation adapters.
  Hosted approval now hands off with commit; Alkahest settlement is unchanged.
  `market end --from <run>` has no supplied instant, retries stable commands,
  preserves receipt time and reports payment/case/delivery/capacity separately.
  Signed site reports are retained without pretending independent site trust.
  Removed financial configuration cannot prevent receipt-only surrender.
- Application first-use and runnable setup: `docs/attachments/vm-site-report/index.md`.
  It uses signed HTTP, SQLite, vector-derived payments, controlled physical work
  and the actual buyer CLI/stage with injected recovered run context. Missing
  mediation authentication remains explicitly unknown, not accepted mediation.
  The 213 existing buyer cases and 74 focused callback/payment cases pass after
  their peer setup follows commit; no new permanent test or weakened assertion.
  Fresh wheels, architecture, packaging, locks and comments pass. Full
  `make test` passes in 7m15s with the shell-local Podman shim; the final
  application/packaging re-drive passes after recovery-policy hardening too.
  Dependency closure was relocked for buyer/storefront/e2e and the existing release row updated.
  Pinned strict validation passes; scoped citations report only the three known
  future lifecycle spec/architecture references in #325.
- Preparation failures were corrected: rebuild/reinit supplied the new client
  dependency; acceptance artifacts use their wire codec, not alias-free model
  output; the updated HTTP fixture replaces rather than duplicates transport.
  Parent integration supplied the shared report-retry fix, so no overlapping
  kit change was kept. This continuation changes no sibling-domain source.
- Remaining: 14.5c end/report e2e stages and fresh-stack real-authority
  qualification; verified failure-source classification/correlation, pending-
  slot resolution and direct failure-policy release dispatch. Site reports
  currently retain pending classification without blocking physical work.
  Keep 14.5 and 7.4 unchecked. Permanent promotion remains 16.9, to the lifecycle
  spec/architecture, VM fulfillment and buyer-orchestration documents.

### VM failure-source continuation checkpoint (2026-11-02)

- 14.5d connects verified site evidence to accepted deadline/availability facts
  and recorded physical intent keys. Known lawful ends retain both sources;
  unentitled withdrawal and provisioning failure journal their corrections.
  Pending site slots are revisited after authority observation without replacing
  their immutable requests or fixed basis. The lifecycle cycle establishes missed
  delivery deadlines even without a further fulfillment attempt.
- Committed-deal failure-policy release now uses end service. Undispatched
  guarded releases echo their operation key; delivered leases always use lease
  termination and await the separate capacity-return callback, never direct release.
  Capacity held outside committed delivery keeps its existing guarded path.
- Evidence and clean-checkout first use: `docs/attachments/vm-end-classification/index.md`.
  Three in-process encounters cover delayed lawful classification, signed site
  withdrawal and direct failure-policy release through the actual physical port
  with injected site transport. No permanent acceptance test was added.
  The kept release assertion now expects the correlation key, not the former
  generic reason; no release or no-truncation assertion was weakened.
- VM unit/application regressions and both first-use entry points pass. Fresh
  wheels, architecture, packaging, locks, comment hygiene and strict validation
  pass. Full `make test` passes in 7m41s on the final source with the prescribed
  proxy exclusions and shell-local Podman shim, including release tooling and
  Helm checks. An earlier aggregate was stopped before the final physical guard
  and is not counted as passing. Scoped citations report only the three known
  future lifecycle destinations in #325. Initial
  self-check preparation supplied missing public SLA/region fields to the reused
  payment fixture; production listing validation remains unchanged.
- Remaining: 14.5c end/report stages in both VM e2e modules, then fresh branch-built
  qualification through the Podman shim with real local payments and mediation,
  hosted dispute terms, and a real CLI subprocess. No deployed lifecycle scenario
  has run here; 14.5 and parent-owned 7.4 remain unchecked. Unknown site causes
  without controlling evidence remain pending by design; renewable/funding-timer
  and rate execution stay outside this foundation. No external resource is left up.
  Permanent documentation promotion remains 16.9 at reviewed closeout.

### VM fresh-stack qualification (2026-11-02)

- Supersedes the remaining 14.5c boundary above: both existing VM journeys now
  preserve lease-expiry qualification and add a second deal, repeated canonical
  surrender, exact signed site-report verification before provider completion,
  one teardown handle and callback-only capacity release. The CLI journey uses
  real `market negotiate`, `market settle` and `market end` subprocesses; bounded
  end wait/read mode observes current delivery separately from the durable receipt.
- At `5874088d1`, fresh branch-built VM images and isolated empty volumes passed
  Compose and real local payments/mediation readiness. An authenticated registry
  read proved hosted adjudication terms, a 300-second delivery deadline, a
  1,296,000-second dispute window and unbounded case hold. `e2e_deal` passed
  **38/38 stages in 17.18s** and `e2e_deal_buyer_cli` **30/30 in 26.07s**,
  with zero skips. The journeys retain their canonical Alkahest settlement;
  this is delivery-only qualification, not hosted rate-stop or ruling execution.
- Live qualification found that enabling payments broke unrelated Alkahest
  publication when no payment clause was selected. Repair `d2c71b365` returns
  no payment option in that case, with the existing builder regression extended;
  all 97 payments-kit tests, typing, vectors and generated-model checks pass.
  Harness preparation corrections preserve all previous assertions: explicitly
  advance republication, await this deal's dispatch, use typed settlement wait,
  observe release by reservation identity and request the CLI's current view.
- Full `make test` passes in **7m19s** with the Podman shim and prescribed proxy
  exclusions. Harness regression: **316 passed**. Architecture, packaging,
  locks, comment hygiene and pinned strict OpenSpec validation pass. Citation
  checking reports only the three known destinations in #325. Evidence and
  committed readiness entry point: `docs/attachments/vm-end-classification/index.md`.
- Every attempted deployment was removed, with final owned container, volume
  and network inventories empty; external service source is unchanged. No
  resident service remains. 14.5 and 14.5c are checked; **7.4 remains untouched**
  for the parent. Permanent promotion remains reviewed closeout under 16.9.

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

### Bare-metal implementation checkpoint (2026-11-02)

- In-progress storefront composition registers accepted bindings and request evidence in the acceptance transaction, mounts the shared lifecycle router, and connects hosted payment/mediation adapters, seller views, respondent discovery before watch, and the end journal. Admission checks precede reserve, commit, dispatch and disclosure. Terminal settlement and seller refunds enter end service; in-flight create/reserve work retains pending physical effects for adoption/re-drive. Lease windows use the accepted Agreement horizon.
- The committed first-use entry point is `domains/bare_metal/storefront/examples/lifecycle_first_use.py`, run from that package with `PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py` after `make reinit`. It drives hosted commit/list/evidence, repeated signed surrender and wrong-buyer refusal through the mounted typed client, using the existing regression setup and deterministic public development identities. The setup is in-process and self-cleaning, not a domain deployment.
- Existing bare-metal storefront regression: 522 passed. Fresh wheel builds, targeted generated locks, architecture, packaging, lock currency, comment hygiene and pinned strict OpenSpec validation pass. An earlier run exposed missing transaction begin and future fixture readiness timestamps; registration now borrows an explicitly active acceptance transaction and records the seller's own observation time. Waiting for an in-flight create's lock during termination could deadlock the caller controlling that create; end effects now stay pending until the create adopts its result and re-drives them. The mounted first use also caught a missing required claim kind, now supplied by the owning contract.
- This is a checkpoint, not completion of 15.1 or 15.2; both boxes remain unchecked. Before finishing 15.1, complete durable bounded cycle pagination and non-payment physical recovery scheduling, correlate/classify site ends, prove pre-dispatch and create-in-flight admission, and recheck actual commitment timing versus acceptance timing in the delivery record. Before finishing 15.2, mount authenticated accepted-site report receipt/pull recovery, update the release callback's neutral progress, retire the unbegun teardown refusal and move the buyer command to the buyer half/canonical client. The bare-metal half of 7.4 remains unimplemented and its checkbox is untouched.
- No VM production code changed. Mechanical consumer lock refreshes cover `domains/vms/storefront/uv.lock` and `e2e-tests/uv.lock`; the VM worker must retain the joined dependency closure during integration. No configuration model, schema, published distribution row or wire codec was added.
- Full aggregate and fresh-stack domain e2e qualification remain unrun at this checkpoint. Next qualification must build the mock-provisioned lane from the branch, supply ready local payments and mediation with dispute-bearing options, run the domain scenarios, extend the existing end/report stages without adding permanent test functions, and distinguish intended end from proven capacity release. No real-host target exists. No service, container, browser, tunnel or deployment was started.
- Permanent promotion remains reviewed closeout: `openspec/specs/deal-lifecycle/spec.md` and its architecture companion; buyer composition in the buyer-orchestration documents; site report/release semantics in the physical-provisioning and site-capacity documents. Detailed checkpoint evidence is in `docs/attachments/bare-metal-lifecycle/index.md`.

### Bare-metal recovery continuation checkpoint (2026-11-02)

- Supersedes the 15.1 remaining-work list above: 15.1 is implemented. Recovery rotates durable bounded pages and runs through the independent controllable `delivery-recovery` loop even without hosted publication. Physical effects remain pending while reserve/create owns its gate, then re-drive once the returned identity is adopted. Final credential authorization rechecks admission after the live access read. Site reports with the verified seller's exact termination source preserve their controlling lawful request; unentitled withdrawal and non-delivery use the existing filing journal.
- Accepted delivery records no longer mistake negotiation acceptance for payment commitment. A small shared `kit/deal-servicing` seam permits absent `committed_at`, confirms it once from verified evidence without losing earlier ends, excludes uncommitted deals from public seller pages, and gates billing/authorization. Bare-metal verified-evidence persistence binds hosted `approvedAt` in the same transaction. Shared changes are limited to `journal.py`, `seller.py` and `end.py`; no VM source changed, and no dependency/configuration/wire model was added.
- The committed first-use entry point now accepts `before-dispatch` and `create-in-flight`. Both return a durable surrender without waiting for the held operation; the former sends no create and releases its hold, the latter adopts and terminates once. Existing regression remains **522 passed**. Temporary diagnostics prove persisted continuation across a recreated composition and lawful site-end correlation. A diagnostic exposed a shadowed reservation lookup while correlating a report; that is repaired and re-driven. The initial regression's five loop-list failures were updated to include the deliberately added recovery loop, with every previous assertion retained and no new test function.
- Shared servicing-kit typing and all its existing first-use examples pass. Fresh distributions, architecture, packaging, locks, comment hygiene and pinned strict OpenSpec validation pass. Full **`make test` passes in 6m59s**, using the prescribed proxy exclusions and shell-local Podman shim, including **1,858 release-tooling cases** and Helm structural/render checks. The earlier aggregate passed all package suites but exposed missing servicing publication/dependency rows. Separate repair `542b04638` adds the servicing kit once, removes the duplicate mediation entry from the manifest/workflow and records the bare-metal storefront's declared dependencies; its focused release-tooling rerun also passes.
- **Remaining:** 15.2 and the bare-metal half of 7.4 are untouched: authenticated accepted-site callback/pull receipt and proven-release progress, canonical buyer teardown through `BuyerLifecycle` with durable evidence/end journal, hosted buyer commit and existing scenario end/report stages. Leave 7.4's checkbox for the parent. Then build a fresh mock-provisioned stack from the branch, readiness-gate real local payments/mediation and dispute-bearing options, and run `e2e_bare_metal_mock_deal`. That live qualification is unrun; the real-host lane has no operator target. No external runtime, container, server, browser or tunnel was started or remains.
- Evidence and reproducible checkout-owned setup: `docs/attachments/bare-metal-lifecycle/index.md`. Permanent promotion remains reviewed closeout in the destinations above and the design-promotion record; this checkpoint is not independent acceptance.

### Canonical bare-metal buyer and site ingress checkpoint (2026-11-02)

- The buyer stage now approves then sends canonical `commit` through `BuyerLifecycle`, rather than the domain settlement transport. `teardown --run-id` uses the same half with the file evidence store and durable end journal; `delivery --run-id` returns independent delivery/authority views. The domain teardown HTTP route and old settlement transport are removed. Alkahest settlement and contact introduction are unchanged. Exact accepted Agreement bytes/data remain recoverable from canonical negotiation and run-end records.
- The selected site's authenticated callback verifies the service principal and signed report against the owned reservation/site. Recovery reads the original report from that site's authenticated lease read, even after release, because routing bindings are retained. Intended-end reports do not claim release; the release callback or authenticated released lease advances neutral physical progress. Undispatched hold release is completed directly and dispatched work retains teardown progress.
- Existing mounted first use covers commit/surrender replay, wrong buyer/site, report push retries, pull recovery, exact report reads and separate proven release; its before-dispatch and create-in-flight modes pass. The existing CLI integration reopens composition, retries teardown, retains observation/receipt evidence and preserves one physical termination. A synchronous event-loop bridge is required for embedded CLI callers. Mediation credentials are resolved only at I/O, so missing credentials do not suppress surrender or discard a filing awaiting retry.
- Minimal shared fixes are `kit/deal-servicing/ingress.py` (immutable report identity is independent of refreshed push headers or pull's absent headers) and `kit/deal-lifecycle-buyer/ending.py` (an exact seller receipt can acknowledge surrender without an installed dispute adapter, without implying a refund). No VM source or wire/config model changes. Buyer client/contracts dependencies, generated consumer locks and the release-guide row are current.
- Existing domain e2e functions are updated for canonical surrender, original signed reports, intended-end versus proven-release progress, and hosted commit replay. No test function was added or removed. The real-host scenario uses the installed buyer's actual run-ID verbs; it still has no operator-owned host target.
- Validation: full **`make test` passes in 8m10s** with the prescribed proxy exclusions and shell-local Podman shim, including storefront **522 passed**, buyer **16 passed**, lifecycle buyer **18 passed**, e2e harness unit **315 passed**, release tooling **1,858 passed** and Helm render/structural assertions. Servicing-kit typing/all first-use examples, existing payment integration **16 passed** including reopened end/evidence and the callback trust fixture pass. Fresh distributions, targeted generated locks, architecture, packaging, lock currency, comment hygiene and pinned strict OpenSpec validation pass. The existing optional Torch-dependent VM collection skip remains; deployed domain scenarios are not part of this aggregate.
- **Continuation:** 15.2 and the bare-metal half of 7.4 remain unchecked pending fresh-stack qualification. Build the mock lane from this branch, readiness-gate real local payments and mediation plus dispute-bearing publication, run `e2e_bare_metal_mock_deal` and the existing hosted payment scenario, repair/re-drive as needed, and report which scenarios actually ran. Leave 7.4's checkbox for the parent. Evidence/setup and failed-approach notes: `docs/attachments/bare-metal-lifecycle/index.md`. No external runtime, server, browser, tunnel or deployment was started for this checkpoint.

### Bare-metal fresh-stack qualification (2026-11-02)

- Supersedes the qualification remainder above: 15.2 passes. At `892ed4d5d`, the branch-built mock lane, real local payments/Formance/Postgres and mediation reached readiness before pytest; an authenticated listing read confirmed the settlement envelope and the exact served mediation authority, compute deadline, sufficient dispute window and unbounded hold.
- Final clean-exit replay: **`e2e_bare_metal_mock_deal` 39 passed in 13.39s**, **`e2e_bare_metal_payment_deal` 3 passed in 7.88s**, zero skips, with baseline/held/replayed/refunded payment observations all passing. Mock lifecycle stages prove lease expiry, signed report receipt/recovery before release, repeated canonical surrender, capacity reuse and exactly one proven release. The payment scenario proves wallet-free approval/canonical commit, same-payment/fulfillment replay, reversal and separate physical release. Earlier passing mock and hosted attempts are recorded in the packet, not substituted for the final clean-exit result.
- Located fixture defect `892ed4d5d` supplies the previously omitted lifecycle publication parameters and retains all prior assertions; the existing payment scenario now also asserts those terms. Its **315** harness unit cases, packaging and comment hygiene pass. No production source, dependency, configuration model or wire codec changed in this qualification pass. The earlier complete aggregate at the implementation revision passes in 8m10s; it was not rerun after the fixture-only correction.
- All owned containers, networks and ephemeral volumes are removed; the external service source remains unchanged. No browser, tunnel, remote deployment or resident server remains. Evidence and reproduction boundary: `docs/attachments/bare-metal-lifecycle/index.md`. This is implementer qualification, not independent acceptance. Real-host execution still lacks an operator target; rate-stop/case-execution scenarios are not claimed. **7.4 remains unchecked for the parent.** Permanent promotion remains reviewed closeout in the destinations already recorded.

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

## Implementation review 19/20 disposition — domain repair checkpoint

- S-F2 / O-F7: `9061c2062` shares pure compute-family classification, correlates direct release/termination/truncation commands, keeps ambiguity pending and preserves controlling evidence, including failure echoes. `171b08a6a` binds the existing terminal-command assertion to its accepted negotiation. Permanent compute unit and bare-metal application-integration regressions fail under the base behavior and pass after repair.
- S-F3: `2ca4537c7` recovers accepted bare-metal work from the retained mandate independently of current approval policy; permanent application-integration cases cover changed fee policy, removed payment policy, retry, and substituted mandate/payer refusal.
- O-F17: `b905dacdd` corrects the teardown comment to describe the unchanged callback-proven-release assertion; no additional test is needed for a comment-only finding.
- Validation: compute 12 passed; bare-metal storefront 527 passed; VM storefront 1,189 unit passed (one optional collection skip) and 501 integration passed; bare-metal buyer 16 passed. Architecture, packaging, locks, comment hygiene and pinned strict OpenSpec validation pass. The initial full aggregate reached release tooling and exposed two missing shared-compute dependency rows in the release guide; both are repaired in `1fea9839a` and the focused release suite passes (1,858). The full aggregate re-drive passes in 7m04s with the prescribed proxy exclusions and Podman shim, including release tooling and Helm structural/render checks.
- O-F8 continuation (`6172aaac0`): both domain compositions map opaque payer/payee accounts to the accepted buyer/seller and the dispute account to its pinned record signer. The kit remains the ruling actor authority. Permanent domain watch/persistence regressions cover payer, payee, terms, authority stop and ruling; before repair VM fails payer/authority and bare metal fails authority, after repair all 10 pass. No account is interpreted as a marketplace identity.
- O-F9 continuation (`d9e4ddfa2`): both domain watches compose the kit seller-retention observer. Bare-metal verified settlement also records the evidence commitment in the verification transaction, so retention uses post-commitment completion rather than acceptance expiry. Permanent domain integration regressions fail before composition and pass after it; held funds, open cases, incomplete physical recovery, unavailable authority and missing credentials retain evidence, and complete observations permit pruning at the frozen window. The observer computes no payment remedy.
- O-F16 continuation (`ba051e273`): the VM sweep only invokes admission for missed availability deadlines, preserving ongoing admission revisions without suppressing non-delivery filings. Site recovery continues after release until an exact report is retained, then stops lease polling. Permanent integration regressions fail on both old behaviors (revision churn and a third released-reservation read); the repaired cycle and report recovery pass.
- Remaining in this domain assignment: remaining O-F1 section 14/15 permanent domain tests; O-F18 fresh-stack hosted VM payments/mediation qualification. Delegated seams: O-F12 credential-independent adapter signing (its owner is completing the isolated domain callbacks) and O-F10 off-loop site ingress. These remain pending, not waived or reclassified as evidence-only work. The domain watches consume the shared kit retention observer and ruling attribution. The VM sweep avoids redundant admission calls rather than modifying the parallel kit's journal; its missed-deadline admission remains intact.
- Whole-finding checkpoint validation at `ba051e273`: all 14 new focused integration cases pass; architecture, packaging, locks, comment hygiene and pinned strict OpenSpec validation pass. The required validation sequence, including the full `make test` with proxy exclusions and Podman shim, passes in 8m34s: VM storefront 1,189 unit (one optional collection skip) and 509 integration; bare-metal storefront 533; VM buyer 213; bare-metal buyer 16; e2e harness 316; release tooling 1,858; Helm structural/render checks. No dependency declaration changed, so no relock was required and no lock changed.
- Checkpoint scope: O-F8/O-F9/O-F16 are whole and committed; O-F1 sections 14/15 and O-F18 remain as specified. The initial retention fixture tried to re-accept an existing envelope with changed author/expiry and was correctly refused; the kept case preserves the real acceptance. No deployed hosted VM qualification has been attempted in this continuation, and no external runtime was started. The next session must retain the named permanent-test and fresh-stack criteria rather than amend them away.
- Reproduction, observations and approach limits: `docs/attachments/aeet-review-domain-repairs/index.md`. No live hosted end-to-end or real-hardware result is claimed. Permanent promotion remains reviewed closeout in the existing owning specifications/architecture destinations.

### O-F1 permanent-domain-test continuation

- Keep every section 14/15 Verify clause and completed task; no scenario is
  amended away. Normal pytest discovery now owns VM hosted acceptance, end
  admission/restart, second-precision ends, both admin branches, signed site
  push/retry/pull and buyer-half capture, plus bare-metal create-in-flight,
  owner/site refusal, repeated teardown and callback-only release. The exact
  file/property map and direct first-use command are in
  `docs/attachments/aeet-domain-permanent-tests/index.md`; existing list,
  payment/refund/terminal and recovery regressions are retained and cited.
- The permanent unentitled-admin encounter found a real ordering race: the
  off-loop submit could record its end after physical lookup had returned.
  SellerServicing exposes local recording separately; VM awaits it before
  driving teardown and filing independently. The authority-gated regression
  fails under the old ordering and passes after repair, without sleeps.
- The VM payment example asserts pending/provisioning/ready rather than only
  printing. Its pre-delivery surrender assertion follows the accepted
  `delivered=true` receipt contract; admin/site examples retain their proof
  and dispatch checks with credential-independent signing and earlier-end
  suppression of an automatic payer claim.
- O-F1 section 14/15 permanent-test work is complete: final focused VM 50 and
  bare-metal 7 cases pass; servicing 48 and typing pass; all asserted domain
  first-use examples pass. Architecture, fresh-wheelhouse packaging, locks,
  comment hygiene and pinned strict OpenSpec validation pass. The complete
  required chain, including shim-backed `make test`, passes in 8m44s: VM
  storefront 1,196 unit (one optional collection skip), 520 integration;
  bare-metal storefront 538; VM buyer 213; bare-metal buyer 16; e2e harness
  316; release tooling and Helm structural/render checks. Final test-only
  refinements pass the focused re-drive. No lock/dependency changed.
  Promotion remains reviewed section 16 closeout, not part of this repair.
- O-F18 remains a whole outstanding item: extend and run hosted VM commit,
  servicing and an end with its case on a fresh owned stack with real local
  payment/mediation, readiness-gated before pytest and fully torn down. An
  early shim-backed image build succeeded, but predates the admin-ordering
  repair and must be rebuilt from the committed branch before qualification.
  No deployment, authority service or e2e stage was started.

### O-F18 hosted VM continuation

- `e2e_vm_payment_deal` extends the VM lane with hosted-only negotiation,
  verified approval and canonical commit, same-key replay/servicing,
  unentitled administrator end with one mediation case, then seller refund
  and callback-proven release. The existing Alkahest journeys are unchanged.
- The real authority exposed first-filing deadlock: the semantic-case read
  received initial 404 before the authority knew the Agreement. `eac70ec3d`
  permits that absence only to prepare the original filing, never as verified
  empty history for ordinary reads or an acknowledgement without a signed
  filed record. The kept semantic-recovery regression models that boundary;
  the old-call-path diagnostic fails, repaired mediation 45 and typing pass.
- Fresh shim-backed images from `eac70ec3d` include both that repair and the
  admin-ordering repair. Owned Compose, host/seller/buyer payments, mediation
  and signed dispute-bearing publication passed readiness before pytest.
  All four deployed stages pass in 10.09s with zero skips. The authority
  source remained read-only, every attempted deployment was torn down and
  both exact leaked build children (#326) were stopped by their supervisor.
- Harness 319, comment hygiene, fresh-wheelhouse packaging/architecture/locks
  and pinned strict OpenSpec validation pass. Full shim-backed `make test`
  passes in 7m51s on the final production source, including release tooling
  and Helm structural/render checks (one existing optional Torch collection
  skip; zero skips in the hosted journey). O-F18 is qualified. Setup, stage
  observations and limits are in
  `docs/attachments/aeet-vm-hosted/index.md`; no rate/funding or real-hardware
  result is claimed. Permanent promotion remains reviewed section 16 closeout.

## Design promotion record

Planned destinations below; promotion is not performed during this design reconciliation.
The remaining D1–D15 destinations are listed in proposal.md and task 16.9.

| Accepted decision | Permanent location |
|---|---|
| Initial missing mediation history permits the first filing only, not a verified empty ordinary read or unproved case acknowledgement | `kit/arkhai-mediation/README.md` now; existing deal-lifecycle spec/architecture ownership at reviewed closeout (16.9) |
| Mediation owns installed published schema/models/vectors and marketplace claim framing; its stateless adapter only communicates with the exact Agreement authority, preserving aggregate monetary answers without computing remedies | `openspec/specs/deal-lifecycle/spec.md` and `architecture.md`, and `docs/development/ARCHITECTURE.md` kit areas at closeout (16.9) |
| D5 Alkahest release-model list, option-owned release conditions, undeliverable-model startup refusal and atomic legacy-flag migration | `docs/development/DEPLOYMENT_AND_CONFIG.md#alkahest-release-models` and `docs/development/ARCHITECTURE.md` readiness boundary; settlement-configuration delta promoted at 16.9 |
| D5 price/settlement/lifecycle option envelope, canonical identity, selection mirror and forward-only registry paths | Settlement-configuration and negotiation-protocol spec deltas; lifecycle ownership in deal-lifecycle spec/architecture, promoted at reviewed closeout (16.9) |
| D6 neutral authorization/evidence envelope, sole end-service billing-start intent; D8 cause classification, pre-start timing exception and revised-remedy netting | New `deal-lifecycle` spec/architecture and settlement-servicing spec/architecture at closeout |
| D8 receipt-embedded SignedDeliveryEndClaim, buyer concurrence/stop retry and both CLI paths | `openspec/specs/buyer-orchestration/spec.md` and `architecture.md` |
| D5 premature-stop penalty codec and D10 capped held-earnings remedy; D10 one payee-agreed delivery_end rule for either filer, receipt concurrence and durable respondent sign-or-contest; D8 delivery_end filing and stable keys; D9 retained signed evidence; D10 case-carried Agreement and human triage | New `deal-lifecycle` capability's spec and architecture companion (created at archive/closeout) |
| D8 site-signed intended-end report, transactional event/outbox and recovery; canonical payload framed under `arkhai.site.lease-ended.v1`, stored proof preserved across retries/pull, per-peer unsupported parking and explicit resumption | `openspec/specs/site-capacity/spec.md`, `openspec/specs/physical-provisioning/spec.md` and their architecture companions |
| D5 coherent hosted contract selection and generated installed resources; one shared clock-injected payments fixture engine | `kit/arkhai-payments/README.md` (current API); settlement-servicing spec/architecture and `docs/development/TESTING.md` at closeout |
| D8 intended end versus proven release; terminate versus future truncate | `docs/development/ARCHITECTURE.md`, "Site authority", "Fulfillment status and results", "Release"; `openspec/specs/site-capacity/architecture.md` |
| D8 VM buyer end and second-precision lease effects | `openspec/specs/vm-storefront-fulfillment/spec.md` |
| Ordered dispute preferences, local identity vetoes, identity-bound credential references and opt-in registry recommendations | `docs/development/DEPLOYMENT_AND_CONFIG.md#dispute-authority-preferences` and its registry descriptor section; payment kit README, seller quickstart and e2e runner guide. Normative settlement-configuration/registry-discovery spec deltas and lifecycle architecture promotion remain at reviewed closeout (16.9) |
| Codec-owned common lifecycle query projections, absent-value semantics and same-option asset correlation | `openspec/specs/cli-query-language/spec.md` and `openspec/specs/settlement-configuration/spec.md` at closeout |
| Per-part absolute ends, stop-relative dispute holds and exact rights-derived authority/cap derivation; setup once permissions remain independent of rate rights | `kit/arkhai-payments/README.md`; settlement-servicing spec/architecture and deal-lifecycle spec/architecture at reviewed closeout |
| Hosted publication selects compatible offered authority projections; shared registry destinations use their ordered intersection; API-credit selection and approval check full accepted identities | `kit/arkhai-payments/README.md`; storefront-publication, settlement-configuration and buyer-orchestration spec deltas and lifecycle architecture at reviewed closeout |
| Bounded current/retiring receipt identities and snapshot attestation/cursor verification before state consumption | `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover`; settlement-servicing spec/architecture at reviewed closeout |
| Accepted delivery metadata does not establish commitment: the verified-evidence transaction fixes the payment authority's approval instant once, preserves earlier ends and gates seller committed-deal pages; bounded recovery runs independently of payment publication | `openspec/specs/deal-lifecycle/spec.md` and its architecture companion at reviewed closeout |
| D6 VM administrator dispatch follows accepted payee rights; exceptional ends retain administrator/reason and drive physical teardown independently of the journaled authority filing | `openspec/specs/deal-lifecycle/spec.md` and its architecture companion, with VM fulfillment ownership at reviewed closeout |
| Lifecycle distributions participate in public publication with their declared dependency order | `docs/development/RELEASING.md` and `manifests/published-distributions.json` |

## Implementation review 19/20 disposition — servicing

- **S-F4, S-F5** — `f0b7f5ce2`: last verified records and current read outcomes
  are separate; first-read failure, outage, verification rejection, recovery and
  empty/shorter full-history replays have permanent integration coverage.
- **O-F3, O-F4, kit O-F8, O-F10** — `243ed8c51`: unresolved respondent cases
  remain visible/retryable without blocking account discovery; respondent answers
  cannot be preempted by watch; ruling actors retain the pinned record signer;
  asynchronous database units run off-loop and admission CAS follows unlocked
  financial I/O. The same transaction protects the optional local delivery write.
- **Kit O-F9** — `8bb7bb8eb` and `243ed8c51`: complete adapter-owned financial
  completion projection, conservative shared seller retention observer, async
  evidence observe/prune API, and seller refresh-before-prune. Domain observer
  composition and synchronous ingress-call offloading belong to the domain repair.
- **O-F1, sections 10 and 13** — `f0b7f5ce2`, `8bb7bb8eb`, `243ed8c51`,
  `4510feb50`: `kit/deal-servicing` has a normal test target in the repository
  aggregate (and therefore CI), with 39 permanent tests at the unit/library or
  mounted-application boundary. Tests cover acceptance authors/exact evidence,
  retention, admission/end/restart races, journaled billing and physical replay,
  corrections/deferred filings, independent watch cursors/extensions/append races,
  seller pages/credentials/operator ends, signed typed-client routes, authentication,
  relay/backdate/future refusal, authority-outage surrender/retry and exact
  owner-only report reads; budget warnings do not stop cycles. Every printed
  first-use outcome now asserts. These tests replace the earlier checkpoint's
  temporary-only verification, not its implementation history or named criteria.

Validation: 39 servicing tests, 98 payment tests, typing and all asserted first-use
examples pass. `make lock`, architecture, packaging, locks, comment hygiene and
strict pinned OpenSpec validation pass. The full `make test` aggregate passes in
8m19s with the required proxy environment and Podman shim.

Reproducible first use and sensitivity evidence:
`docs/attachments/aeet-servicing-review-fixes/index.md`. Current API documentation
is `kit/deal-servicing/README.md`; review implementation rationale is in `design.md`.
Permanent specification/architecture promotion remains in the existing
post-code-review closeout, with no owner decision reopened.

## Implementation review 19/20 disposition

### Lifecycle filing and buyer-end repairs

| Findings | Disposition and commits |
| --- | --- |
| S-F1 / O-F2 | `33d777ba0` reserves one original semantic delivery-end writer in caller-owned durable storage and adopts one equivalent signed case. `3531af8b0` correlates seller-failure site echoes without another filing; `15c0d39f8` proves concurrent adoption across reconstructed SQLite callers. Unsupported revisions/ambiguous or unresolved originals return repair required; the published API cannot safely map linked revisions, so SCM refuses rather than computes a monetary delta or allocates a new key. |
| O-F5 / O-F6 | `ac139c842` retries uncertain surrender before fixing a case and skips automatic payer filing for a non-surrender selected end. `3531af8b0` signs concurrence only for the selected surrender. The signed client accepts withdrawal of concurrence when newly selected earlier evidence supersedes surrender. |
| O-F11 | `3531af8b0` makes rejected filings terminal, exposes every intent/outcome through read/list, and marks repair required after restart instead of resubmitting forever. |
| O-F12 | `eccc87ea1` supports credential-independent local claims through the pinned mediation adapter. `d65e98e86` dispatches both compute receipt callbacks through their selected adapter tables; absent adapters return no claim. Read-only binding lookup remains safe inside ingress's write transaction. |
| O-F13 | `211e29f7b` removes the unused duplicate receipt-store/no-adapter helpers and their helper-only assertions. Kept public receipt persistence, retry and no-adapter delivery assertions are exercised through the real servicing/client surfaces. |
| O-F14 | `3531af8b0` fixes never-delivered claims at Agreement start, including a pre-start failure recorded late. The design/delta correction reconciles the old minimum expression with mediation's at-or-after-start guard; no filing is future-dated. |
| O-F15 | `3531af8b0` validates operator payload/time before consuming its operation key, allowing a corrected retry. |
| O-F1 client seam | `ac139c842` adds the signed client's permanent suite and test target; `299adfd7c` wires it into the repository aggregate and asserts mediation first-use outcomes. The parallel servicing owner supplies that kit's aggregate target. Named verification tasks remain unchanged. |
| O-F16 requested kit seam | `cf580bb6f` avoids a revision write on unchanged phase admission while retaining end/deadline checks. Compute cycle/report recovery is owned by the parallel domain repair. |

The review corrections are recorded in `design.md`, the deal-lifecycle and
buyer-orchestration deltas, and the affected kit READMEs. Subsystem-spec and
architecture promotion remains the reviewed closeout work at 16.9; no roadmap,
campaign status or archival transition is made by this repair round.

Evidence and reproducible first use:
`docs/attachments/aeet-review-19-20-fix-a/index.md`. All behavioral regression
checks were run against the reviewed source and fail before their repairs.
Focused checks pass: contracts 37, foundation 61, mediation 45, buyer 20, signed
client 2, servicing 9, and 3 receipt-adapter checks in each compute domain.
Mediation resource/model checks and mediation/servicing typing pass. `make lock`
was run after the client test dependency; check-locks is part of qualification.
The final-head `make check-architecture`, `make check-packaging`, `make
check-locks`, `make check-comment-hygiene`, strict OpenSpec validation and full
`make test` all pass (combined chain 7m 41s with proxy exclusions and the Podman
shim). The preceding complete chain also passed. No hosted mediation deployment
or deployed monetary-ruling qualification is claimed by this kit repair.

## Re-review 21/22 disposition — buyer and servicing kit

Implementation evidence and clean-checkout replay:
`docs/attachments/aeet-fix2-kit-buyer/index.md`. These refinements retain the
existing closeout promotion destinations; no authority or financial policy
changes are introduced. Validation: servicing 61 passed plus mypy (11 files),
buyer lifecycle 20 passed, signed client 2 passed, both real buyer-port checks
passed, semantic-filing checks passed, and first-use examples passed. Architecture,
packaging, locks, comment hygiene and pinned strict OpenSpec validation passed.
Full `make test` passed in 7m59s with the prescribed proxy environment and Podman
shim. No hosted deployment or independent acceptance verdict is claimed.

- **E-N7:** Operator end returns only its own filing result (or accepted local recording if superseded), repair reasons have one prefix, and buyer filing uses only the acknowledged receipt without unreachable observed-time fallbacks or a redundant contested flag. Kept journal plans still decode the obsolete field. Regressions cover unrelated terminal filings, exact diagnostics, receipt-backed recovery, and retained-plan replay.
- **E-N5:** Respondent discovery drops cases with no local registered commitment, including inherited foreign repair rows; a locally registered but temporarily unresolved Agreement remains repairable. The bounded repair queue uses insertion order and moves a failed attempt to the back. Regressions cover shared-account foreign/local cases across reconstruction and fair local retry rotation.
- **E-N3 / O-F6 respondent:** Payer concurrence now requires the matching buyer request to be the selected end. The real signed respondent regression records an earlier seller failure, then proves the explicit payer claim receives contesting end evidence rather than concurrence. Receipt and automatic buyer suppression remain unchanged.
- **E-N1:** An unresolved semantic writer now returns `Pending`, not terminal rejection; authority refusals and unsupported revisions remain terminal. The real seller/mediation regression loses the original write before receipt, reconstructs dispatch, and proves both required same-basis callers adopt one signed case with no permanent repair state. Existing concurrency expectations now distinguish retryable ownership from terminal refusal.
- **S-N2 / E-N6:** `resolve_correction` accepts a verified controlling source, validates its classification/end and existing filing, and adopts it without rewriting the original request. Both domain correction callers pass the one new optional keyword; no other domain behavior changes. SQLite regressions cover delayed lawful/nonlawful sources, delivered/undelivered state, reconstruction, replay, and invalid controllers.
- **E-N2:** Only a selected source journals a seller filing. Later superseded requests remain immutable evidence; a genuinely earlier late source still journals a revision. Regression proves both orderings and same-key replay. The terminal-refusal fixture now uses two successively selected failures rather than manufacturing an unnecessary later filing.
- **S-N1:** Both lazy buyer mediation ports forward `case` without eager credential resolution. Each buyer package now drives lost-filing-response recovery through its real port and reconstructed evidence store, asserting one signed authority case. Before the repair both tests failed at the missing `case` operation.

### Parallel repair integration checkpoint

- `7fb2dae69` merges the lifecycle repair into `8b1a5cfb5`, preserving the
  domain and servicing disposition notes. Seller reads combine current authority
  outcomes with respondent and filing repair state; dispatch retains per-filing
  progress and terminal rejections while keeping database work off-loop. Both
  servicing and signed-client targets remain in the kit aggregate.
- `1d713730c` makes both receipt callbacks' immutable binding reads schema-free.
  The first aggregate exposed schema initialization on a second connection under
  ingress's write lock; all six unchanged domain receipt-adapter checks pass after
  the repair. The deferred-filing assertion follows the per-filing result shape
  and still requires the exact pending filing and no authority submission.
- Validation: `make dist`; servicing 48, foundation 61, buyer 20, signed client 2,
  mediation 45 and payments 98 tests; servicing typing and all nine asserted
  first-use examples; mediation typing/resources/models and asserted first use;
  architecture, packaging, locks, comment hygiene and strict pinned OpenSpec
  validation pass. The full `make test` re-drive passes on `1d713730c` in 7m26s
  with the prescribed proxy exclusions and Podman shim, including release tooling
  and Helm structural/render checks.
- Setup, observations and reproduction:
  `docs/attachments/aeet-fix-a-integration/index.md`. This integrates the parallel
  kit repairs, not the remaining domain work or reviewed closeout promotion.
