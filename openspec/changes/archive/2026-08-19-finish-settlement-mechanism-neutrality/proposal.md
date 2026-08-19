# Finish Settlement-Mechanism Neutrality

## Why

The hosted-settlement work delivered the mechanism seam this repository used to lack:
`MechanismRegistration` and `SettlementConfigurationRegistry`
(`kit/settlement-runtime/src/market_settlement_runtime/configuration.py`), the
mechanism-tagged `SettlementOption` carrier accepted by the registry alongside legacy
`accepted_escrows`, a mechanism-neutral durable identity (`obligation_ref` in
`settlement_obligations`) with its own signed route family, and marketplace identities
that need no chain. A second mechanism (`fiat.stripe.v1`) is composed purely from kit,
and a wallet-free seller can publish and settle.

What remains is the residue where mechanism awareness still leaks, and every item is a
place a third mechanism must add one more arm per domain — exactly what the
registration seam exists to prevent:

- Every pre-terms decision point re-implements the same
  `if settlement_selection … else Alkahest` conditional per domain: proposal
  interpretation, accepted-artifact construction, settle-route selection, and status
  projection.
- The scalar-amount negotiation path is mandatory. A proposal without `fields.amount`
  is rejected as `missing_amount` for every mechanism, and the scalar policies still
  read `rates`, `literal_fields`, and Alkahest kind-resolution directly. A mechanism
  cannot decline the scalar path, so take-it-or-leave-it terms are not expressible.
- Deal identity is dual, not neutral: Alkahest deals live in
  `escrows(escrow_uid PRIMARY KEY)` behind `/api/v1/settle/{escrow_uid}`, hosted deals
  in `settlement_obligations` behind `/api/v1/settlements`. Alkahest verification
  remains a domain-injected core function rather than a registration-owned hook.
- The Alkahest-shaped carriers (`AcceptedEscrow`, `EscrowProposal`, `EscrowDemand`,
  the `accepted_*` accessors) are still core-owned, with three residual core
  consumers. `RateValue` is deliberately **not** in this list — the hosted mechanism
  adopted `rates` for minor-unit pricing and `primary_rate_value` is now the
  mechanism-neutral price lens, so the rate shape is cross-mechanism core vocabulary.
- Residual literals: the buyer hosted transport hard-codes `"fiat.stripe.v1"`, the
  seller CLI mounts mechanism command groups statically instead of iterating
  registrations, and the Stripe option builder re-implements the option-identity hash
  instead of calling `derive_settlement_option_id`.
- Registry discovery filters project only `accepted_escrows`, so option-only listings
  are invisible to token/price filtering.
- One apparent live defect: the buyer rejects a seller plan whose option-selected path
  carries non-empty `service_terms`, while the VM hosted seller emits
  `service_terms["vm.v1"]` at acceptance. Verify and resolve.

## What Changes

- Dispatch the pre-terms branch through the registry: resolve the mechanism once from
  the selection/option, then reach proposal interpretation, accepted-artifact
  construction, verification, and route/status selection through
  registration-supplied hooks. Domain code keeps domain semantics; the per-domain
  mechanism conditionals are removed.
- Make the scalar path a mechanism capability: registration-owned negotiation hooks
  (amount extract/inject, ordering hint) replace the domain-global scalar guard. A
  mechanism that declares no scalar negotiates take-it-or-leave-it over its published
  option, and `missing_amount` applies only to mechanisms that declare one.
- Converge deal identity on `obligation_ref`: every deal, Alkahest included, gains its
  `settlement_obligations` record with `escrow_uid` recorded as the `alkahest.v1`
  `mechanism_ref`; the `/api/v1/settle/{escrow_uid}` family remains as that
  mechanism's surface, documented as such. The `escrows` table is not dropped here.
- Give the registration a verification hook so Alkahest escrow verification composes
  the way hosted funding truth already does (through the mechanism client), and move
  the Alkahest-shaped carriers into `kit/alkahest`, repointing the residual core
  consumers. `RateValue`, `SettlementOption`, and `compute_rate_total` stay core.
- Fix the residual literals (buyer hosted transport, static seller CLI mounts, inline
  option-ID hash) and resolve the buyer `service_terms` rejection inconsistency.
- Extend registry filters to project `settlement_options` alongside
  `accepted_escrows` (token and mechanism filters).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: pre-terms mechanism dispatch, verification, and negotiation
  scalar participation are registration-owned; no per-domain mechanism conditionals;
  deal identity is mechanism-neutral for every mechanism.
- `negotiation-protocol`: a mechanism that declares no negotiable scalar negotiates
  take-it-or-leave-it; the scalar guard is scoped to scalar-declaring mechanisms.

Implementation also touches `settlement-configuration`, `settlement-servicing`,
`registry-discovery`, and `buyer-orchestration`; those deltas land with the tasks that
change them.

## Non-Goals

- No new settlement mechanism; `contact-exchange-settlement-mechanism` is the first
  consumer of the completed seam.
- No funding-profile or hosted-authority changes; `consume-expanded-stripe-funding`
  owns those surfaces.
- No removal of the `escrows` table or the `escrow_uid` route family; retiring them is
  a later contract change after convergence proves out.

## Dependencies and Related Changes

- Coordinate with `consume-expanded-stripe-funding`, which is actively modifying the
  hosted adapter, publication, and buyer selection surfaces this change also touches.
  Sequence shared-file sections after its relevant tasks or rebase deliberately.
- Consumed by `contact-exchange-settlement-mechanism`, whose only hard prerequisites
  are the declinable-scalar capability and the `service_terms` acceptance fix.

## Impact

- Affected code: `kit/settlement-runtime` (registration surface),
  `kit/negotiation-runtime` and `kit/policy` (scalar participation), `kit/alkahest`
  (vocabulary and verification hook), the five domain settlement compositions and
  negotiation policies, `core_storefront` (escrow verification, refund, settle
  models), `core_buyer` (hosted transport literal), registry filter-specs and filter
  evaluation, seller CLI mounts.
- Affected tests: registration/dispatch units, negotiation characterization for both
  existing mechanisms, settle-route and identity-convergence integration, registry
  filter coverage for option-only listings.
- Not affected: hosted authority contracts, funding profiles, obligation servicing
  semantics, capacity, fulfillment, provisioning.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — mechanism-neutral deal identity in shared
      vocabulary; settlement-mechanism composition described once.
- [x] Existing subsystem specifications — `market-composition`,
      `negotiation-protocol`, `settlement-configuration`, `settlement-servicing`,
      `registry-discovery`, `buyer-orchestration`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Registration-owned pre-terms dispatch and the no-per-domain-conditional rule —
  `openspec/specs/market-composition/spec.md`.
- Declinable scalar participation — `openspec/specs/negotiation-protocol/spec.md`.
- `obligation_ref` as the universal deal identity with mechanism refs beside it —
  `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities`.
