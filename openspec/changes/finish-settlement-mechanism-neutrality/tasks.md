# Tasks

Sections 1 and 2 are deliberately first: they are the only two items
`contact-exchange-settlement-mechanism` is blocked on, and Section 1 is an apparent
live defect on the hosted path. Sections 3–6 are the wider neutrality work and are
coarser here; refine each when it is picked up, and sequence the VM/hosted-surface
portions after the corresponding `consume-expanded-stripe-funding` tasks.

## 1. Accepted-plan `service_terms` compatibility

- [x] 1.1 Reproduce: `core/buyer/tests/unit/test_settlement_acceptance.py` feeds a
      seller-shaped hosted accept (selection echo, advertised option with
      canonically derived `option_id`, obligation matching the option, and
      `service_terms["vm.v1"]` as the VM seller emits) through
      `_validate_settlement_acceptance` with `expected_plan=None`. Confirmed the
      defect: rejected at the blanket `plan.service_terms` clause; the same plan
      with empty `service_terms` passed, isolating the cause.
- [x] 1.2 Fix: the advertised-option semantic guard now compares conditions only;
      seller `service_terms` are accepted on the option-selected branch with the
      rationale recorded at the guard. Selection echo, party, mechanism, amount,
      expiry, asset, and params strictness unchanged.
- [x] 1.3 Regression: tampered-conditions and tampered-params rejections covered
      and green; full `core/buyer` unit suite passes (99 tests). Disclosed:
      `domains/vms/storefront/tests/unit/test_sync_negotiation_seller_round_hook.py`
      was not run in this checkout — it requires the verified hosted-settlement
      release wheels, which are not staged locally; its assertion of the emitted
      seller shape is the merged upstream evidence the new buyer tests mirror.
- [x] 1.4 Closeout: `make check-comment-hygiene` clean; section imports are
      module-level; no roadmap edit owed (the fix does not close a Goal 6 gap row);
      promotion recorded below.

## 2. Declinable scalar negotiation

- [x] 2.1 `MechanismRegistration.negotiates_scalar_amount` added (default scalar),
      declared explicitly by both existing factories; `build_option` enforces
      coherence — a declining mechanism must not publish an `amount` rate, since
      the option shape is how the declaration reaches counterparties.
- [x] 2.2 Guards scoped data-driven off the matched option, symmetric with the
      existing escrow-entry scalar test: `proposal_uses_scalar_amount` reads the
      selection's matched `settlement_options` entry, `accept_exact_listing`
      gained a selection arm (unlisted selection rejected; scalar selection held
      to the reference amount; non-scalar accepted as proposed), and the
      `missing_amount` rejections (kit `buyer_counter_guard`, VM guard via the
      shared helper) no longer fire for non-scalar selections. No domain-file
      edits were needed — both domain guards already call the kit helper.
- [x] 2.3 Evidence: kit/policy suite 17 passed (9 new selection-scalar tests,
      including preserved missing-amount rejection for scalar selections);
      kit/settlement-runtime 68 passed (5 new declaration/coherence tests);
      kit/negotiation-runtime 7 passed (new: a non-scalar selection reaches
      acceptance through the runtime with no `fields.amount`, `agreed_price` 0);
      kit/alkahest 178 passed; core/buyer priceless-ordering pin (2 new tests).
      Disclosure closed after the fact: the verified hosted release
      (v0.2.0, trust manifest added on main) was staged into `.dist` via
      `gh release download` + `make verify-hosted-release`, and
      kit/hosted-settlement now runs locally — 143 passed including the factory
      declaration. VM domain suites run once the full wheel set is built.
- [x] 2.4 Closeout: `make check-comment-hygiene` clean; imports module-level; no
      roadmap edit owed (gap row remains until the change completes); promotion
      recorded below; design decision updated to record the option-shape carrier
      refinement.

## 3. Registration-owned pre-terms dispatch

- [x] 3.1 `MechanismRegistration.accepted_obligation_builder` +
      `AcceptedObligationArtifacts` (obligation, scalar-coherent `amount`,
      mechanism-namespaced `service_terms`) with registry dispatch
      `build_accepted_obligation` enforcing role, section, mechanism identity,
      scalar coherence, and the service-terms namespace. The hosted mechanism
      rebuilds its canonical duration-scaled obligation in
      `kit/hosted-settlement` (147 passed — suite now runnable locally);
      contact-exchange builds its amountless introduction obligation
      (kit suites 78 + 20 passed). Verification and route/status projection
      hooks deliberately deferred to Sections 5.1 and later — the accepted
      branch inventory showed obligation construction is the load-bearing
      pre-terms hook.
- [x] 3.2 Bare metal replaced as the template: `_open_exact_selection`
      resolves the mechanism once from the selection and dispatches through
      `BareMetalStorefrontSettlementComposition.accepted_obligation_dispatch()`
      (hosted-only default for runtimes composed without settlement config);
      the domain keeps trusted-physical-facts validation keyed on the option's
      `bare_metal` params — the option shape, not the mechanism — and its
      `bare_metal.v1` service terms, with mechanism service terms merged from
      the artifacts. `hosted_binding`'s rebuild-verify delegates to the same
      kit builder, so accept and verify share one definition (hosted lifecycle
      test green through the new path). The provision envelope gained the
      non-provisioning shape (`access_method: "none"`, no SSH key; every
      provisioning arm still requires credentials). Evidence: bare-metal
      domain 73, storefront 99 (6 new dispatch tests incl. non-scalar accept,
      uncomposed-mechanism/tampered-option/proposed-amount rejections), buyer 4.
- [x] 3.3 Api-credits branches replaced. One kit refinement forced by the
      domain: api-credits rates are counted-unit (`per="credit"`), so the
      mechanism gained count scaling — `compute_rate_unit_total` /
      `rate_scales_by_time` in `market_core.schemas`, and the stripe
      builder picks its scaling input (`duration_seconds` vs
      `unit_quantity`) from the rate itself, keeping rate arithmetic
      opaque inside the mechanism. `_hosted_policy_state` admits any
      dispatched mechanism, `_accepted_selection_artifacts` builds
      through the composition's `accepted_obligation_dispatch()` (kit
      `default_hosted_selection_dispatch` — moved from bare metal to
      `kit/hosted-settlement` as the one shared definition — for
      runtimes composed without settlement config), and
      `load_api_credit_hosted_agreement` rebuild-verifies against the
      same builder, deleting the domain's duplicate quantity-pricing
      arithmetic. Evidence: apicredits storefront 76 (5 new dispatch
      tests incl. non-scalar amountless accept with merged mechanism
      service terms, uncomposed-mechanism and tampered-amount
      rejections, composition dispatch surface); core 91 (4 new rate
      helpers); kit/hosted-settlement 153 (4 new: counted-rate build,
      quantity requirement, time-rate precedence, kit default dispatch);
      bare-metal storefront 111 re-pointed and green.
- [x] 3.4 VM branches replaced on the same template:
      `_accepted_selection_artifacts` dispatches through
      `VmSettlementComposition.accepted_obligation_dispatch()`, the
      duration-scaled amount is now held to the trusted build
      (previously taken as given), and the domain keeps only `vm.v1`
      service terms. `load_hosted_agreement` deliberately keeps its
      field-level checks: legacy card obligations
      (`payment_method_types`) are recovery-only and cannot be rebuilt
      through the builder. Evidence: VM storefront 1093 passed (3 new
      dispatch tests; 1 pre-existing `offering_mode` failure on main,
      unrelated); the round-hook suite's legacy-option rejection now
      pins the dispatch path.
- [x] 3.5 Closeout: hygiene clean; imports module-level; ROADMAP Goal 6
      narrative and gap row updated (pre-terms dispatch complete in all
      three storefront domains); the no-per-domain-conditional rule is
      already the `market-composition` spec delta of this change;
      promotion rows below.

## 4. Deal-identity convergence

- [x] 4.1 The live settle-start paths already write the record at the escrow
      commit flow in all three domains (`SettlementJobCoordinator` runs
      `register_plan` + `adopt(mechanism_ref=escrow_uid)` before
      `reserve_start`; bare metal adopts inline), so the substance was the
      backfill: `core_storefront.escrow_identity.
      backfill_escrow_obligation_records` re-registers the accepted plan
      from the negotiation thread and adopts the escrow uid for every
      `escrows` row with no `settlement_obligations` record, wired at
      startup in all three storefronts. Adopted-only records carry no
      `fulfillment_ref`, so the servicing sweep never touches them —
      lifecycle stays with the legacy mechanism surface; identity is
      neutral. Pre-plan rows (no persisted settlement plan) are skipped
      with a log line: their identity cannot be derived. Evidence:
      bare-metal `test_escrow_identity_backfill.py` (record created with
      `mechanism_ref == escrow_uid`, second run 0, planless row skipped).
- [x] 4.2 Alkahest status projections now expose the neutral identity:
      `obligation_ref` added to `SettleStatusResponse`, the VM and
      api-credits settle serializers, and the bare-metal settle/status
      responses — cross-mechanism tooling correlates by `obligation_ref`
      from every mechanism surface (the VM deals-heartbeat fallback
      already resolved records by `mechanism_ref`). Evidence: bare-metal
      storefront 113 (settle idempotency test now pins the exposed ref),
      VM 1093, apicredits 76, core/storefront 148.
- [x] 4.3 Closeout: universal-identity vocabulary promoted to
      `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities`
      (`obligation_ref` paragraph beside the `fulfillment_uid` note);
      hygiene clean.

## 5. Alkahest vocabulary and verification hook

- [x] 5.1 `MechanismRegistration.settlement_verifier` added;
      `verify_escrow_for_settlement` moved verbatim from
      `core_storefront.escrow_verification` into
      `market_alkahest.escrow_verification` (function-local soft imports
      of the kit's own codecs hoisted to a module-level `_codecs`
      attribute so the established `market_alkahest.alkahest` patch seam
      survives) and installed on `create_alkahest_registration()`. All
      three domain contracts now wire
      `verify=create_alkahest_registration().settlement_verifier`; the
      bare-metal runtime's default `escrow_verifier` resolves from the
      registration; the VM `utils/escrow_verification` shim re-exports
      from the kit; the core module is deleted. Evidence: kit/alkahest
      179 (new pin: the registration owns the verifier), VM storefront
      1093, bare-metal 113, apicredits 76.
- [x] 5.2 The kit's verbatim carrier copies are the single definition.
      One reality the draft missed, recorded in `design.md`: core cannot
      import a mechanism kit, so "core re-exports" is realized as
      tombstoned transitional aliases — an ownership note now marks the
      core block, kept only for the wire models core still types
      (negotiation/listing carriers), to be retired with a contract
      change. The named residual accessor consumers are repointed:
      `escrow_verification` (moved into the kit), core `refund` (lazy
      accessor import → `market_alkahest.schemas`, matching
      `token_transfer`'s existing soft-dep pattern), VM `cli_publish`
      (`accepted_token_address` → kit; `primary_rate_value` stays core
      as the mechanism-neutral price lens). `RateValue`,
      `SettlementOption`, `compute_rate_total` stay core as designed.
- [x] 5.3 Closeout: hygiene clean; core/storefront 148, core 91,
      kit/settlement-runtime 78, core/buyer 105 all green; design
      decision recorded; promotion row below.

## 6. Discovery filters and residual literals

- [ ] 6.1 Option-aware registry filters (token, and the mechanism-filter decision
      recorded in `design.md`'s open question).
- [ ] 6.2 Remove residual literals: buyer hosted transport `"fiat.stripe.v1"`
      (`core/buyer/src/core_buyer/hosted_settlement.py:182`), static seller CLI
      mechanism mounts, Stripe's inline option-ID hash → `derive_settlement_option_id`.
- [ ] 6.3 Closeout.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Buyer acceptance validates the funded obligation strictly against the advertised option but does not compare seller `service_terms`, which carry negotiation-established service context the option cannot predict | `openspec/specs/buyer-orchestration/spec.md` (promote at synchronization) |
| Scalar participation is a registration declaration carried to counterparties through the option shape (an `amount` rate ⇔ bargained through `fields.amount`), with `build_option` enforcing coherence; non-scalar selections negotiate take-it-or-leave-it and order as priceless | `openspec/specs/negotiation-protocol/spec.md` and `openspec/specs/settlement-configuration/spec.md` (promote at synchronization) |
| Accepted obligations are constructed by the registration (`accepted_obligation_builder` → `AcceptedObligationArtifacts` with scalar-coherent amount and mechanism-namespaced service terms); domains resolve the mechanism once from the selection and keep only domain semantics, keyed on option shape rather than mechanism ID | `openspec/specs/market-composition/spec.md` (promote at synchronization) |
| Rate arithmetic is mechanism-owned: the rate's own unit decides its scaling input — time units scale by the negotiated duration, counted units by the negotiated unit quantity (`compute_rate_unit_total`), both carried in the acceptance context | `openspec/specs/settlement-configuration/spec.md` (promote at synchronization) |
| Legacy hosted card obligations are recovery-only: reload paths that admit them keep field-level verification, since a builder rebuild cannot reproduce their pre-profile params | `openspec/specs/market-composition/spec.md` (promote at synchronization) |
| Settlement verification is a registration hook (`settlement_verifier`); mechanism-specific call signatures stay at the mechanism's surface, but ownership lives on the registration | `openspec/specs/settlement-configuration/spec.md` (promote at synchronization) |
| Alkahest-shaped carriers are kit-owned; core keeps tombstoned verbatim aliases only for the wire models it still types, because core cannot import a mechanism kit | `openspec/specs/market-composition/spec.md` (promote at synchronization) |
