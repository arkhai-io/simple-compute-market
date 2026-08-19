# Design

## Context

Verified 2026-08-15 against `7155d014`, after the hosted-settlement merge. The
mechanism seam exists and is import-fenced (`kit/settlement-runtime` forbids
`market_alkahest`, provider SDKs, and web frameworks in its unit boundary tests). Both
mechanisms compose through `MechanismRegistration` factories
(`kit/alkahest/src/market_alkahest/settlement_config.py:566`,
`kit/hosted-settlement/src/market_hosted_settlement/settlement_config.py:989`) named
only in five domain composition roots.

The residue, precisely:

- Per-domain mechanism conditionals: `domains/vms/negotiation/policies.py:122`
  (selection vs. Alkahest proposal branch),
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py:449` and `:355`
  (accepted artifacts, hard-coded `"fiat.stripe.v1"` at `:377`), the settle
  controllers' hosted-vs-escrow rejection branches, and the equivalent arms in
  api-credits and bare metal.
- Mandatory scalar: `kit/policy/src/market_policy/scalar_policies.py:46-62`
  (`fields.amount`), `:75-104` (Alkahest kind resolution), `:538-552` and `:799-819`
  (rate/literal reads); rejection at `domains/vms/negotiation/policies.py:203-210`.
  The kit negotiation runtime already takes `amount_from_proposal` /
  `proposal_from_amount` as injected hooks
  (`kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py:192-193`) — but
  they are domain hooks, not registration hooks, and cannot be declined.
- Dual identity: `escrows(escrow_uid PRIMARY KEY)`
  (`core/storefront/src/core_storefront/sqlite_client.py:734-760`) plus
  `/api/v1/settle/{escrow_uid}` for Alkahest; `settlement_obligations` keyed by
  `obligation_ref` with a unique `mechanism_ref` index plus `/api/v1/settlements` for
  hosted. Alkahest verification is still
  `core_storefront.escrow_verification.verify_escrow_for_settlement`, injected by all
  three domains.
- Core-owned Alkahest shapes: `AcceptedEscrow`, `EscrowProposal`, `EscrowDemand`, and
  the `accepted_*` accessors in `core/src/market_core/schemas.py`, duplicated in
  `kit/alkahest`; residual core consumers are `escrow_verification`, `refund`, and the
  VM `cli_publish`.
- Literals: `core/buyer/src/core_buyer/hosted_settlement.py:182`; static
  `stripe_app`/`alkahest_app` mounts in the VM seller CLI; Stripe's inline option-ID
  hash (`settlement_config.py:840-855`).
- Registry filters project only `$.accepted_escrows[*]`
  (`core/registry/filter-spec.yaml:210,216`), while `listing_shape` already accepts
  option-only listings via `anyOf`.
- Apparent defect: `core/buyer/src/core_buyer/negotiation_client.py:452` rejects any
  non-empty `service_terms` on the option-selected path; the VM hosted seller emits
  `service_terms["vm.v1"]` at acceptance.

## Goals / Non-Goals

**Goals:** a third mechanism composes with zero per-domain conditional arms; a
mechanism may decline the scalar path; one durable deal identity for every mechanism;
Alkahest vocabulary owned by `kit/alkahest`; existing behavior preserved for both
mechanisms.

**Non-Goals:** new mechanisms, hosted-authority/funding changes, retiring the
`escrows` table or `escrow_uid` routes.

## Decisions

### Dispatch at the selection, through the registration

The mechanism is resolved exactly once per deal — from the buyer's
`settlement_selection` (or, on the legacy branch, from the flat proposal's implied
`alkahest.v1`) — and every subsequent mechanism-shaped decision reaches the
registration: proposal interpretation, accepted-artifact construction, verification,
route/status projection. This extends `MechanismRegistration` with the small set of
hooks those branch sites need rather than inventing a second registry. Domains keep
domain-semantic hooks (terms, artifacts content, persistence); they lose the
mechanism conditionals.

### Scalar participation is declared, not assumed

The registration declares scalar participation
(`MechanismRegistration.negotiates_scalar_amount`), but the declaration reaches
counterparties through the *option shape*: a buyer cannot see the seller's
composition, so the published option's rates are the cross-party carrier — an
`amount` rate means bargained-through-`fields.amount`, its absence means
take-it-or-leave-it. This is deliberately symmetric with how `accepted_escrows`
entries already declare scalarness through their rates and literal fields.
`build_option` enforces coherence: a declining mechanism must not publish an
`amount` rate. The shared guards (`proposal_uses_scalar_amount`, the
`missing_amount` rejections, `accept_exact_listing`) read the matched option, so a
scalar-declaring mechanism keeps today's strict behavior, a declining mechanism
negotiates take-it-or-leave-it over its published option, and buyer ordering
treats its listings as priceless — all three fallback paths already existed in
`kit/policy`; the change scoped the guards rather than building new negotiation
machinery. An unmatched selection stays scalar so the invalid-selection rejection
fires instead of an exact-accept shortcut.

### The rate decides its own scaling input

Api-credits priced counted units (`per="credit"`) while the mechanism's
accepted-obligation builder only scaled by duration. Rather than letting the
domain keep its own quantity arithmetic beside the builder, the scaling choice
lives with the rate: `PER_UNIT_SECONDS` units scale by the context's
`duration_seconds`, any other unit is a counted unit scaled by the context's
`unit_quantity` (`compute_rate_unit_total` in core, guarded to uint256).
Domains pass what they know — bare metal and VMs a duration, api-credits a
credit quantity — and never multiply rates themselves. The domain's amount
check reduces to `agreed_amount == built.amount` for scalar mechanisms and
`agreed_amount == 0` for declining ones.

### The hosted default dispatch is kit-owned

`default_hosted_selection_dispatch` (hosted-only accepted-obligation dispatch
for runtimes composed without a settlement config) moved from the bare-metal
storefront into `kit/hosted-settlement`: it contains zero domain semantics, and
three domains now need it. Legacy card obligations stay recovery-only — the VM
agreement reload keeps its field-level verification because a builder rebuild
cannot reproduce pre-profile (`payment_method_types`) params.

### Identity convergence is additive

Every deal gains a `settlement_obligations` record; for Alkahest, `escrow_uid` is
recorded as `mechanism_ref` — the unique index already models exactly this. The
`escrows` table and its route family continue to serve the Alkahest mechanism surface
unchanged. This makes `obligation_ref` the universal correlation key (status,
reporting, cross-mechanism tooling) without a persistence cutover; retiring the legacy
surface becomes a later, evidence-backed contract change.

### `RateValue` stays core; only escrow shapes move

The earlier draft of this change proposed moving the whole rate/escrow vocabulary to
`kit/alkahest`. The hosted mechanism inverted the premise: `SettlementOption.rates`
carries Stripe minor-unit pricing and `primary_rate_value` is the mechanism-neutral
price lens the buyer already uses across both carriers. So the rate shape is core
cross-mechanism vocabulary, and only `AcceptedEscrow` / `EscrowProposal` /
`EscrowDemand` / `accepted_*` accessors — consumed by three residual core sites —
move. The verbatim duplicates in `kit/alkahest` become the single definition.

### Core cannot re-export the kit's carriers

The draft said "core re-exports then tombstones", but the dependency
arrow points the other way: `market_alkahest` depends on `market_core`,
so core cannot import the kit to re-export the moved carriers. The
realized shape: the kit's verbatim copies are the single authoritative
definition, the residual accessor consumers repoint to the kit (core's
`refund` uses the same lazy soft-import pattern `token_transfer` already
established), and core's copies stay as tombstoned transitional aliases
solely for the wire models core still types (negotiation and listing
carriers) until a contract change retires them.

### The defect is verified before it is designed around

The buyer-side `service_terms` rejection contradicts the VM hosted seller's emitted
plan. First reproduce against a live hosted deal; if real, the fix is buyer-side
acceptance of mechanism-namespaced `service_terms`, which
`contact-exchange-settlement-mechanism` also requires. If it turns out unreachable
(the hosted path may bypass that check), record why and leave the guard.

## Risks / Trade-offs

- **[Behavior drift while removing branches]** → Characterization tests for both
  mechanisms' negotiation and settlement flows before each branch site is replaced;
  the branch removal sections land per decision point, not as one sweep.
- **[Collision with `consume-expanded-stripe-funding`]** → It actively modifies the
  hosted adapter, publication, and buyer selection. Sections touching those files are
  sequenced after its corresponding tasks; the purely core/kit-alkahest sections are
  independent and may proceed now.
- **[Scoping the scalar guard weakens it for scalar mechanisms]** → The guard's
  strictness is keyed to the mechanism declaration, and existing rejection tests are
  kept green for `alkahest.v1` and `fiat.stripe.v1` (both declare the scalar).
- **[Convergence writes disagree with legacy rows]** → The Alkahest
  `settlement_obligations` write happens at the same commit point as the `escrows`
  insert; a backfill for existing rows is idempotent on `mechanism_ref`.

## Migration Plan

Additive persistence (new rows beside existing), hook-by-hook branch replacement with
characterization coverage, vocabulary move via re-export-then-tombstone in core.
Rollback at any section boundary is a code revert; no destructive schema step.

## Open Questions

- When does `/api/v1/settle/{escrow_uid}` retire behind the neutral route family?
  Deliberately out of scope; needs deployment evidence after convergence.
- Do registration-owned negotiation hooks subsume the domain's
  `amount_from_proposal`, or compose with it (mechanism extracts, domain adjusts)?
  Leaning compose, since api-credits multiplies by quantity.
- ~~Whether the registry gains a generic `mechanism` filter or only option-aware
  token filters~~ — resolved with the introduction-market profile: both, as
  missing-tolerant option-aware projections (`mechanism` over
  `$.settlement_options[*].mechanism`, token filters over the option-embedded
  escrow template), keeping escrow-carrier legacy listings visible.
