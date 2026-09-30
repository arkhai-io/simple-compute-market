## Context

The payments service's cross-product decisions are recorded in `arkhai-io/arkhai-payments` (`docs/issues/scm-settlement-port.md`); its wire contract is JSON Schema in that repository (`schema/payments.schema.json`) with test vectors, so this repository generates pydantic models rather than importing TypeScript.

A mandate is `{from, to, parts, deal, fee, authorities, nonce, expires}`. Parties and authorities are Arkhai account UUIDs. Each part is `once` with an asset, an amount and a hold. The transaction id is `sha256(JCS(mandate))`, so a retried approval converges on one transaction and one receipt. The receipt is Ed25519-signed with `kit/identity` framing (`arkhai.payments.receipt.v1`).

## Decisions

### Pipeline, not a shared escrow interface

Each stage consumes its predecessor's output and owns the translation into its own form. The listing is opaque to core except for its slots and which kit fills each, so buyers and registries can filter by kit, and registries may restrict kits. Behavior is discriminated dispatch on the mechanism identifier, which the registration surface in `kit/settlement-runtime` already provides.

Rejected: a mechanism-neutral signal vocabulary (start/stop/reverse or collect/reclaim) in core. Nothing but the mechanism reads it, and each domain needs explicit compatibility with each mechanism anyway.

### The settle stage defines the deal hash

`arkhai.payments.v1` commits to `sha256(JCS(agreement))` (RFC 8785; the Python side uses `rfc8785`). `derive_settlement_option_id`'s `json.dumps(sort_keys=True)` is not JCS and is not reused for it.

### Mandate derivation for fixed-interval deals

Both sides derive the mandate from the agreement deterministically, so the seller's verification is a comparison:
- `from`: the buyer's Arkhai account; `to`: the payee account in the selected option's params.
- one `once` part: the agreed amount in the option's asset (payments notation, e.g. `USD/2`), held for the term plus the dispute window declared in the option params.
- `fee`: the service's published fee policy.
- `authorities`: `reverse` lists the seller and Arkhai's dispute authority, which the service requires; `start` and `stop` are empty.
- `nonce`: from the agreement, so one agreement cannot be approved twice by accident.

### Stateless kit

Every call goes to the payments service: approve (buyer), fetch or verify the receipt (seller), `reverse` (seller refund). Hold release and fee collection happen in the service. Provisioning is gated on a verified receipt.

## Superseded changes

Built on `fiat.stripe.v1` and `kit/hosted-settlement`: `consume-expanded-stripe-funding`, `add-api-credits-hosted-settlement`, `add-bare-metal-hosted-settlement`, `bind-one-hosted-release-coordinate`, `carry-the-payer-return-address`, `project-an-authoritative-funding-loss`, and the hosted sections of `disburse-a-settlement-disposition`. The old service never ran with production money, so nothing deployed needs migration. Archive or withdraw them when this change is accepted.

## Deferred

- **Identity slot.** `kit/identity` already dispatches by scheme, but the listing carries one `seller_principal`. Revisit when a listing needs to advertise several identity schemes.
- **Negotiation slot.** `kit/negotiation-runtime` builds in one protocol (counter/accept/exit, an amount, `AgreementTerms`). Revisit when a second negotiation protocol arrives, e.g. auctions.
- **Per-stage kit declarations** (which predecessor outputs a stage accepts, for filtering). Revisit with the negotiation slot.

## Open Questions

- The shape of the agreement object, and whether it includes the full transcript or only the accepted terms.
- Where the buyer presents the receipt to the storefront (the existing `mechanism_ref` path or a new route).
- How the dispute window is chosen: seller-declared in option params, or a registry policy.
