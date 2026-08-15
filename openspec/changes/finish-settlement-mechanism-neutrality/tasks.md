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

- [ ] 2.1 Add the scalar-participation declaration to `MechanismRegistration`
      (`kit/settlement-runtime/src/market_settlement_runtime/configuration.py`),
      with `alkahest.v1` and `fiat.stripe.v1` declaring the scalar so existing
      behavior is unchanged by construction.
- [ ] 2.2 Scope the guard: `missing_amount` rejection and scalar policy routing
      consult the resolved mechanism's declaration
      (`kit/policy/src/market_policy/scalar_policies.py`, the domain guards such as
      `domains/vms/negotiation/policies.py:203-210`); a declining mechanism routes to
      the exact-accept path and buyer ordering treats its listings as priceless.
- [ ] 2.3 Tests: characterization for both existing mechanisms unchanged
      (missing-amount rejection preserved); a fake non-scalar registration reaches
      acceptance through the kit negotiation runtime with no `fields.amount`.
- [ ] 2.4 Closeout: as 1.4, promoting the declinable-scalar contract to
      `openspec/specs/negotiation-protocol/spec.md`.

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
