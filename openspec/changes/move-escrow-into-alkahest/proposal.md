## Why

Escrow is Alkahest's model, but it still sits in shared carriers. `SettlementObligation` carries `claimant`, `claimant_principal`, `expiration_unix` and `conditions` as if they were universal. `MechanismRegistration` has escrow-shaped hooks: `client_factory` returns a `ConditionalEscrowClient`, and `accepted_obligation_builder` builds obligations. Core buyer orchestration carries `accepted_escrow_proposal`. This was §1 of `settle-through-arkhai-payments`, deferred there because extraction touches persisted negotiation and obligation records and the shared runtime.

## What Changes

- Escrow fields leave `SettlementObligation` and core buyer orchestration and become Alkahest's `settlement_data` and option params.
- `ConditionalEscrowClient`, the obligation journal and the servicing jobs become a library used internally by Alkahest and contact exchange. Domains and core stop driving a servicing lifecycle. Each mechanism's settle stage (see `route-settlement-by-mechanism`) calls into it.
- `MechanismRegistration` shrinks to publication, readiness and buyer compatibility. `client_factory`, `accepted_obligation_builder` and `settlement_verifier` leave it. Each registration declares a typed resource model, replacing the untyped `resources: Mapping[str, Any]` bag.
- The legacy path for negotiations without a `SettlementOption` is deleted. Every accepted deal has an Agreement.
- The Agreement becomes a deal's complete settlement input: an Alkahest option carries its
  release condition and the Agreement its escrow expiry, so each party derives the plan,
  the escrow terms, and the obligation identity from the Agreement alone, and the accept
  reply carries nothing derivable from it. `unbacked-bare-metal-listings` removes the
  reply's `accepted_escrow_terms` and has the buyer derive its escrow and compare it with
  the seller's plan; this is the end state that design records.
- Rename the kit/site quota ledger's `escrow_uid` correlation API/persistence coordinate to a neutral name with its owning ledger and all consumers changed together. Credits issuance currently supplies its negotiation-derived fulfillment ID there, not an escrow or grant alias; domain-local renaming must not create another compatibility projection. This includes shared capacity `deal_ref` consumers, not just the credits service.
- Escrow-shaped code leaves the foundation kits and the buyer core, so that no kit
  other than Alkahest's holds Alkahest in its scope (`ARCHITECTURE.md`, "Where the
  current tree diverges"):
  - `kit/policy/scalar_policies.py` splits. The scalar-amount half — bisection,
    listed price, counter guards, wire-amount parsing, `selected_settlement_artifact`
    — is mechanism-neutral (Arkhai payments uses it; contact exchange declines it)
    and stays in `kit/policy`. The escrow-kind half — `proposal_escrow_kind`, whose
    function-local `market_alkahest.address_to_slot` import is `kit/policy`'s only
    upward edge, `_escrow_kind_lookup_keys`, `_normalize_demands_for_chain`,
    `_normalize_selected_demand`, `_accepted_escrow_for_proposal`,
    `make_escrow_kind_dispatch_middleware`, and the verbatim-extraction compatibility
    shim — moves to `market_alkahest.policies`.
  - `core_buyer.negotiation_client` builds its chain with
    `make_escrow_kind_dispatch_middleware(policies_by_kind, chain_config_paths=…)`:
    the buyer core dispatches policy by Alkahest escrow kind and threads chain
    configuration paths to do it. Per-kind dispatch is one case of dispatch by the
    selected settlement option, which the shrunken `MechanismRegistration` carries:
    `kit/policy` owns a registration-keyed dispatch middleware, the Alkahest
    registration contributes the kind resolver, and `core_buyer` composes from
    installed registrations without knowing chains.
  - `kit/alkahest/aggregation.py`'s `resolve_best_price_timeout` imports
    `market_config` function-locally to read `[aggregation].best_price_timeout` from
    the user's configuration — the kit's only upward edge, with one consumer,
    `arkhai_vms_buyer/aggregation.py`. The buyer resolves the timeout and passes it;
    the kit stops reading configuration. The same module registers
    `market.buyer_aggregation_policies` entry points, so a mechanism kit every
    package imports is also a buyer-side extension; whether the policies move to
    the Alkahest buyer plugin is decided with the resource-model work above.
  - `core_storefront`'s `refund.py`, `token_transfer.py`, and `escrow_identity.py`
    are Alkahest and EVM helpers in the storefront role package, the first two
    importing `market_alkahest.schemas` and `web3` without declaring them. They move
    to `kit/alkahest`, in coordination with
    `kit-owned-storefront-auth-and-persistence`, which decides what remains of
    `core_storefront`.
  - The Alkahest client factory, `kit/storefront/alkahest_clients.py`, and the
    `build_alkahest_clients` callback on `core_storefront.app_lifecycle`, become
    the Alkahest registration's typed resource model; see
    `kit-owned-storefront-shell`'s design for which change lands the lifespan step.
  - `market_core.schemas`'s Alkahest-named escrow fields leave with
    `SettlementObligation`'s, which the first bullet above already moves.
- The VM listing and negotiation specializations stop importing `kit/alkahest`,
  since neither carries a mechanism in its name and so neither may know one
  (`ARCHITECTURE.md`, "Scope"):
  - `arkhai_vms_listings` types `accepted_escrows` with `AcceptedEscrow` and
    `EscrowDemand` and resolves `ERC20TokenMetadata` through
    `resolve_token_cached` in `models.py` and `resources.py`, and reads
    `accepted_token_address` and `primary_rate_value` in `pricing.py` and
    `buyer_cli.py`.
  - `arkhai_vms_negotiation`'s `policies.py` validates an `EscrowProposal` and
    normalizes it against the listing's accepted escrows through a
    function-local import.
  - Each reaches the escrow-shaped data through the Alkahest registration or the
    VM settlement codec, which legitimately knows its mechanism. The listing's
    wire shape is unchanged; removing escrow from it is
    `drop-escrow-from-shared-wire`'s. `enforce-package-layers`'s exceptions table
    carries both edges under this change, and the rows are deleted when the
    imports are.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: becomes a library owned below the Alkahest and contact-exchange kits.
- `settlement-configuration`: hooks are reduced, and resources are typed.
- `buyer-orchestration` / `negotiation-protocol`: escrow-free outcomes.

## Non-Goals

- Changes to the listing and registry wire format (`drop-escrow-from-shared-wire`).

## Dependencies

- `route-settlement-by-mechanism` (archived 2026-10-09): stages must exist before the escrow branch they replace can be removed.

## Compatibility

There is no backwards-compatibility promise. Persisted negotiation and obligation schemas are rebuilt rather than migrated.
