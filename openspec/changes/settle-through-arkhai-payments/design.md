## Context

The payments service's cross-product decisions are recorded in `arkhai-io/arkhai-payments` (`docs/issues/scm-settlement-port.md`); its wire contract is JSON Schema in that repository (`schema/payments.schema.json`) with test vectors, so this repository generates pydantic models rather than importing TypeScript.

A mandate is `{from, to, parts, deal, fee, authorities, nonce, expires}`. Parties and authorities are Arkhai account UUIDs. Each part is `once` with an asset, an amount and a hold. The transaction id is `sha256(JCS(mandate))`, so a retried approval converges on one transaction and one receipt. The receipt is Ed25519-signed with `kit/identity` framing (`arkhai.payments.receipt.v1`).

## Decisions

### Pipeline, not a shared escrow interface

Each stage consumes its predecessor's output and owns the translation into its own form. The listing is opaque to core except for its slots and which kit fills each, so buyers and registries can filter by kit, and registries may restrict kits. Behavior is discriminated dispatch on the mechanism identifier, which the registration surface in `kit/settlement-runtime` already provides.

Rejected: a mechanism-neutral signal vocabulary (start/stop/reverse or collect/reclaim) in core. Nothing but the mechanism reads it, and each domain needs explicit compatibility with each mechanism anyway.

### The agreement is the negotiation stage's output

On acceptance the seller emits one agreement object holding only the accepted terms, since terms are the only output negotiation exposes; there is no universal meaning to a transcript. Both sides keep the exact bytes from the accept response and neither rebuilds it, so serialization differences cannot produce two hashes. A sketch for the current runtime:

```text
Agreement = {
  negotiation_id, listing_id, listing_hash,
  buyer, seller: Identity,
  settlement: {option_id, mechanism, asset, rates, params},   # the settle stage's section, carried unread
  settlement_params: <buyer mechanism inputs>,
  amount, asset, duration_seconds, start_utc,   # start is explicit; "now" is resolved at acceptance
  provision_terms: <domain wire>,
  accepted_at,
}
```

### The settle stage defines the deal hash

`arkhai.payments.v1` commits to `sha256(JCS(agreement))` (RFC 8785; the Python side uses `rfc8785`). `derive_settlement_option_id`'s `json.dumps(sort_keys=True)` is not JCS and is not reused for it.

### The seller derives the mandate; the buyer confirms

The payments service never parses the agreement, so the two can evolve independently. The seller's kit derives the mandate and returns it with the agreement in the accept response:
- `from`: the buyer's Arkhai account, which the buyer supplies as `payer_account` in its `SettlementSelection.params` and the Agreement carries as `settlement_params`; `to`: the payee account in the option params. Core treats both params maps as opaque.
- one `once` part: the agreed amount in the option's asset (payments notation, e.g. `USD/2`), held for `start_utc − accepted_at + duration_seconds + window`. The window is declared in the option params, so buyers see it before negotiating, and it absorbs a late provisioning start.
- `fee`: the service's published fee policy.
- `authorities`: `reverse` lists the seller and Arkhai's dispute authority, which the service requires; `start` and `stop` are empty.
- `nonce`: fixed, since `negotiation_id` already makes each agreement unique.

The transaction id is `sha256(JCS(mandate))`, so both sides know it before approval. The buyer's kit checks the mandate against the agreement and its own policy (payee, amount, hold, `deal`) and approves it, attaching the agreement. Both sides poll `GET /transactions/{id}`; the seller provisions once the receipt matches. A push hook from the payments service is expected to replace polling (see Resolved Questions).

For bare-metal, the buyer calls seller settlement with only the negotiation ID. The seller derives the deterministic transaction ID from the accepted mandate and polls the payments service. Acceptance stores the mandate in shared opaque `negotiation_threads.settlement_data` beside exact `agreement_bytes`; receipt verification records domain-owned transaction/receipt evidence as `settlement_verified`. This is a domain-owned evidence record, not an escrow row or `SettlementPlan`. Fulfillment resolves the same record by negotiation ID and still uses the accepted selected-site binding before any provisioning effect.

All three domains use that shared mandate location and return it through negotiation responses and `NegotiationOutcome`. VM uses the same negotiation-scoped mandate and signed-receipt evidence. Its existing local `escrows` table stores only physical provisioning progress under the negotiation ID for payments, with no chain/address, plan, or obligation. The foreground task and recovery sweeper share the existing convergence lease and durable physical fulfillment ID; recovery rechecks the stored receipt against the exact accepted Agreement before any physical effect. The VM buyer's Arkhai account is `[vms].payer_account`, not its marketplace signer or a payments-service configuration field.

Agreement timestamps may contain fractional seconds. Mandate derivation preserves the Agreement bytes/hash, rounds the acceptance-to-start interval up for the whole-second hold, and rounds approval expiry down. Domain adapters do not rewrite accepted timestamps.

### Depositing the agreement

Approval may carry the agreement as an attachment, which the service checks against `deal` and keeps for disputes. If the seller's kit is set to deposit and the snapshot shows no agreement, it attaches it itself. The listing option declares the setting, so buyers can see it and filter on it: it gives the deal Arkhai's dispute fast path, which sellers without a reputation can advertise. Any party could deposit on its own, so a buyer's protection is this transparency, not a veto.

### Stateless kit

Shared typed registration, configuration, and owner-scoped client provision live in `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`. A selected outcome without an escrow proposal enters the domain's `agreement_settlement` stage through `make_settle_hook`. Buyer seller-settle requests contain only negotiation ID; pending receipts return retryable pending, completed calls are idempotent, and nonterminal physical or issuance progress is re-driven under the same durable identity.

Every call goes to the payments service: approve and attach (buyer), poll and attach (seller), `reverse` (seller refund). Headless callers authenticate with WorkOS user-scoped API keys for their owner's Arkhai account. Hold release and fee collection happen in the service.

The kit also exports a typed `MechanismRegistration` for publication inputs and
public option filtering. Its client factory, accepted-obligation builder, and
settlement verifier remain unset; compositions use the registration without routing
payments transactions through the conditional-escrow lifecycle engine.

## Superseded changes

Built on `fiat.stripe.v1` and `kit/hosted-settlement`: `consume-expanded-stripe-funding`, `add-api-credits-hosted-settlement`, `add-bare-metal-hosted-settlement`, `bind-one-hosted-release-coordinate`, `carry-the-payer-return-address`, `project-an-authoritative-funding-loss`, and the hosted sections of `disburse-a-settlement-disposition`. The old service never ran with production money, so nothing deployed needs migration. Archive or withdraw them when this change is accepted.

## Deferred

- **Identity slot.** `kit/identity` already dispatches by scheme, but the listing carries one `seller_principal`. Revisit when a listing needs to advertise several identity schemes.
- **Negotiation slot.** `kit/negotiation-runtime` builds in one protocol (counter/accept/exit, an amount, `AgreementTerms`). Revisit when a second negotiation protocol arrives, e.g. auctions.
- **Per-stage kit declarations** (which predecessor outputs a stage accepts, for filtering). Revisit with the negotiation slot.

## Resolved Questions

- §1 is deferred: existing `SettlementObligation` claimant, expiration, and condition fields and the shared conditional-escrow runtime remain. Moving those carriers and listing fields into Alkahest is not implemented or promoted. The Agreement carries canonical parties; the Arkhai mandate's `to` comes from its payment option, and its path does not construct an obligation.
- `kit/settlement-runtime` stays where it is for now: Alkahest, contact exchange, core and the domains all use it. Arkhai payments keeps no client-side servicing state and bypasses it, producing no settlement plan or obligation; moving escrow semantics out of core is a follow-up change.
- Both kits poll the payments service by transaction ID; the storefront relays nothing. A push hook from the payments service is tracked as an idea in arkhai-payments (`transaction-webhooks`) and is expected to replace polling.
- The SDK's default window is `P7D`. The payments service enforces no minimum; chargeback exposure is covered by its cash reserve.

## Closeout disposition

Permanent specifications are edited directly for implemented §2–§3 behavior. The change remains active for verification; it is not archived. Strict validation passes after delta scenario headings are aligned with the promoted contract. Archive preview reports already-promoted ADDED requirements; eventual archival must skip spec updates rather than replay the delta over these permanent edits. §1 delta statements that remove core escrow fields, move the shared port into Alkahest, or remove legacy Alkahest listing carriers remain deferred and are not synchronized as current guarantees.

The hosted-document cleanup includes all 18 destinations named in §3.2, plus their adjacent servicing, publication, marketplace-identity, physical-provisioning, and API-credit contracts and repository testing/deployment guides. Historical hosted changes remain in `openspec/changes`; rejected legacy config names and forbidden-import assertions deliberately remain. No Stripe profile, credential, authorization, or operation is mapped to Arkhai payments.

Implementation evidence retained from §3: Stripe removal commits `aa97accd` and `c39090ea` preserved Alkahest/contact coverage, with 2,251 regressions (one skipped), 42-source typing, wheels/CLI/Helm checks. VM fractional-time derivation and restored admin diagnostics were separate repairs. VM controlled HTTP/payment/delivery smoke observed pending → provisioning → ready with one delivery; it is not live-ledger or hardware evidence. Bare-metal ran no payment-service smoke. API-credit E2E was unavailable because the local payments service was down. Global integration, deployment, and typing qualification remains §4.1-owned.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Negotiate → settle → provision; core defines only shared-reader carriers, not one escrow adapter API. | `docs/development/ARCHITECTURE.md#composition-from-above-and-below`; `openspec/specs/market-composition/spec.md#requirement-deals-compose-negotiate-settle-and-provision-stages` and companion `architecture.md#typed-phase-boundaries` |
| Acceptance fixes exact Agreement bytes and explicit start; core does not define a universal deal hash. | `openspec/specs/negotiation-protocol/spec.md#requirement-deterministic-agreed-terms`; `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| Buyer supplies payer_account in selection params and Agreement settlement_params, separately from marketplace identity and trusted service policy; VM uses [vms].payer_account. | `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials`; `openspec/specs/marketplace-identity/spec.md` |
| All domains return and persist the seller-derived mandate in shared opaque settlement_data beside agreement_bytes in negotiation_threads. | `openspec/specs/negotiation-protocol/spec.md#requirement-acceptance-persists-opaque-settlement-data`; `openspec/specs/settlement-servicing/spec.md#requirement-negotiation-scoped-payment-settlement-converges` |
| make_settle_hook sends selected outcomes without escrow proposals to the domain agreement_settlement stage. | `openspec/specs/market-composition/spec.md#requirement-buyer-dispatch-preserves-agreement-only-settlement`; companion `architecture.md#agreement-based-payment-composition` |
| JCS deal/transaction hashes, declared hold window, fixed nonce, fee/reverse policy, Agreement deposit, and fractional-time rounding. | `openspec/specs/settlement-servicing/spec.md#requirement-arkhai-payments-settles-charge-first-from-an-agreement`; companion `architecture.md#charge-first-payment-settlement` |
| Buyer approves and polls; seller settle accepts only negotiation ID, polls the same transaction, verifies the signed receipt, returns retryable pending, and re-drives nonterminal progress idempotently. | `openspec/specs/buyer-orchestration/spec.md#requirement-payment-buyers-preserve-accepted-state`; `openspec/specs/settlement-servicing/spec.md#requirement-negotiation-scoped-payment-settlement-converges` |
| VM and bare-metal receipt evidence gates selected-site fulfillment and recovery; VM provisioning progress is not a chain escrow or obligation. | `openspec/specs/physical-provisioning/spec.md#requirement-signed-payment-receipts-gate-selected-site-execution` and companion `architecture.md#signed-payment-receipt-boundary`; `docs/development/ARCHITECTURE.md#fulfillment` |
| API-credit receipt verification precedes authority-owned exact-once grants and private credential delivery; uncertain issuance is recoverable. | `openspec/specs/api-credits/spec.md#requirement-payment-grants-are-principal-bound-and-exact-once` and companion `architecture.md#payment-composition-and-recovery` |
| Shared registration/config/client provider lives in payments settlement_config.py; Arkhai payments is a peer of Alkahest, with no wallet requirement or conditional-escrow hooks. | `openspec/specs/settlement-configuration/spec.md#requirement-payments-configuration-separates-accounts-and-credentials` and companion `architecture.md#registration-and-ownership`; `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-registers-as-a-peer-settlement-mechanism` |
| External payments authority owns ledger, holds, fees, disputes, cash movement, and provider state; stateless generated-model kit uses owner-scoped WorkOS credentials and identity-framed Ed25519 receipts. | `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-authority-remains-external`; `openspec/specs/deployment-state/spec.md` and companion `architecture.md#arkhai-payment-consumers`; `docs/development/ARCHITECTURE.md#authority-boundaries` |
| Stripe mechanism/client, funding/setup/recovery surfaces, and hosted release/profile matrix are not current behavior; legacy settings are rejected, not converted. | `openspec/specs/settlement-configuration/spec.md#requirement-settlement-configuration-selects-explicit-peer-mechanisms`; `openspec/specs/storefront-publication/spec.md#requirement-payment-publication-discloses-mandate-policy`; `openspec/specs/cli-query-language/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md#settlement-consumer-configuration-and-cutover` |
| Consumer tests prove SCM behavior only; live payment/provider and physical delivery claims need their actual authority. | `openspec/specs/test-compatibility/spec.md#requirement-payment-evidence-is-attributed-at-its-owning-boundary` and companion `architecture.md#payment-evidence-ownership`; `docs/development/TESTING.md#marketplace-identity-verification`; `openspec/specs/README.md#settlement-documentation-ownership` |
| Goal 6 names current peer payment composition and deferred escrow isolation; Goal 4 and qualification gaps no longer point to superseded hosted adopters. | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice`, `#goal-4--make-a-domain-a-composition-of-kit`, and `#payment-qualification-boundaries`; `openspec/changes/README.md#roadmap-goal--make-the-settlement-mechanism-a-composed-choice` |
| Moving escrow fields and the conditional-escrow port into Alkahest, additional listing slots, per-stage declarations, push payment notification, and non-fixed-interval payments. | Deferred, not promoted as implemented behavior; retained in this design and §1. Existing escrow carrier contract remains in `openspec/specs/settlement-servicing/spec.md#requirement-mechanism-neutral-plan-carrier`. |
