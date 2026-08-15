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
      Disclosed: kit/hosted-settlement's suite was not run — it requires the
      verified released client wheel, not staged locally; its one-line factory
      edit is exercised by the settlement-runtime registration suite. VM domain
      suites likewise not run here (hosted wheel dependency); their guard path is
      the shared kit helper covered above.
- [x] 2.4 Closeout: `make check-comment-hygiene` clean; imports module-level; no
      roadmap edit owed (gap row remains until the change completes); promotion
      recorded below; design decision updated to record the option-shape carrier
      refinement.

## 3. Registration-owned pre-terms dispatch

- [ ] 3.1 Extend `MechanismRegistration` with the pre-terms hooks the branch sites
      need (proposal interpretation, accepted-artifact construction, verification,
      route/status projection), designed against the concrete branch inventory in
      `design.md`.
- [ ] 3.2 Replace the bare-metal branches first (smallest domain, contact-exchange's
      first composition target), as the template.
- [ ] 3.3 Replace the api-credits branches.
- [ ] 3.4 Replace the VM branches, sequenced after the touching
      `consume-expanded-stripe-funding` tasks land.
- [ ] 3.5 Closeout, promoting the no-per-domain-conditional rule to
      `openspec/specs/market-composition/spec.md`.

## 4. Deal-identity convergence

- [ ] 4.1 Write the Alkahest `settlement_obligations` record at the same commit point
      as the `escrows` insert, with `escrow_uid` as `mechanism_ref`; idempotent
      backfill for existing rows.
- [ ] 4.2 Point cross-mechanism status/reporting at `obligation_ref`.
- [ ] 4.3 Closeout, promoting the universal-identity vocabulary to
      `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities`.

## 5. Alkahest vocabulary and verification hook

- [ ] 5.1 Registration-owned verification hook; Alkahest escrow verification moves
      behind it and out of `core_storefront.escrow_verification`'s injected-function
      shape.
- [ ] 5.2 Move `AcceptedEscrow`/`EscrowProposal`/`EscrowDemand`/`accepted_*`
      accessors to `kit/alkahest` (single definition, core re-exports then
      tombstones); `RateValue`, `SettlementOption`, `compute_rate_total` stay core.
      Repoint the residual consumers (`escrow_verification`, `refund`,
      VM `cli_publish`).
- [ ] 5.3 Closeout.

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
