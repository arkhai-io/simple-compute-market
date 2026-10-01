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
  settlement: {option_id, mechanism, params},   # the settle stage's section, carried unread
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

For bare-metal, the buyer calls seller settlement with only the negotiation ID. The seller derives the deterministic transaction ID from the accepted mandate and polls the payments service. Acceptance stores the mandate with a digest of the exact Agreement bytes; receipt verification atomically records the transaction ID and signed receipt as `settlement_verified`. This is a domain-owned evidence record, not an escrow row or `SettlementPlan`. Fulfillment resolves the same record by negotiation ID and still uses the accepted selected-site binding before any provisioning effect.

VM uses the same negotiation-scoped mandate and signed-receipt evidence. Its existing local `escrows` table stores only physical provisioning progress under the negotiation ID for payments, with no chain/address, plan, or obligation. The foreground task and recovery sweeper share the existing convergence lease and durable physical fulfillment ID; recovery rechecks the stored receipt against the exact accepted Agreement before any physical effect. The VM buyer's Arkhai account is `[vms].payer_account`, not its marketplace signer or a payments-service configuration field.

Agreement timestamps may contain fractional seconds. Mandate derivation preserves the Agreement bytes/hash, rounds the acceptance-to-start interval up for the whole-second hold, and rounds approval expiry down. Domain adapters do not rewrite accepted timestamps.

### Depositing the agreement

Approval may carry the agreement as an attachment, which the service checks against `deal` and keeps for disputes. If the seller's kit is set to deposit and the snapshot shows no agreement, it attaches it itself. The listing option declares the setting, so buyers can see it and filter on it: it gives the deal Arkhai's dispute fast path, which sellers without a reputation can advertise. Any party could deposit on its own, so a buyer's protection is this transparency, not a veto.

### Stateless kit

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

- No mechanism-neutral recipient field remains in `SettlementObligation`. The Agreement carries buyer and seller principals, and the Arkhai mandate's `to` comes from the payment option; Alkahest's claimant moves into its `params`. Core keeps only what at least two parties read.
- `kit/settlement-runtime` stays where it is for now: Alkahest, contact exchange, core and the domains all use it. Arkhai payments keeps no client-side servicing state and bypasses it, producing no settlement plan or obligation; moving escrow semantics out of core is a follow-up change.
- Both kits poll the payments service by transaction ID; the storefront relays nothing. A push hook from the payments service is tracked as an idea in arkhai-payments (`transaction-webhooks`) and is expected to replace polling.
- The SDK's default window is `P7D`. The payments service enforces no minimum; chargeback exposure is covered by its cash reserve.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Bare-metal stores the seller-derived mandate and matching signed receipt in a negotiation-scoped evidence record; the transaction ID is not an escrow obligation. | `openspec/specs/settlement-servicing/spec.md`, `openspec/specs/physical-provisioning/spec.md` |
| Bare-metal invokes selected-site fulfillment only after that receipt record is verified. | `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md#fulfillment` |
| VM payment evidence gates selected-site fulfillment and restart recovery; local provisioning progress has no escrow obligation. | Pending §4 promotion: `openspec/specs/settlement-servicing/spec.md`, `openspec/specs/physical-provisioning/spec.md` |
| VM payer account is separate from marketplace identity and trusted service policy. | Pending §4 promotion: `openspec/specs/settlement-configuration/spec.md` |
| Fractional Agreement timestamps round hold intervals up and approval expiry down without changing the deal hash. | Pending §4 promotion: `openspec/specs/settlement-servicing/spec.md` |
