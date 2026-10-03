## Why

The settlement slot is shaped like the first mechanism that filled it. Alkahest is escrow: money stays the payer's until a condition is proven, and the payer reclaims after expiry. `SettlementObligation` carries that model as typed "lifecycle universals" (`claimant`, `expiration_unix` as the collect-vs-reclaim boundary, `conditions`), and `ConditionalEscrowClient` gives every mechanism escrow verbs (`materialize`, `check`, `collect`, `reclaim_expired`).

Fiat is charge-first: money moves at payment and is undone by refund or dispute. Fitting the hosted Stripe mechanism to the escrow shape produced most of its friction, for example escrowing a maximum amount up front and refunding the unused rest instead of charging the actual amount once it is known. The hosted Stripe service (`arkhai-io/stripe-settlement-service`, consumed through `kit/hosted-settlement` as `fiat.stripe.v1`) is being replaced by the Arkhai payments service (`arkhai-io/arkhai-payments`): a balance ledger on Formance where a buyer approves a mandate from their Arkhai account and receives a service-signed receipt. Its v1 serves fixed-interval deals.

## What Changes

- **The deal is a pipeline, negotiate → settle → provision.** Each stage understands the output of the stage before it and nothing else. A stage may discriminate on its input internally: one provisioning stage can accept both Alkahest and Arkhai payment evidence and translate each into its own internal form. Stages may fuse, as `contact-exchange.v1` fuses settle and provision. There is no shared adapter API; each mechanism defines its own API towards the domains that support it.
- **Core defines only what at least two of buyer, seller and registry read.** For settlement that is the listing's `settlement_options` (`{option_id, mechanism, asset, rates, params}`) and the selected option in the accepted deal. Mechanism status, servicing and refunds are the mechanism's and the domain's business.
- **Escrow semantics move into `alkahest.v1`.** `claimant`, `claimant_principal`, `expiration_unix` and `conditions` leave `SettlementObligation` for Alkahest params, the listing's `accepted_escrows`, `demands` and `oracle_address` fold into Alkahest's option params, and `ConditionalEscrowClient` becomes Alkahest's internal detail.
- **Negotiation emits one explicit agreement object on acceptance**, the output a settle stage consumes. Core does not define its hash; a settle stage that needs one defines it.
- **Add `arkhai.payments.v1`**, a stateless kit over the Arkhai payments HTTP API. The seller's kit derives the mandate from the agreement, with `deal = sha256(JCS(agreement))`, and hands both to the buyer, so both know the transaction id before approval. The buyer approves it with its owner's credentials, optionally depositing the agreement for disputes; both poll the id, and the seller provisions once the receipt matches. A refund is a `reverse`. Holds release without SCM calls, so the kit keeps no servicing state and runs no daemon.
- **Delete `fiat.stripe.v1` and `kit/hosted-settlement`.** The hosted-fiat changes built on them are superseded (see design).

## Capabilities

### Modified Capabilities

- `settlement-configuration`: hosted funding profiles, release pins and Stripe registration are removed; `arkhai.payments.v1` registers as a peer mechanism.
- `settlement-servicing`: the obligation servicing lifecycle becomes Alkahest-owned; core keeps the neutral obligation fields.
- `negotiation-protocol`: acceptance produces an explicit agreement object.
- `market-composition`: domains compose settle and provision stages rather than an escrow client.

## Non-Goals

- Identity and negotiation as advertised listing slots, and per-stage kit declarations (deferred; see design).
- Rates, spot and on-demand deals through `arkhai.payments.v1`. That is the payments service's next release.
- Cash movement. Stripe top-ups and payouts are internal to the payments service; SCM trusts the ledger.

## Impact

- Affected code: `core/src/market_core/schemas.py`, `kit/settlement-runtime`, `kit/alkahest`, `kit/negotiation-runtime`, a new `kit/arkhai-payments`, the removed `kit/hosted-settlement`, and every domain's settlement composition, hosted routes and buyer funding commands (vms, bare_metal, apicredits).
- Affected wire: registry listing columns, the accepted-deal carrier, and the negotiation acceptance response.
- External dependency: headless callers authenticate to the payments service with WorkOS user-scoped API keys, owned by `arkhai-payments` (`agent-credentials`).

## Permanent documentation impact

### Knowledge to promote

- The negotiate → settle → provision pipeline and "core defines only what two parties read" go to `docs/development/ARCHITECTURE.md`.
- The neutral obligation and agreement shapes go to `openspec/specs/settlement-servicing/spec.md` and `openspec/specs/negotiation-protocol/spec.md`.
- ROADMAP Goal 6's current state drops `fiat.stripe.v1` and names `arkhai.payments.v1`.
