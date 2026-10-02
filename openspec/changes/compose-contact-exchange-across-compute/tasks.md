# Tasks — compose contact exchange across the compute family

Depended on `contact-payload-retention` and `pass-through-storefront-config`, both
complete and archived. Task 6.5 is blocked on `bare-metal-mock-provisioned-deal`'s
two-storefront topology. Decisions are in `design.md` (1–13).

Paths abbreviate `kit/contact-exchange/src/market_contact_exchange/` as `KC/`,
`kit/delivery/src/market_delivery/` as `KD/`,
`domains/vms/storefront/src/market_storefront/` as `VM/`, and
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` as `BM/`.

Order: Sections 1–2 promote and must leave bare metal's suites green before Section 3
composes VM. Sections 3b, 4, and 4a may proceed in parallel after Section 2.

## 1. Survey and placement

- [x] 1.1 Separated bare metal's introduction composition into domain-neutral parts
      (accepted-state interpretation, `obligation_ref` re-derivation, the drive
      sequence, `load_revealed_introduction`, introduction persistence over the kit's
      own table, the retention/disclosure/reveal wiring in `BM/runtime.py`) and
      domain parts (thread and obligation reads, configuration carrier, routes,
      authorization adapter, loop registration). The same split for `BM/delivery.py`
      and the bare-metal buyer's `introduce` and `introduction`.
- [ ] 1.2 Promote into `KC/composition.py` with the thread, obligation, and origin
      reads as Protocols (`design.md` decisions 2, 3, 13).
- [ ] 1.2a Add `uuid` and `typer` to the permitted roots in
      `kit/contact-exchange/tests/unit/test_package_boundary.py`; the deny list is
      unchanged.
- [x] 1.2b Recorded: not `kit/storefront`, which hard-depends on Alkahest.
- [x] 1.3 Recorded: VM only; API credits is out of scope (`design.md` decision 11).
- [x] 1.4 The VM process resolves only mode `vm` for its services; the `bare_metal`
      contribution in its registry is used for binding resolution only, so registering
      contact exchange in `VM/settlement_composition.py` affects VM listings only.

## 2. Promote

- [ ] 2.1 `KC/composition.py`: the accepted-state bodies from `BM/introduction_routes.py`,
      moved unchanged except for the injected origin read; `load_revealed_introduction`
      with them.
- [ ] 2.2 `KC/store.py`: `SQLiteIntroductionStore(db_path)` with async `insert`,
      `load`, `delete_payloads`, and `select_expired` over `KC/migrations.py`'s row
      functions, replacing the four wrappers in `BM/sqlite_client.py`.
- [ ] 2.3 `KC/composition.py`: `ContactExchangeComposition`, built from the running
      configuration getter, the store, the three reads, the settlement runtime, the
      known origins, and an optional seller dispatch. It yields the reveal service for
      an authorizer, the retention service, the disclosures, and the redelivery read.
      Replaces `contact_settlement_config`, `introduction_retention`, and the
      disclosure wiring in `BM/runtime.py`.
- [ ] 2.4 Export the new surface from `KC/__init__.py`.
- [ ] 2.5 Move bare metal onto it: `BM/introduction_routes.py` and
      `BM/runtime.py` reduce to composition; `BM/api.py` keeps routes and
      `_authorize_introduction_request`; `BM/server.py` keeps loop registration;
      `BM/sqlite_client.py` loses the wrappers.
- [ ] 2.6 **Unit.** `kit/contact-exchange/tests/unit/test_composition.py` and
      `test_store.py`, covering each refusal the glue makes, the mismatch refusal, the
      store's round trip and redaction, and the composition object's outputs.
- [ ] 2.7 **Unchanged coverage.** `domains/bare_metal/storefront/tests/test_http_introductions.py`,
      `test_introduction_delivery.py`, `test_persistence.py`, `test_http_system.py`, and
      `test_app_composition.py` pass against the promoted implementation before
      Section 3 starts.

## 3. Compose VM

- [ ] 3.1 `VM/settlement_composition.py`: register `create_contact_registration()`;
      add `"contact-exchange.v1": False` to the per-mechanism fulfillment declaration.
- [ ] 3.2 `VM/utils/sqlite_client.py`: the contact-exchange migrations in the migration
      tuple beside `*settlement_migrations()`.
- [ ] 3.3 `VM/container.py`: build the `ContactExchangeComposition` from VM's
      settlement configuration, `SQLiteIntroductionStore`, the inherited
      `load_negotiation_thread_row` / `load_thread_binding` reads, the settlement
      runtime, and the keys of `[capacity.sites]` as known origins.
- [ ] 3.4 `VM/controllers/introductions_controller.py` (new): `POST /api/v1/introductions`
      and `GET /api/v1/introductions/{obligation_ref}` over the kit reveal service, with
      an authorization adapter on `core_storefront.auth.authenticate_request` that
      allows the buyer and seller roles and sets `request.state.marketplace_authenticated`.
      Mount it in `VM/server.py`.
- [ ] 3.5 `VM/middleware/seller_auth.py`: `_buyer_response_contract` signs and records
      both introduction routes, as it does for the hosted settlement routes.
- [ ] 3.6 Confirm composition is independent of backing in both directions.
- [ ] 3.7 **Integration.** `domains/vms/storefront/tests/integration/test_introductions.py`
      through `core_buyer`'s `IntroductionTransport` over a loopback server
      (`domains/vms/storefront/tests/loopback.py`, copied from bare metal's): an
      accepted introduction reveals to both parties, an exact retry replays, a
      mismatched `obligation_ref` is refused with no payload, the obligation reaches
      collected without VM fulfillment, and a rateless contact selection negotiates to
      acceptance with no agreed amount.

## 3a. Retention

- [ ] 3a.1 `VM/lifecycle.py` and `VM/lifecycle_steps.py`: an `introduction-retention`
      loop with step and preview over the kit sweep; started from `VM/startup.py` on a
      configurable interval.
- [ ] 3a.2 `VM/controllers/admin_controller.py` and `VM/middleware/admin_identity.py`:
      the kit's admin deletion route behind administrator authentication, with its
      route contract.
- [ ] 3a.3 `core/storefront/src/core_storefront/models/system_models.py`:
      `HealthResponse.disclosures`; `VM/services/system_service.py` fills it from the
      composition when the mechanism is enabled, for `/health` and
      `/api/v1/system/health`.
- [ ] 3a.4 **Integration.** `domains/vms/storefront/tests/integration/test_introduction_retention.py`:
      the readiness disclosure matches the reveal's; admin deletion leaves the
      obligation resolvable; read, start, and re-delivery answer the deleted outcome;
      the sweep step and preview work while loops are held.

## 3b. Per-origin contact resolution

- [ ] 3b.1 `KC/settlement_config.py`: `origins` tables with a non-empty
      `contact_payload`, bounded keys and count; `contact_payload` stays the single
      form. Both carry `"never_published": true` instead of `"secret": true`
      (`design.md` decision 13).
- [ ] 3b.1a `KC/settlement_config.py` `contact_preflight`: unready on no profiles or no
      contact in either form, otherwise ready; nothing per origin in the projection.
- [ ] 3b.1b `kit/settlement-runtime/src/market_settlement_runtime/configuration.py`
      `_secret_values`: collect `never_published` fields too, so the readiness leak
      check covers them. `VM/values_schema.py`: add `never_published` to the stripped
      annotations.
- [ ] 3b.2 `KC/settlement_config.py`: `validate_contact_origins(config, known_origins)`
      with decision 4's three refusals; called from `KC/composition.py` at
      construction.
- [ ] 3b.3 Option builder: take `origin` from publication resources; no option when it
      resolves no contact, refuse when the keyed form has no origin, no option when no
      clause selects contact. `VM/services/listing_service.py`: in `create_listing`,
      read the capacity source's site before `_derive_settlement_artifacts` and pass it;
      in `reconcile_settlement_options`, pass the stored binding's site.
      `BM/publication_composition.py`: pass `candidate["site_id"]`.
- [ ] 3b.4 `KC/introduction_routes.py`: `IntroductionAgreement.origin`; the service
      takes a contact resolver instead of `seller_contact`; HTTP 503
      `seller_contact_unavailable` before persisting. Remove `BM/api.py`'s
      storefront-wide 503 check.
- [ ] 3b.5 A single-origin deployment configured with the single form resolves to its
      configured value.
- [ ] 3b.6 **Unit.** `kit/contact-exchange/tests/unit/test_settlement_config.py`: forms,
      empty-entry refusal, every startup refusal, readiness under each form, resolver,
      option suppression and fail-closed refusal, and that a never-published value in
      a readiness projection is refused.
- [ ] 3b.7 **Integration.** `domains/vms/storefront/tests/integration/test_introduction_origins.py`:
      two origins behind one storefront each reveal their own payload and never the
      other's; one listing followed from publication through acceptance to reveal
      uses its binding's origin throughout.
- [ ] 3b.8 **Integration.** Same module: an origin with no payload publishes no contact
      option; a start whose origin lost its payload is refused with nothing persisted,
      driven, or delivered.

## 4. Delivery

- [ ] 4.1 `KD/config.py`: named instances with `sink`; a table without `sink`
      instantiates its own name; an instance named for one sink stating another is
      refused; reserve `origins`; a `role` argument to `load_delivery_config`.
- [ ] 4.2 `KD/config.py`: the seller-side `[Delivery.origins]` table and its refusals,
      including the unconditional multi-origin refusal; refuse a routing table on the
      buyer side.
- [ ] 4.3 `KD/seller.py` (new): background dispatch with task retention and outcome
      logging, sink-set construction with warnings, routing by the agreement's origin,
      and re-delivery, reading reveal and agreement by shape. `KD/discovery.py`:
      instantiate by `sink`.
- [ ] 4.3a `KD/builtin/webhook_sink.py`: `sign = true` signs with a signer passed by
      the sink-set builder; refused without one.
- [ ] 4.3b `kit/delivery-apprise/` (new distribution `arkhai-kit-delivery-apprise`,
      package `market_delivery_apprise`): an `apprise` sink with secret-marked `urls`,
      registered on the `market.delivery_sinks` entry point; README, tests, lock.
- [ ] 4.4 Bare metal onto the kit: `BM/delivery.py` reduces to loading its environment
      carrier; `BM/cli.py`'s re-delivery calls the kit.
- [ ] 4.5 VM: `VM/utils/config.py` reads `[Delivery]`; `VM/container.py` builds the
      seller dispatch with the storefront signer and known origins; `VM/cli.py` gains
      `redeliver-introduction`.
- [ ] 4.5a `VM/values_schema.py`: type `[Delivery]` (`design.md` decision 13) and
      regenerate `helm/charts/storefront/values.schema.json` and
      `helm/values.schema.json` with `make helm-values-schema`;
      `domains/vms/storefront/tests/unit/test_values_schema.py` gains the delivery and
      contact cases.
- [ ] 4.6 Confirm delivery stays non-authoritative and re-delivery routes by origin.
- [ ] 4.7 **Unit.** `kit/delivery/tests/unit/test_config_and_discovery.py`,
      `test_builtin_sinks.py`, and new `test_seller.py`: instance parsing including
      pre-instance configurations, two instances of one plugin, misnamed instances,
      routing and every refusal including the multi-origin refusal, a shared
      destination, signing, and dispatch outcome reporting.
      `kit/delivery-apprise/tests/`: settings, secret marker, and delivery to a
      loopback `json://` receiver.

## 4a. Buyer introduction commands

- [ ] 4a.1 `KC/buyer_commands.py` (new): `create_contact_command_group(context_factory)`
      with `introduce` and `introduction [--deliver]`; the context supplies the
      transport, run recovery, and buyer sinks.
- [ ] 4a.2 Bare-metal buyer: mount the group through its settlement registry or
      settlement app in `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`,
      remove `introduce` and `introduction`, keep `request-introduction`.
- [ ] 4a.3 VM buyer: register contact with its command group in
      `domains/vms/buyer/src/arkhai_vms_buyer/settlement_composition.py`; add
      `request-introduction` in a new `introduction_cli.py` mounted from `cli.py`.
- [ ] 4a.4 **Unit.** `kit/contact-exchange/tests/unit/test_buyer_commands.py` against an
      injected context, including the deleted outcome and sink failure;
      `domains/vms/buyer/tests/test_introduction_cli.py`;
      `domains/bare_metal/buyer/tests/test_buyer_composition.py` updated.

## 4b. Deployment

- [ ] 4b.1 `domains/vms/storefront/storefront.bob.toml`: contact exchange enabled with
      one profile, `origins.default`, priority entry; `[Delivery]` with an SMTP instance
      to Mailpit routed for `default`.
- [ ] 4b.2 `domains/vms/compose.yml`: a `mailpit` service on the market network.
- [ ] 4b.3 `helm/charts/dev-env/`: an optional Mailpit Deployment and Service
      (`mailpit.enabled`, default false).
- [ ] 4b.4 `helm/fixtures/contact-exchange-values.yaml` (new): enables contact
      exchange and SMTP delivery to Mailpit for Bob, and Mailpit in `dev-env`;
      `helm/charts/storefront/tests/test_render.py` asserts the sections render intact
      and a secret-marked sink field is refused.
- [ ] 4b.5 Both storefront images install `arkhai-kit-delivery-apprise`
      (`domains/vms/storefront/pyproject.toml`, `domains/bare_metal/storefront/pyproject.toml`).
- [ ] 4b.6 Version bumps and pins: `kit-contact-exchange` 0.2.0, `kit-delivery` 0.2.0,
      `kit-settlement-runtime` next minor, `core-storefront` 0.7.0,
      `kit-capacity-publication` 0.3.1, `bare-metal-storefront` 0.7.0,
      `vms-storefront` 0.9.0, `bare-metal-buyer` 0.4.0, `vms-buyer` 0.5.0,
      `apicredits-storefront` 0.5.1; every exact pin of a bumped package updated; then
      `make lock`.

## 5. Specification and documentation

- [ ] 5.1 Promote the `contact-exchange-settlement` delta into
      `openspec/specs/contact-exchange-settlement/spec.md`.
- [ ] 5.2 Promote the `introduction-delivery` delta into
      `openspec/specs/introduction-delivery/spec.md`.
- [ ] 5.3 `docs/development/DEPLOYMENT_AND_CONFIG.md`: the contact-exchange section's
      forms, refusals, and never-published marker; delivery instances, routing,
      signing, and Apprise; the Kubernetes section's contact-exchange overlay.
- [ ] 5.4 `docs/development/ARCHITECTURE.md`: the settlement-configuration delivery
      paragraph for per-origin contact and routing.
- [ ] 5.5 `docs/development/TESTING.md`: the VM loop row gains `introduction-retention`;
      the new marker.
- [ ] 5.6 `docs/development/VALIDATION_RUNBOOK.md`: the Helm verification procedure
      from 6.6.
- [ ] 5.7 `VM/settings.toml`: comments for `[Settlement.contact]` and `[Delivery]`.

## 6. Validation

System scenarios are new modules only; no shared end-to-end helper or fixture is
edited.

- [ ] 6.1 Kit, buyer, and boundary suites from Sections 2, 3b, 4, and 4a.
- [ ] 6.2 Bare-metal and VM storefront suites, including 2.7, 3.7, 3a.4, 3b.7, 3b.8.
- [ ] 6.3 **System.** A new module `test_vm_introduction.py` under
      `e2e-tests/tests/e2e/roles/scenarios/vms/`, marker `e2e_vm_introduction` registered in `e2e-tests/pyproject.toml`; a
      `mailpit_api_url` lane setting in `e2e-tests/config/config-docker.yml` and
      `config-local.yml`. A VM deal settles by introduction through the VM buyer CLI,
      the buyer's file sink receives the seller's contact, and Mailpit holds the
      seller-side message carrying the buyer's.
- [ ] 6.4 **System.** Same module: backed and unbacked VM listings from one storefront
      are returned by one rate-bounded query, a listing publishing no rate is excluded,
      and an unbacked one reaches a usable introduction. Transferred from
      `unbacked-listing-publication` (its 6.7); the rate bound from
      `publish-indicative-listing-rates` (its 7.13).
- [ ] 6.5 **System — blocked** on `bare-metal-mock-provisioned-deal`'s two-storefront,
      two-site topology; redesign from that baseline. Two seller sites behind one
      storefront keep distinct origin and source identity, each reveals its own
      seller's contact, and seller-side delivery reaches only that origin's instances.
      Transferred from `unbacked-listing-publication` (its 6.8).
- [ ] 6.6 **Helm.** With `helm/fixtures/contact-exchange-values.yaml` applied and port
      forwards to Bob's storefront (8001), the registry (8080), provisioning (8081), and
      Mailpit's API (8025), `make -C e2e-tests test-module MODULE=e2e_vm_introduction
      ACTIVE_PROFILES=local` passes. Confirm the Service names against `helm template`
      and record the exact commands in 5.6.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep at the promoted glue is why the
      re-derivation check exists, not which domain it came from.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite; a promotion is exactly where a latent circular import surfaces.
- [ ] 7.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and any remaining open work. Decisions and their alternatives are
      recorded in `design.md`; do not restate their reasoning here.
- [ ] 7.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, remove this change's
      rows from Goal 6's and Goal 7's gap tables and absorb the result into their
      current-state prose: contact exchange composed on VM, the contact resolved per
      origin, and delivery routed per origin. Keep the note beside Goal 6's unowned
      second-delivery-producer row current: the multi-origin routing refusal is
      unconditional, and a second producer revisits it.
- [ ] 7.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`, and
      `unbacked-bare-metal-listings`' blocker.
- [ ] 7.7 **Promotion.** Complete the design-promotion record below.
- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=compose-contact-exchange-across-compute` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [ ] 7.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Accepted-state interpretation and the obligation drive sequence have one implementation | `openspec/specs/contact-exchange-settlement/spec.md` |
| A composing domain supplies persistence, configuration, and route bindings, not lifecycle logic | `openspec/specs/contact-exchange-settlement/spec.md` |
| The seller's contact is resolved per opaque origin, guarded at publication and reveal; readiness stays storefront-wide; one origin from binding to reveal | `openspec/specs/contact-exchange-settlement/spec.md`; configuration in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Seller-side delivery has one implementation and remains non-authoritative across composing domains | `openspec/specs/introduction-delivery/spec.md` |
| Sinks are named instances; seller-side delivery routes by origin, and a multi-origin storefront must route deliberately | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/ARCHITECTURE.md` |
| Buyer introduction commands are mechanism-owned and domain-mounted | `openspec/specs/contact-exchange-settlement/spec.md` |
| Contact details are public configuration that is never published | `openspec/specs/contact-exchange-settlement/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Webhook signing; instances never misname their sink; the Apprise plugin | `openspec/specs/introduction-delivery/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Helm deployment of contact exchange and delivery | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/VALIDATION_RUNBOOK.md` |
| Roadmap currency | `docs/development/ROADMAP.md`, Goals 6 and 7 |
| Campaign index currency | `openspec/changes/README.md` |
