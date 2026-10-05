## Why

Escrow is Alkahest's model, but it still sits in shared carriers. `SettlementObligation` carries `claimant`, `claimant_principal`, `expiration_unix` and `conditions` as if they were universal. `MechanismRegistration` has escrow-shaped hooks: `client_factory` returns a `ConditionalEscrowClient`, and `accepted_obligation_builder` builds obligations. Core buyer orchestration carries `accepted_escrow_proposal`. This was §1 of `settle-through-arkhai-payments`, deferred there because extraction touches persisted negotiation and obligation records and the shared runtime.

## What Changes

- Escrow fields leave `SettlementObligation` and core buyer orchestration and become Alkahest's `settlement_data` and option params.
- `ConditionalEscrowClient`, the obligation journal and the servicing jobs become a library used internally by Alkahest and contact exchange. Domains and core stop driving a servicing lifecycle. Each mechanism's settle stage (see `route-settlement-by-mechanism`) calls into it.
- `MechanismRegistration` shrinks to publication, readiness and buyer compatibility. `client_factory`, `accepted_obligation_builder` and `settlement_verifier` leave it. Each registration declares a typed resource model, replacing the untyped `resources: Mapping[str, Any]` bag.
- The legacy path for negotiations without a `SettlementOption` is deleted. Every accepted deal has an Agreement.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: becomes a library owned below the Alkahest and contact-exchange kits.
- `settlement-configuration`: hooks are reduced, and resources are typed.
- `buyer-orchestration` / `negotiation-protocol`: escrow-free outcomes.

## Non-Goals

- Changes to the listing and registry wire format (`drop-escrow-from-shared-wire`).

## Dependencies

- `route-settlement-by-mechanism`: stages must exist before the escrow branch they replace can be removed.

## Compatibility

There is no backwards-compatibility promise. Persisted negotiation and obligation schemas are rebuilt rather than migrated.
