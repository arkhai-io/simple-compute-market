# Accepted-decision comparison

Compared `openspec/changes/settle-through-arkhai-payments/design.md` with the permanent promotion at `e97b4b7a`, retained on verification base `5cfa48f1`.

| Accepted decision | Observed permanent coverage |
|---|---|
| Negotiate → settle → provision; shared-reader carriers, no universal escrow adapter | ARCHITECTURE composition/servicing; market-composition spec and architecture |
| Exact Agreement bytes, explicit start, no universal deal hash | negotiation-protocol acceptance and deterministic-agreed-terms requirements; ARCHITECTURE discovery |
| Separate payer account, signer, service trust and owner credential | settlement-configuration and marketplace-identity specs; deployment guide |
| Shared opaque negotiation settlement_data for all mandates | negotiation-protocol, settlement-servicing and deployment-state specs |
| Agreement-only make_settle_hook dispatch | market-composition buyer-dispatch requirement |
| JCS deal/transaction hashes; one once part; hold/window/expiry rounding; fee/reverse/fixed nonce/deposit | settlement-servicing charge-first requirement and companion |
| Buyer approve/poll; negotiation-only seller settle; pending and stable retry | buyer-orchestration and settlement-servicing specs |
| Receipt-gated selected-site physical delivery and recovery; VM progress is not escrow | physical-provisioning spec/architecture; ARCHITECTURE fulfillment |
| Principal-bound exact-once grants, recoverable issuance and private credentials | api-credits spec/architecture |
| Shared kit registration/client provision; peer mechanism without wallet or obligation hooks | settlement-configuration spec/architecture; market-composition spec |
| External ledger/fees/holds/disputes/cash authority; generated wire models; WorkOS/Ed25519 | market-composition and deployment-state specs/architecture; ARCHITECTURE authority table |
| Stripe removed, legacy settings rejected rather than mapped | settlement-configuration and storefront-publication specs; deployment guide and CLI contract |
| Evidence belongs to each actual authority | test-compatibility spec/architecture; TESTING; capability index |
| Current roadmap and explicitly deferred escrow isolation, slots and push | ROADMAP Goal 6 and qualification boundaries; design's deferred disposition |

Small mismatches repaired: deterministic Agreement field enumeration now includes option asset/rates and opaque buyer settlement_params; API-credit grant idempotency names deterministic fulfillment identity instead of only escrow_uid; receipt gating distinguishes pending progress persistence from issuance authorization. These clarify existing accepted behavior, not a new lifecycle. Permanent normative behavior stays in spec.md; rationale stays in companion architecture or ARCHITECTURE. No production comment references an active change.

Larger implementation mismatch encountered while composing the credit diagnostic: API credits still owns `ApiCreditsArkhaiPaymentsConfig` and a local registration/client factory in `domains/apicredits/settlement/payments.py`, including inline api_key instead of the accepted shared api_key_env surface. This is not a missing promotion: the permanent shared-kit rule is explicit. Owner: [SCM #254](https://github.com/arkhai-io/simple-compute-market/issues/254). Development-auth ledger/issuance evidence does not prove that operator configuration boundary. No other larger documentation mismatch was found.

The prior local-import pass moved all 13 newly introduced candidates safely; this pass reran VM buyer/storefront and API-credit buyer/storefront suites. Diagnostic scripts are not permanent acceptance tests. Complete hardware access/revocation, production payment credentials/cash-provider behavior, and complete-deal publication/discovery/negotiation qualification remain outside these seeded local diagnostics, as the permanent evidence-ownership contracts already state.
