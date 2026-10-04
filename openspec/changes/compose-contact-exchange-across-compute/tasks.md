# Tasks — compose contact exchange across the compute family

Depended on `contact-payload-retention` and `pass-through-storefront-config`, both
complete and archived. Task 6.5 is transferred to `unbacked-bare-metal-listings`.
Decisions are in `design.md` (1–14).

Paths abbreviate `kit/contact-exchange/src/market_contact_exchange/` as `KC/`,
`kit/delivery/src/market_delivery/` as `KD/`,
`domains/vms/storefront/src/market_storefront/` as `VM/`, and
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` as `BM/`.

Order: Sections 1–2 promote and must leave bare metal's suites green before Section 3
composes VM. Sections 3b, 4, and 4a may proceed in parallel after Section 2.

## Review corrections

Section 8 records the corrections an implementation review and an architecture
review asked for, and the VM negotiation defect found while making them (8.8). The
end-to-end scenario (`test_vm_introduction.py`) and the Helm fixture
(`helm/fixtures/contact-exchange-values.yaml`) are iterated separately.

## 1. Survey and placement

- [x] 1.1 Separated bare metal's introduction composition into domain-neutral parts
      (accepted-state interpretation, `obligation_ref` re-derivation, the drive
      sequence, `load_revealed_introduction`, introduction persistence over the kit's
      own table, the retention/disclosure/reveal wiring in `BM/runtime.py`) and
      domain parts (thread and obligation reads, configuration carrier, routes,
      authorization adapter, loop registration). The same split for `BM/delivery.py`
      and the bare-metal buyer's `introduce` and `introduction`.
- [x] 1.2 Promote into `KC/composition.py` with the thread, obligation, and origin
      reads as Protocols (`design.md` decisions 2, 3, 13).
- [x] 1.2a Add `uuid` and `typer` to the permitted roots in
      `kit/contact-exchange/tests/unit/test_package_boundary.py`; the deny list is
      unchanged.
      The boundary test is an allow-list; `pathlib`, `uuid`, and `typer` are on it.
- [x] 1.2b Recorded: not `kit/storefront`, which hard-depends on Alkahest.
- [x] 1.3 Recorded: VM only; API credits is out of scope (`design.md` decision 11).
- [x] 1.4 The VM process resolves only mode `vm` for its services; the `bare_metal`
      contribution in its registry is used for binding resolution only, so registering
      contact exchange in `VM/settlement_composition.py` affects VM listings only.

## 2. Promote

- [x] 2.1 `KC/composition.py`: the accepted-state bodies from `BM/introduction_routes.py`,
      moved unchanged except for the injected origin read; `load_revealed_introduction`
      with them.
- [x] 2.2 `KC/store.py`: `SQLiteIntroductionStore(db_path)` with async `insert`,
      `load`, `delete_payloads`, and `select_expired` over `KC/migrations.py`'s row
      functions, replacing the four wrappers in `BM/sqlite_client.py`.
- [x] 2.3 `KC/composition.py`: `ContactExchangeComposition`, built from the running
      configuration getter, the store, the three reads, the settlement runtime, the
      known origins, and an optional seller dispatch. It yields the reveal service for
      an authorizer, the retention service, the disclosures, and the redelivery read.
      Replaces `contact_settlement_config`, `introduction_retention`, and the
      disclosure wiring in `BM/runtime.py`.
      `ContactExchangeComposition` also yields `seller_view`, the read re-delivery uses.
- [x] 2.4 Export the new surface from `KC/__init__.py`.
- [x] 2.5 Move bare metal onto it: `BM/introduction_routes.py` and
      `BM/runtime.py` reduce to composition; `BM/api.py` keeps routes and
      `_authorize_introduction_request`; `BM/server.py` keeps loop registration;
      `BM/sqlite_client.py` loses the wrappers.
- [x] 2.6 **Kit integration.** `kit/contact-exchange/tests/integration/test_composition.py`
      over a real introduction table with injected reads and runtime: each refusal
      the glue makes, the mismatched-reference refusal, the store's round trip and
      deletion, keyed and single-form resolution, and the composition's outputs.
      Configuration, resolver, readiness, and option-builder rules are unit-tested in
      `kit/contact-exchange/tests/unit/test_settlement_config.py`. The store has no
      file of its own; it is exercised through the composition test.
- [x] 2.7 **Unchanged coverage.** `domains/bare_metal/storefront/tests/test_http_introductions.py`,
      `test_introduction_delivery.py`, `test_persistence.py`, `test_http_system.py`, and
      `test_app_composition.py` pass against the promoted implementation before
      Section 3 starts.

## 3. Compose VM

- [x] 3.1 `VM/settlement_composition.py`: register `create_contact_registration()`;
      add `"contact-exchange.v1": False` to the per-mechanism fulfillment declaration.
- [x] 3.2 `VM/utils/sqlite_client.py`: the contact-exchange migrations in the migration
      tuple beside `*settlement_migrations()`.
- [x] 3.3 `VM/container.py`: build the `ContactExchangeComposition` from VM's
      settlement configuration, `SQLiteIntroductionStore`, the inherited
      `load_negotiation_thread_row` / `load_thread_binding` reads, the settlement
      runtime, and the keys of `[capacity.sites]` as known origins.
- [x] 3.4 `VM/controllers/introductions_controller.py` (new): `POST /api/v1/introductions`
      and `GET /api/v1/introductions/{obligation_ref}` over the kit reveal service, with
      an authorization adapter on `core_storefront.auth.authenticate_request` that
      allows the buyer and seller roles and sets `request.state.marketplace_authenticated`.
      Mount it in `VM/server.py`.
- [x] 3.5 `VM/middleware/seller_auth.py`: `_buyer_response_contract` signs and records
      both introduction routes, as it does for the hosted settlement routes.
- [x] 3.6 Confirm composition is independent of backing in both directions.
- [x] 3.7 **Integration.** `domains/vms/storefront/tests/integration/test_introduction_origins.py`
      on the VM publication harness (`domains/vms/storefront/tests/publication_app.py`),
      an in-process composition: the production routers, middleware, and container
      wiring over real SQLite, contact exchange with a real settlement runtime, and a
      stand-in only for Alkahest artifact construction. It is not the storefront's own
      app factory and lifespan; those, and the real buyer CLI against deployed
      services, are exercised by the system runs in 6.3, 6.4, and 6.6. It drives
      `core_buyer`'s `IntroductionTransport` over loopback
      (`domains/vms/storefront/tests/loopback.py`): a published listing is negotiated
      to acceptance under the default policy chain, revealed and re-read with the
      seller's signature verified by the transport, and a reveal against another
      obligation is refused with no payload. The VM buyer's own negotiation client,
      as `request-introduction` runs it, reaches agreement with no amount when the
      seller accepts the unpriced selection at the opening. Exact-retry replay is covered by the
      kit's reveal-service unit tests and bare metal's typed-client tests.
## 3a. Retention

- [x] 3a.1 `VM/lifecycle.py` and `VM/lifecycle_steps.py`: an `introduction-retention`
      loop with step and preview over the kit sweep; started from `VM/startup.py` on a
      configurable interval.
- [x] 3a.2 `VM/controllers/admin_controller.py` and `VM/middleware/admin_identity.py`:
      the kit's admin deletion route behind administrator authentication, with its
      route contract.
- [x] 3a.3 `core/storefront/src/core_storefront/models/system_models.py`:
      `HealthResponse.disclosures`; `VM/services/system_service.py` fills it from the
      composition when the mechanism is enabled, for `/health` and
      `/api/v1/system/health`.
- [x] 3a.4 **Integration.** `domains/vms/storefront/tests/integration/test_introduction_retention.py`
      on the same harness, through typed clients only: the `/health` disclosure
      matches the reveal's; admin deletion through its route and administrator
      authentication converges, leaves the obligation resolvable, and turns read and
      start into the deleted outcome; the `introduction-retention` dry-run names
      exactly the expired introduction and run-cycle deletes it. Operator
      re-delivery after deletion is shown at composition level: its `seller_view`
      read raises the deleted outcome, so no sink can be reached.
## 3b. Per-origin contact resolution

- [x] 3b.1 `KC/settlement_config.py`: `origins` tables with a non-empty
      `contact_payload`, bounded keys and count; `contact_payload` stays the single
      form. Both carry `"never_published": true` instead of `"secret": true`
      (`design.md` decision 13).
- [x] 3b.1a `KC/settlement_config.py` `contact_preflight`: unready on no profiles or no
      contact in either form, otherwise ready; nothing per origin in the projection.
- [x] 3b.1b `kit/settlement-runtime/src/market_settlement_runtime/configuration.py`
      `_secret_values`: collect `never_published` fields too, so the readiness leak
      check covers them. `VM/values_schema.py`: add `never_published` to the stripped
      annotations.
- [x] 3b.2 `KC/settlement_config.py`: `validate_contact_origins(config, known_origins)`
      with decision 4's three refusals; called from `KC/composition.py` at
      construction.
- [x] 3b.3 Option builder: take `origin` from publication resources; no option when it
      resolves no contact, refuse when the keyed form has no origin, no option when no
      clause selects contact. `VM/services/listing_service.py`: in `create_listing`,
      read the capacity source's site before `_derive_settlement_artifacts` and pass it;
      in `reconcile_settlement_options`, pass the stored binding's site.
      `BM/publication_composition.py`: pass `candidate["site_id"]`.
- [x] 3b.4 `KC/introduction_routes.py`: `IntroductionAgreement.origin`; the service
      takes a contact resolver instead of `seller_contact`; HTTP 503
      `seller_contact_unavailable` before persisting. Remove `BM/api.py`'s
      storefront-wide 503 check.
- [x] 3b.5 A single-origin deployment configured with the single form resolves to its
      configured value.
- [x] 3b.6 **Unit.** `kit/contact-exchange/tests/unit/test_settlement_config.py`: forms,
      empty-entry refusal, every startup refusal, readiness under each form, resolver,
      option suppression and fail-closed refusal, and that a never-published value in
      a readiness projection is refused.
- [x] 3b.7 **Integration.** `test_introduction_origins.py`: one listing's published
      binding, its negotiation's inherited binding, and the revealed contact all name
      the same site; two sites behind one storefront each reveal their own contact.
- [x] 3b.8 **Integration.** Same module: a site with no contact publishes no
      introduction option; a reveal for a deal whose site lost its contact after
      acceptance is refused with nothing persisted or driven.
## 4. Delivery

- [x] 4.1 `KD/config.py`: named instances with `sink`; a table without `sink`
      instantiates its own name; an instance named for one sink stating another is
      refused; reserve `origins`; a `role` argument to `load_delivery_config`.
- [x] 4.2 `KD/config.py`: the seller-side `[Delivery.origins]` table and its refusals,
      including the unconditional multi-origin refusal; refuse a routing table on the
      buyer side.
- [x] 4.3 `KD/seller.py` (new): background dispatch with task retention and outcome
      logging, sink-set construction with warnings, routing by the agreement's origin,
      and re-delivery, reading reveal and agreement by shape. `KD/discovery.py`:
      instantiate by `sink`.
- [x] 4.3a `KD/builtin/webhook_sink.py`: `sign = true` signs with a signer passed by
      the sink-set builder; refused without one.
      The marketplace v2 header names are restated in the delivery kit, as eight
      packages already do, rather than adding a client dependency.
- [x] 4.3b `kit/delivery-apprise/` (new distribution `arkhai-kit-delivery-apprise`,
      package `market_delivery_apprise`): an `apprise` sink with secret-marked `urls`,
      registered on the `market.delivery_sinks` entry point; README, tests, lock.
- [x] 4.4 Bare metal onto the kit: `BM/delivery.py` reduces to loading its environment
      carrier; `BM/cli.py`'s re-delivery calls the kit.
- [x] 4.5 VM: `VM/utils/config.py` reads `[Delivery]`; `VM/container.py` builds the
      seller dispatch with the storefront signer and known origins; `VM/cli.py` gains
      `redeliver-introduction`.
- [x] 4.5a `VM/values_schema.py`: type `[Delivery]` (`design.md` decision 13) and
      regenerate `helm/charts/storefront/values.schema.json` and
      `helm/values.schema.json` with `make helm-values-schema`;
      `domains/vms/storefront/tests/unit/test_values_schema.py` gains the delivery and
      contact cases.
- [x] 4.6 Confirm delivery stays non-authoritative and re-delivery routes by origin.
- [x] 4.7 **Unit.** `kit/delivery/tests/unit/test_config_and_discovery.py`,
      `test_builtin_sinks.py`, and new `test_seller.py`: instance parsing including
      pre-instance configurations, two instances of one plugin, misnamed instances,
      routing and every refusal including the multi-origin refusal, a shared
      destination, signing, and dispatch outcome reporting.
      `kit/delivery-apprise/tests/`: settings, secret marker, and delivery to a
      loopback `json://` receiver.

## 4a. Buyer introduction commands

- [x] 4a.1 `KC/buyer_commands.py` (new): `create_contact_command_group(context_factory)`
      with `introduce` and `introduction [--deliver]`; the context supplies the
      transport, run recovery, and buyer sinks.
      Mounted as `market settlement contact introduce` and `… introduction`; bare
      metal's own copies are removed.
- [x] 4a.2 Bare-metal buyer: mount the group through its settlement registry or
      settlement app in `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`,
      remove `introduce` and `introduction`, keep `request-introduction`.
- [x] 4a.3 VM buyer: register contact with its command group in
      `domains/vms/buyer/src/arkhai_vms_buyer/settlement_composition.py`; add
      `request-introduction` in a new `introduction_cli.py` mounted from `cli.py`.
- [x] 4a.4 **Unit.** `kit/contact-exchange/tests/unit/test_buyer_commands.py` against an
      injected context, including the deleted outcome and sink failure;
      `domains/vms/buyer/tests/test_introduction_cli.py`;
      `domains/bare_metal/buyer/tests/test_buyer_composition.py` updated.

## 4b. Deployment

- [x] 4b.1 `domains/vms/storefront/storefront.bob.toml`: contact exchange enabled with
      one profile, `origins.default`, priority entry; `[Delivery]` with an SMTP instance
      to Mailpit routed for `default`.
- [x] 4b.2 `domains/vms/compose.yml`: a `mailpit` service on the market network.
- [x] 4b.3 `helm/charts/dev-env/`: an optional Mailpit Deployment and Service
      (`mailpit.enabled`, default false).
- [x] 4b.4 `helm/fixtures/contact-exchange-values.yaml` (new): enables contact
      exchange and SMTP delivery to Mailpit for Bob, and Mailpit in `dev-env`;
      `helm/charts/storefront/tests/test_render.py` asserts the sections render intact
      and a secret-marked sink field is refused.
      The render cases pass in the 2026-10-04 Helm run (`helm/test-render.log`), and
      the committed schema is validated against real documents by
      `domains/vms/storefront/tests/unit/test_values_schema.py`.
- [x] 4b.5 Both storefront images install `arkhai-kit-delivery-apprise`
      (`domains/vms/storefront/pyproject.toml`, `domains/bare_metal/storefront/pyproject.toml`).
- [x] 4b.6 Version bumps and pins: `kit-contact-exchange` 0.2.0, `kit-delivery` 0.2.0,
      `kit-settlement-runtime` next minor, `core-storefront` 0.7.0,
      `kit-capacity-publication` 0.3.1, `bare-metal-storefront` 0.7.0,
      `vms-storefront` 0.9.0, `bare-metal-buyer` 0.4.0, `vms-buyer` 0.5.0,
      `apicredits-storefront` 0.5.1; every exact pin of a bumped package updated; then
      `make lock`.

      Also bumped by later tasks: `kit-settlement-runtime` 0.2.0, `kit-config` 0.1.3,
      `kit-hosted-settlement` 0.1.5, `core-buyer` 0.3.3, `kit-policy` 0.2.0,
      `kit-negotiation-runtime` 0.2.1, `vms-negotiation` 0.3.0; every exact pin is
      updated. Locks are regenerated; see 7.10.
## 5. Specification and documentation

- [x] 5.1 Promote the `contact-exchange-settlement` delta into
      `openspec/specs/contact-exchange-settlement/spec.md`.
- [x] 5.2 Promote the `introduction-delivery` delta into
      `openspec/specs/introduction-delivery/spec.md`.
- [x] 5.3 `docs/development/DEPLOYMENT_AND_CONFIG.md`: the contact-exchange section's
      forms, refusals, and never-published marker; delivery instances, routing,
      signing, and Apprise; the Kubernetes section's contact-exchange overlay.
- [x] 5.4 `docs/development/ARCHITECTURE.md`: the settlement-configuration delivery
      paragraph for per-origin contact and routing.
- [x] 5.5 `docs/development/TESTING.md`: the VM loop row gains `introduction-retention`;
      the new marker.
- [x] 5.6 `docs/development/VALIDATION_RUNBOOK.md`: the Helm verification procedure
      from 6.6.
- [x] 5.7 `VM/settings.toml`: comments for `[Settlement.contact]` and `[Delivery]`.

## 6. Validation

System scenarios are new modules only; no shared end-to-end helper or fixture is
edited.

- [x] 6.1 Kit, buyer, and boundary suites from Sections 2, 3b, 4, and 4a.
- [x] 6.2 Bare-metal and VM storefront suites, including 2.7, 3.7, 3a.4, 3b.7, and
      3b.8. Pre-existing failures reproduced unchanged on the snapshot source and not
      owned here: `test_negotiate_controller.py`'s amountless Alkahest escrow and
      unbacked-acceptance cases, `test_publication_loop.py`'s two order-dependent
      cases and its hang at `test_round_zero_evaluation_runs_the_inventory_guard`, and
      `test_alkahest.py`'s chain-dependent setup. The publication harness's
      `set_settlement_clauses` appends to `pricing.settlements` across apps instead of
      replacing it; the introduction tests offer pools through overrides instead.
- [x] 6.3 **System.** A new module `test_vm_introduction.py` under
      `e2e-tests/tests/e2e/roles/scenarios/vms/`, marker `e2e_vm_introduction` registered in `e2e-tests/pyproject.toml`; a
      `mailpit_api_url` lane setting in `e2e-tests/config/config-docker.yml` and
      `config-local.yml`. A VM deal settles by introduction through the VM buyer CLI,
      the buyer's file sink receives the seller's contact, and Mailpit holds the
      seller-side message carrying the buyer's.
      The VM lane passed with 135 tests, including all six introduction scenarios.
      Lane configuration includes Mailpit, Bob's contact and SMTP delivery, and
      `mailpit.api_url` in the Docker and local profiles. Rerun on the tree combining
      8.8 and 8.9 in Actions run 37182810584: the VM lane passed 135 tests including
      all six introduction stages, with the seller accepting the opening at round 0
      (`decision_reason` `unpriced_selection`) and seller-side delivery reaching the
      `seller-mail` instance; the bare-metal lane passed 16.
- [x] 6.4 **System.** Same module: backed and unbacked VM listings from one storefront
      are returned by one rate-bounded query, a listing publishing no rate is excluded,
      and an unbacked one reaches a usable introduction. Transferred from
      `unbacked-listing-publication` (its 6.7); the rate bound from
      `publish-indicative-listing-rates` (its 7.13).
      Passed in the VM lane and in the focused introduction module run.
- [x] 6.5 *(transferred, not run here)* **System.** Two seller sites behind one
      storefront keep distinct origin and source identity, each reveals its own
      seller's contact, and seller-side delivery reaches only that origin's instances.
      Transferred from `unbacked-listing-publication` (its 6.8), and transferred on to
      `unbacked-bare-metal-listings` with its bare-metal counterpart: neither lane
      has a storefront serving two seller sites, and `bare-metal-mock-provisioned-deal`
      deploys two storefronts with one site each, so the scenario needs a topology of
      its own. The behaviour is proven below the system level here:
      `domains/vms/storefront/tests/integration/test_introduction_origins.py` (two sites
      behind one storefront each reveal their own contact; a site that lost its contact
      is refused) and `kit/delivery/tests/unit/test_seller.py` with
      `kit/delivery/tests/unit/test_config_and_discovery.py` (routing per origin, and
      the multi-origin refusal without a routing table).
- [x] 6.6 **Helm.** With `helm/fixtures/contact-exchange-values.yaml` applied and port
      forwards to Bob's storefront (8001), the registry (8080), provisioning (8081), and
      Mailpit's API (8025), `make -C e2e-tests test-module MODULE=e2e_vm_introduction
      ACTIVE_PROFILES=local` passes. Confirm the Service names against `helm template`
      and record the exact commands in 5.6.

      Passed on 2026-10-04: all six introduction stages (`6 passed` in 3.61 s) against
      a fresh local release `arkhai-node-operator` in namespace `scm-intro-20261004`,
      deployed with `make -C helm deploy VALUES=fixtures/contact-exchange-values.yaml`,
      after `make build-dev` and `make -C e2e-tests reinit`. Two earlier attempts
      found what the fixture and profile now carry: the backed test pool had no
      settlement clause (the fixture now gives Bob a contact-exchange
      `pricing.settlements` default), and a redeploy left the storefront port-forward
      bound to the replaced pod. The fixture advertises Bob at the port-forward URL;
      `e2e-tests/config/config-local.yml` carries the registry authority and the
      signed development identities the scenario needs; `e2e-tests/Makefile` resolves
      its config directory from `CURDIR`. Commands are recorded in
      `docs/development/VALIDATION_RUNBOOK.md`.

## 8. Review corrections

- [x] 8.1 **Single-form contact binds to its one site.** `resolve_seller_contact` in
      `KC/settlement_config.py` takes the known origins; the single form resolves only
      when the agreement's origin is the one configured origin, so a missing origin,
      an unknown one, or a stale deal from a site no longer configured is refused with
      `seller_contact_unavailable` before anything is persisted, driven, or delivered.
      `KC/composition.py` keeps the known origins after construction. Unit tests for
      `None`, an unexpected origin, and a stale deal.
- [x] 8.2 **VM transport contract.** Replace the hand-signed router test (now removed) with tests driving
      `core_buyer`'s `IntroductionTransport` (`start`, `read`, the deleted outcome, seller
      signature verification) against the VM publication harness over loopback, as
      bare metal's `test_http_introductions.py` does against its app. See 3.7 for what
      the harness is and is not.
- [x] 8.3 **Origin and retention through typed clients.** Through the VM publication
      harness (`domains/vms/storefront/tests/publication_app.py`, an in-process
      composition; see 3.7):
      `test_introduction_origins.py` publishes, accepts, and reveals one listing and
      asserts its binding's site governed all three; two sites reveal their own
      contacts; a site with no contact publishes no option and refuses a reveal.
      `test_introduction_retention.py` covers the `/health` disclosure, admin deletion
      through its route and authentication, `introduction-retention` dry-run and
      run-cycle, and read, start, and operator re-delivery after deletion.
- [x] 8.4 **Delivery tests synchronize instead of sleeping.** `sinks_for` routing as
      plain unit tests; one background-dispatch test synchronized on an
      `asyncio.Event`, moved to `kit/delivery/tests/integration`.
- [x] 8.5 **Apprise loopback test is integration.** Move it to
      `kit/delivery-apprise/tests/integration`; its `pyproject.toml` test paths and
      `make test` run it.
- [x] 8.6 **Sinks are discovered, never named.** A sink plugin may declare its settings
      model beside its factory (`KD/sinks.py`); `KD/discovery.py` collects installed
      sinks' declared models; the built-in sinks and `kit/delivery-apprise` declare
      theirs; `VM/values_schema.py` types `[Delivery]` from discovery and imports no
      sink module. A plugin declaring no model stays open. Both storefronts keep
      `arkhai-kit-delivery-apprise` as a plain dependency, which is what ships it in
      their images. Regenerate the Helm values schemas.
- [x] 8.7 **Record corrections.** `tasks.md` 2.6, 3.7, 3a.4, 3b.7, 3b.8, and 6.2 name
      the files and levels that exist; `design.md`'s migration plan names the mechanism
      kit for buyer commands; `DEPLOYMENT_AND_CONFIG.md` says routed origins must be
      configured sites; `VM/controllers/introductions_controller.py` says only the
      buyer starts a reveal; `VM/startup.py` imports the retention sweep at module
      scope.

- [x] 8.8 **VM accepts an unpriced selection.** Found while doing 8.3: VM countered
      every introduction opening, because its terminal `bisection` policy waits for
      an amount an unpriced option never carries (`design.md` decision 14).
      `kit/policy/src/market_policy/scalar_policies.py` gains
      `accept_unpriced_selection`; `domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py`
      runs it last among VM's default guards. The VM storefront's dev group carries
      `arkhai-vms-buyer` for the buyer-client integration test. Unit tests in
      `kit/policy/tests/unit/test_selection_scalar.py`; the chain position in
      `domains/vms/storefront/tests/unit/test_file_policy_discovery.py`; acceptance
      under the default chain in 3.7's integration tests. `kit-policy` 0.2.0,
      `kit-negotiation-runtime` 0.2.1, `vms-negotiation` 0.3.0.

- [x] 8.9 **Buyer-side fixes from the VM lane run.** The lane run showed the buyer
      could not carry an amountless introduction deal through its own checks, each
      fixed where it was found: `core/buyer/src/core_buyer/negotiation_client.py`
      validates settlement acceptance only on an accept and allows an omitted amount
      when the selected option advertises no rate; `core/buyer/src/core_buyer/deal_helpers.py`
      recovers an accepted run whose single obligation has no amount;
      `core/buyer/src/core_buyer/delivery.py` reads the `[Delivery]` section the
      configuration documents; `domains/vms/buyer/src/arkhai_vms_buyer/deal_helpers.py`
      derives escrow terms only for an Alkahest plan; and
      `domains/vms/buyer/src/arkhai_vms_buyer/introduction_cli.py` negotiates through the
      VM buyer client with the selected option in its policy parameters. Unit test for
      the delivery section in `core/buyer/tests/unit/test_delivery.py`; the registry
      smoke test authenticates as a buyer against the trusted registry authority.

- [x] 8.10 **Pre-closeout review corrections.**
      - A named delivery instance spelling `sink` differently (`Sink`, `SINK`) escaped
        the generated schema's typing, so its secret settings could reach the
        ConfigMap. `VM/values_schema.py` now selects a sink only by `sink` spelled
        exactly and refuses every other spelling in every instance table, since the
        delivery kit reads no other; both Helm schemas regenerated.
        `domains/vms/storefront/tests/unit/test_values_schema.py` validates real
        documents against the committed schema with `jsonschema` (added to the VM
        storefront's dev group): secret webhook, SMTP, and Apprise settings are refused
        however `sink` or the field is spelled, and public settings stay accepted.
      - The buyer refused an amountless acceptance whenever the selected option had any
        rate, though the negotiation protocol defines bargaining by an `amount` rate.
        `core/buyer/src/core_buyer/negotiation_client.py` now refuses only for an
        option with an `amount` rate; `core/buyer/tests/unit/test_settlement_acceptance.py`
        covers an option with only a `nativeAmount` rate (accepted) and one with an
        `amount` rate (refused).
      - The VM system scenario reads `/health` through the storefront's typed client;
        only Mailpit, an external service, is called directly.
      - The VM introduction integration tests are described as in-process composition
        integration, not full-app integration (3.7, 8.2, 8.3).

## 7. Closeout

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep at the promoted glue is why the
      re-derivation check exists, not which domain it came from.
- [x] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite; a promotion is exactly where a latent circular import surfaces.
      Moved to module scope: the VM buyer's `request-introduction` and introduction
      context imports (not circular in any import order), `introduction_cli`'s
      `common` imports, the VM server's contact-exchange import, and every test-local
      import this change added. Kept with a stated reason: the VM `settlement contact`
      CLI group defers its imports so `--help` needs no configuration, as the sibling
      settlement group does. Verified by the suites in 8.10.
- [x] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [x] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and any remaining open work. Decisions and their alternatives are
      recorded in `design.md`; do not restate their reasoning here.
- [x] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, remove this change's
      rows from Goal 6's and Goal 7's gap tables and absorb the result into their
      current-state prose: contact exchange composed on VM, the contact resolved per
      origin, and delivery routed per origin. Keep the note beside Goal 6's unowned
      second-delivery-producer row current: the multi-origin routing refusal is
      unconditional, and a second producer revisits it.
      Done: Goal 6 and Goal 7 gap rows removed and absorbed into their current-state
      prose; the second-producer note states the routing rule without citing this
      change.
- [x] 7.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`, and
      `unbacked-bare-metal-listings`' blocker.
      Done: the row reads complete and ready to archive; the dependency graph marks
      this change complete; `unbacked-bare-metal-listings` is no longer blocked on it,
      in the index, its tasks, and its proposal.
- [x] 7.7 **Promotion.** Complete the design-promotion record below.
      Done: the record below names every accepted decision's permanent home, including
      the two rules 8.10 promoted.
- [x] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=compose-contact-exchange-across-compute` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
      Passes for this change and for `unbacked-bare-metal-listings`. The repository-wide
      check reports the same 11 misses it reported before this change, none in a file
      this change touches.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
      Evidence: Actions run 37182810584 passed both lanes — VM 135, including all six
      introduction stages (disclosure, backed and unbacked publication, the rate-bounded
      query, the introduction-only listing, reveal through the buyer CLI, and Mailpit
      delivery), with the seller accepting at round 0 (`unpriced_selection`) and
      delivering to `seller-mail`; bare metal 16, including its introduction scenario.
      The same six stages passed against a local Helm release on 2026-10-04 (6.6).
      Owed: one VM-lane run on the final tree, since 8.10 changed the schema
      generator, the buyer's amountless check, and the scenario's health read after
      those runs.
- [ ] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
      `check-uv-setup`, `check-python-version`, and `check-project-layout` pass on the
      final tree, and every lock but one is current. Owed: regenerate
      `domains/vms/storefront/uv.lock` for the `jsonschema` dev dependency 8.10 added,
      which needs `download-r2.pytorch.org`, then rerun `make check-packaging`.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Accepted-state interpretation and the obligation drive sequence have one implementation | `openspec/specs/contact-exchange-settlement/spec.md` |
| A composing domain supplies persistence, configuration, and route bindings, not lifecycle logic | `openspec/specs/contact-exchange-settlement/spec.md` |
| The seller's contact is resolved per opaque origin, guarded at publication and reveal; readiness stays storefront-wide; one origin from binding to reveal | `openspec/specs/contact-exchange-settlement/spec.md`; configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Seller-side delivery has one implementation and remains non-authoritative across composing domains | `openspec/specs/introduction-delivery/spec.md` |
| Sinks are named instances; seller-side delivery routes by origin, and a multi-origin storefront must route deliberately | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/ARCHITECTURE.md` |
| A seller's default policy accepts an exact unpriced selection | `openspec/specs/negotiation-protocol/spec.md` |
| Buyer introduction commands are mechanism-owned and domain-mounted | `openspec/specs/contact-exchange-settlement/spec.md` |
| Contact details are public configuration that is never published | `openspec/specs/contact-exchange-settlement/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The buyer accepts an amountless acceptance only for an option with no `amount` rate | `openspec/specs/negotiation-protocol/spec.md` |
| `sink` is spelled exactly; a deployment schema refuses other spellings | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Webhook signing; instances never misname their sink; the Apprise plugin | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Helm deployment of contact exchange and delivery | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/VALIDATION_RUNBOOK.md` |
| Roadmap currency | `docs/development/ROADMAP.md`, Goals 6 and 7: this change's gap rows removed and absorbed into current-state prose; the second-producer note restates the routing rule without citing this change |
| Campaign index currency | `openspec/changes/README.md`: this change's row marked complete and ready to archive; `unbacked-bare-metal-listings` no longer blocked on it |
