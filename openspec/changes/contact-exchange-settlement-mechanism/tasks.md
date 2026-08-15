# Tasks

Both prerequisite items from `finish-settlement-mechanism-neutrality` (buyer
`service_terms` acceptance, declinable scalar) are complete on this branch. One
sequencing constraint remains and is stated where it bites: bare metal's selection
path is still Stripe-shaped (`negotiation_service.py:115` rejects non-hosted
mechanisms; `_open_hosted` scales rates and builds the hosted plan), so Section 3
here is where that change's Section 3.1–3.2 (registration-owned pre-terms dispatch,
bare metal as template) must land first — the two changes share that boundary
deliberately. Sections 1–2 are purely additive and independent.

Open questions from `design.md` are resolved at the section that forces them:
consent model and buyer-payload timing in Section 4, retention posture in
Section 6.

## 1. Mechanism kit

- [x] 1.1 Scaffolded `kit/contact-exchange` (package `market_contact_exchange`)
      mirroring `kit/hosted-settlement`: pyproject (deps: arkhai-core,
      arkhai-kit-settlement-runtime, pydantic), Makefile, `kit/Makefile`
      `test-contact-exchange`/`dist-contact-exchange` wiring, and an import-fence
      boundary test (stdlib + market_core + market_settlement_runtime + pydantic;
      no provider SDKs, no web frameworks; market_identity unneeded so far, add
      to the fence only when imported).
- [x] 1.2 `create_contact_exchange_registration()` done. One correction forced
      by the registry: the canonical mechanism-ID grammar
      (`[a-z][a-z0-9.-]*\.vN`) forbids underscores, so the ID is
      `contact-exchange.v1`, not the drafted `contact_exchange.v1`; all change
      documents and prior test fixtures were renamed. Config under
      `[Settlement.contact]`: `contact_payload` (bounded opaque dict, marked
      secret, seller-role) and `profiles` (channel + prose terms); a config-time
      validator rejects payload values that appear in published profiles.
- [x] 1.3 `ContactExchangeClient` implements the port trivially; mechanism_ref
      derives from the runtime's deterministic materialize operation_ref, so
      re-materialization is idempotent. Port conformance pinned via the
      runtime-checkable protocol.
- [x] 1.4 Option builder emits one rateless option per ready clause with
      `option_id` via `derive_settlement_option_id` (market_core import — no
      inline hash duplicate); rejects scalar-rate clauses, unoffered profiles,
      and any option payload containing a configured contact value. Built
      option validates against `SettlementOption` (canonical-ID check) and
      passes registry `build_option` with the non-scalar coherence check live.
- [x] 1.5 Evidence: kit suite 16 passed (fence, client port ×5, config/registry
      ×10 covering readiness channels-only projection, blockers, option build,
      scalar-clause rejection, leak refusal at config and builder, publication
      input, buyer compatibility, buyer-role client map); wheel
      `arkhai_kit_contact_exchange-0.1.0` built into `.dist`. Renamed-fixture
      suites re-run green: kit/policy 17, kit/negotiation-runtime 7,
      core/buyer 101.
- [x] 1.6 Closeout: `make check-comment-hygiene` clean; imports module-level;
      no change-ID references in code.

## 2. Non-financial obligation servicing

- [x] 2.1 Characterized in
      `kit/settlement-runtime/tests/unit/test_non_financial_obligation.py`:
      an amountless, assetless `contact-exchange.v1` obligation registers with
      a stable `derive_obligation_ref` identity and services materialize →
      fulfillment → check → collect to aggregate `complete` on an
      immediate-ready client. Nothing was broken — the runtime never reads
      `amount`/`asset` in its control flow, exactly as the spec delta requires;
      no production change was needed.
- [x] 2.2 Terminal shape pinned: completion with `reclaim_calls == 0`;
      availability is modeled as the fulfillment signal, and the status
      projection stays amountless. One lifecycle fact recorded: status
      reconciliation requires materialization first (no `mechanism_ref` before
      it), which the introduction flow satisfies since materialize is the first
      act after acceptance.
- [x] 2.3 Evidence: kit/settlement-runtime 71 passed (3 new).
- [x] 2.4 Closeout: hygiene clean; no production edits, so no promotion beyond
      the existing servicing spec delta.

## 3. Selection dispatch and the accepted plan (bare metal)

- [x] 3.1 Landed as `finish-settlement-mechanism-neutrality` §3.1–3.2 (checked
      there with its own evidence): registration-owned
      `accepted_obligation_builder` dispatch, bare metal as the template.
- [x] 3.2 The contact builder produces the one non-financial obligation and
      the introduction package (option identity, profile, channel, prose
      terms, listing ref, negotiated free text — never contact payloads) as
      mechanism-namespaced `service_terms`, which the domain merges into the
      accepted plan and persists via the existing `commit_settlement_plan`
      path. Amount is absent on the wire; the proposal echo carries no
      `fields.amount`. One refinement over the design draft, recorded in
      `design.md`: the obligation keeps the option's nominal `asset`
      (`"introduction"`) and binds both party principals into params, so the
      buyer's strict obligation-vs-advertised-option comparison holds without
      weakening.
- [x] 3.3 Decision recorded in `design.md`: the provision envelope gains the
      non-provisioning shape — `access_method: "none"` with no SSH key —
      rather than a second message kind; every provisioning path still
      requires credentials at its own admission arm, and the introduction deal
      still states the brokered duration.
- [x] 3.4 Evidence: bare-metal storefront `test_selection_dispatch.py`
      (non-scalar accept persists the plan with the mechanism package;
      uncomposed-mechanism, tampered-option, and proposed-amount rejections;
      composition dispatch surfaces only priority builders including hosted);
      `core/buyer` `test_accepts_amountless_introduction_plan` validates the
      buyer side with `agreed_amount=None`. Suites: storefront 99, buyer 102,
      contact kit 20.
- [x] 3.5 Closeout: hygiene clean; imports module-level; design updated with
      the two decisions above.

## 4. Introductions reveal surface

- [x] 4.1 `IntroductionRouteService` in `kit/contact-exchange` mirrors the
      hosted route service (protocol callbacks; domain mounts FastAPI routes):
      signed start supplies the buyer's payload — resolving the timing
      question: the payload accompanies start, so "available to both" is
      well-defined — and an idempotent authenticated read serves each party
      the counterparty's payload plus the introduction package. Acceptance is
      consent to reveal (accept = deal). One amendment to the draft: the
      seller's payload binds from configuration at the first introduction
      operation, not at negotiation acceptance — acceptance stays payload-free
      by construction, so deals that never start persist no contact data.
- [x] 4.2 `contact_introductions` table via kit `SettlementMigration`s
      (`CONTACT_EXCHANGE_MIGRATIONS`), keyed by `obligation_ref`,
      size-bounded via the shared payload validator, with idempotent insert,
      conflict rejection on changed payloads, and `delete_introduction` as the
      lifecycle teardown hook; bare-metal `SQLiteClient` composes the
      migration and wraps the sync helpers.
- [x] 4.3 `/api/v1/introductions` mounted in the bare-metal storefront beside
      the `/api/v1/settlements` family with the same request-signing
      authorization (either party may read; only the buyer may start); the
      domain `complete` callback drives the non-financial obligation to
      collected through the settlement runtime, idempotently. The contact
      registration joined `build_bare_metal_settlement_registry` (the §6.1
      storefront half) since `[Settlement.contact]` cannot resolve without it.
- [x] 4.4 Evidence: kit route-service units 8 (buyer-only start, idempotent
      replay, changed-payload conflict, both-party reads, pre-start refusal,
      unaccepted 404, non-party 403) + migration units 4 (restart round-trip,
      idempotent/conflicting insert, deletion); storefront HTTP e2e 3 —
      listing → selection accept → start (reveals, aggregate settlement
      `complete`) → both-party reads → restart persistence → refusals.
      Suites: contact kit 32, bare-metal storefront 102.
- [x] 4.5 Closeout: hygiene clean; design decisions recorded.

## 5. Buyer surface

- [ ] 5.1 Buyer flow for an introduction deal: propose the selection with no
      amount, accept the plan (already tolerated), start the introduction with a
      contact payload, and read the introduction — surfaced through the
      bare-metal buyer CLI (`domains/bare_metal/buyer`), reusing
      `core_buyer.hosted_settlement`'s transport patterns for the new family.
- [ ] 5.2 Evidence: buyer unit tests for the introduction client (start/read,
      idempotent re-read, refusal surfaces cleanly).
- [ ] 5.3 Closeout.

## 6. Composition, discovery, end-to-end

- [ ] 6.1 Register `create_contact_exchange_registration()` in the bare-metal
      composition roots (storefront `settlement_composition.py`; buyer side per
      §5) behind `[Settlement.contact]` + a `priority` entry; other domains'
      roots follow only after bare metal is proven (each is one line once §3's
      seam covers that domain — do not add them ahead of their dispatch work).
- [ ] 6.2 Loose-listing registry filter-spec profile for introduction markets:
      option-only requirements, minimal filter set, missing-field-tolerant
      matching; decide the mechanism-filter shape recorded as the open question
      shared with `finish-settlement-mechanism-neutrality` §6.1.
- [ ] 6.3 End-to-end introduction deal on bare metal: publish a contact-option
      listing, negotiate take-it-or-leave-it, accept, start, both parties read
      their introduction, deal reports terminal.
- [ ] 6.4 Record the contact-payload retention posture (resolving the retention
      question): bounded persistence, deletion as part of the deal lifecycle,
      documented in the capability's `architecture.md`.
- [ ] 6.5 Permanent docs: `docs/development/ARCHITECTURE.md` system-overview
      note (a market may settle by introduction); promotion record rows below
      filled as decisions are accepted.
- [ ] 6.6 Closeout: comment hygiene, import placement, docs compliance,
      narrative compression, roadmap currency (Goal 6 row), promotion record
      complete.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The canonical mechanism ID is `contact-exchange.v1` (registry ID grammar forbids underscores) | `openspec/specs/contact-exchange-settlement/spec.md` (promote at synchronization) |
| The introduction obligation keeps the option's nominal `asset` and binds party principals into params so buyer-side strict option comparison holds; only `amount` is absent | `openspec/specs/contact-exchange-settlement/spec.md` (promote at synchronization) |
| Non-provisioning deals ride the provision envelope with `access_method: "none"`; provisioning arms re-require credentials themselves | bare-metal domain documentation (promote at synchronization) |
