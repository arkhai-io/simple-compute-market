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

- [ ] 1.1 Scaffold `kit/contact-exchange` (package `market_contact_exchange`)
      mirroring `kit/hosted-settlement`: pyproject, Makefile with `dist` target,
      and an import-fence boundary test identical in spirit to the other mechanism
      kits (stdlib + market_core + market_identity + market_settlement_runtime +
      pydantic; no provider SDKs, no web frameworks).
- [ ] 1.2 `create_contact_exchange_registration()`: `mechanism_id =
      "contact_exchange.v1"`, `config_key = "contact"`, buyer and seller roles,
      `negotiates_scalar_amount=False`, preflight that validates configuration
      only (no external dependency to probe). Config model under
      `[Settlement.contact]`: the seller's contact payload (an opaque bounded
      dict, size-capped), offered contact profiles (channel descriptor + prose
      commercial terms), and nothing that could leak contact into publication.
- [ ] 1.3 Mechanism client implementing the `ConditionalEscrowClient` port:
      `materialize` returns ready immediately, `get_status`/`check` report
      satisfied, `collect` produces the introduction receipt, `reclaim_expired`
      is a no-op. No funding, no condition anchors.
- [ ] 1.4 Option builder: one `SettlementOption` per offered profile with
      `rates: []`, prose terms and channel descriptor in `params`, `option_id`
      via `derive_settlement_option_id`. Pin that the builder passes
      `build_option`'s `reject_scalar_rates_for_non_scalar` coherence check and
      that no configured contact payload reaches the built option.
- [ ] 1.5 Evidence: kit unit suite (registration, readiness, client port, option
      builder, fence) green via `uv run --find-links ../../.dist pytest
      tests/unit -q`; wheel builds into `.dist`.
- [ ] 1.6 Closeout: comment hygiene, module-level imports, no change-ID
      references in code.

## 2. Non-financial obligation servicing

- [ ] 2.1 Characterize the settlement runtime against the contact-exchange
      obligation — payer/claimant are the two parties, `amount`/`asset` absent
      (`None`, already documented as the non-scalar view in
      `market_core.schemas.SettlementObligation`), mechanism
      `contact_exchange.v1`: `register_plan`, `derive_obligation_ref`, servicing
      state transitions to collected on the immediate-ready client, and status
      projection. Fix only what the characterization proves broken; the spec
      delta in `specs/settlement-servicing/spec.md` is the contract.
- [ ] 2.2 Pin the terminal shape: the deal is agreed → revealed with nothing to
      converge, heartbeat, or reclaim; the claim completes on availability, not
      on read.
- [ ] 2.3 Evidence: settlement-runtime suite green including the new
      non-financial characterization tests.
- [ ] 2.4 Closeout.

## 3. Selection dispatch and the accepted plan (bare metal)

- [ ] 3.1 Land `finish-settlement-mechanism-neutrality` §3.1–3.2 first: the
      registration-owned pre-terms hooks (selection admission, accepted-plan
      construction) with bare metal as the template, replacing the
      `mechanism != HOSTED_MECHANISM` rejection and the Stripe-shaped
      `_open_hosted` arm with dispatch through the registry. Check those boxes
      in that change's tasks with their own evidence; this section consumes the
      seam, it does not duplicate the work.
- [ ] 3.2 Contact-exchange accepted plan through the seam: selection of a
      contact option produces a plan with the one non-financial obligation and
      the introduction package (agreed context, channel descriptor, prose terms,
      negotiated free text — never contact payloads) in
      `service_terms["contact_exchange.v1"]`; acceptance persists it via the
      existing `commit_settlement_plan` path. Amount is absent, not zero, on
      the wire shape the buyer sees; `agreed_price` records 0 per the runtime's
      existing tolerance.
- [ ] 3.3 Bare-metal round admission for introduction deals: the seller round
      path must not demand provisioning inputs (SSH key, access method) that an
      introduction does not need — decide whether the contact option's listing
      admits a reduced message shape or the domain message keeps its fields
      optional for non-provisioning mechanisms, and record the decision in
      `design.md`.
- [ ] 3.4 Evidence: bare-metal storefront unit tests covering open-with-selection
      for a contact option (accept, plan persisted, tampered selection rejected);
      buyer-side acceptance covered by the existing `service_terms` and
      non-scalar tests plus one contact-shaped case in
      `core/buyer/tests/unit/`.
- [ ] 3.5 Closeout.

## 4. Introductions reveal surface

- [ ] 4.1 Framework-free `IntroductionRouteService` in `kit/contact-exchange`
      mirroring `HostedSettlementRouteService` (protocol callbacks for
      authorization, persistence, projection; domain mounts the FastAPI routes):
      signed start supplies the buyer's contact payload (resolving the open
      question: the payload accompanies start, so "available to both" is a
      well-defined terminal condition), the seller's payload is bound from
      configuration at acceptance, and an idempotent authenticated read serves
      each party the counterparty's payload plus the introduction package.
      Acceptance is consent to reveal (resolving the consent question:
      accept = deal; record the rationale in `design.md`).
- [ ] 4.2 Persistence beside the obligation record: contact payloads in a new
      table via kit migrations (pattern: `kit/hosted-settlement/migrations.py`),
      size-bounded, keyed by `obligation_ref`; reads are stable across restart.
- [ ] 4.3 Mount `/api/v1/introductions` in the bare-metal storefront
      (`api.py`/`runtime.py`, beside the `/api/v1/settlements` family), with the
      same request-signing authorization; reveal is refused before acceptance
      and to non-parties.
- [ ] 4.4 Evidence: kit route-service units (authorization, idempotency,
      pre-acceptance refusal, non-party refusal); storefront integration test
      persisting across a restart of the service.
- [ ] 4.5 Closeout.

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
| _(filled as sections complete)_ | |
