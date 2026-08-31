## Why

API credits currently negotiates and fulfills only Alkahest-shaped `accepted_escrows`, so a non-EVM buyer cannot purchase or top up credits through the shared hosted financial authority. The expanded hosted consumer now provides the mechanism-neutral selection, authorization, servicing, and identity seams this domain must compose instead of copying VM lifecycle code.

## Dependencies

- `consume-expanded-stripe-funding` supplies exact profile publication/selection, persistent payer integration, direct authorization, shared hosted transport/adapter, runtime semantics, deployment pins, and evidence contracts.
- Completed API-credit composition/runtime/publication seams from `bare-metal-and-credits-domain-stacks` and the kit-extraction changes remain authoritative. Unrelated unfinished bare-metal work is not a reason to create API-credit-local copies.

## What Changes

- Add mechanism-neutral `settlement_options` to the versioned API-credit listing while preserving `accepted_escrows` as independent Alkahest alternatives.
- Register Alkahest and `fiat.stripe.v1` through the shared settlement configuration registry in API-credit buyer and storefront composition roots. Hosted-only Ed25519 roles start without wallet, chain, or EVM construction.
- Replace Alkahest-only buyer selection with exact shared `SettlementSelection`. Validate option identity, profile, condition, parties, service, quantity, key mode/key ID, amount, and expiry against trusted listing and seller-accepted terms.
- Derive one canonical hosted obligation from the accepted API-credit purchase; buyer input cannot invent seller account, claimant, condition, price, service, key ownership, or issuance target.
- Reuse the shared hosted buyer start/status/reclaim/resume transport and common conditional-settlement runtime. API-credit packages do not import VM packages or duplicate hosted signing/wire/action logic.
- Gate issuance/top-up on authoritative hosted funded state. Use the immutable settlement obligation/fulfillment identity as the credits-service grant key so restart or retry cannot reserve quota, issue a new key, top up, or collect twice.
- Publish signed portable issuance evidence binding service, quantity, key mode/key ID, canonical buyer/claimant, settlement/fulfillment identity, key ownership, and issuance success without exposing the bearer secret. The configured hosted condition resolver retrieves this evidence.
- Collect only after authoritative issuance evidence satisfies the accepted condition. Funding whose issuance fails remains non-collected and eligible for reclaim after the accepted deadline; pre-collection hosted return blocks issuance/collection, while post-collection loss remains authority incident state.
- Support `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1`, buyer-local bounded off-session policy, transient setup/payment/confirmation/bank action fallback, delayed funding, and recovery through the shared hosted consumer.
- Add wallet-free Ed25519 configuration and E2E coverage for new-key purchase, consumption through exhaustion/HTTP 402, and existing-key top-up by the same persistent profile; reject top-up by another canonical principal.
- Preserve existing Alkahest API-credit negotiation, issuance, compensation, credential retrieval, and consumption behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `api-credits`: add mechanism-neutral listing/terms settlement choices, hosted funding-to-issuance/evidence semantics, canonical principal ownership, exact-once top-up, reclaim, and secret-free results.
- `market-composition`: compose shared settlement registrations, hosted adapter/transport, identity, and runtime in API-credit buyer/storefront roots without VM or provider dependencies.
- `storefront-publication`: publish independently ready API-credit hosted profiles alongside accepted Alkahest escrows and reject incomplete or mismatched clauses.
- `buyer-orchestration`: add exact API-credit hosted selection, authorization, transient action, credential retrieval, and restart/reclaim behavior.
- `settlement-servicing`: order hosted funding, domain issuance fulfillment, portable evidence, condition evaluation, collection/reclaim, return/loss, and recovery under one immutable obligation.
- `deployment-state`: add API-credit hosted-only identity/config/profile/release/Compose wiring while keeping wallet, provider, payer detail, and bearer secret boundaries explicit.
- `test-compatibility`: add focused and full wallet-free hosted API-credit deal evidence with exact producer/consumer attribution and secret/provider redaction.

## Impact

- Domain contract and negotiation: `domains/apicredits/{schema.py,domain_runtime.py,listings,negotiation}`.
- Buyer: `domains/apicredits/buyer/` composition, selection, buy/negotiate/settle, action/resume, persistent profile, and credential retrieval paths; shared hosted transport below domains where the existing VM transport is generalized.
- Storefront: `domains/apicredits/storefront/src/apicredits_storefront/` startup/config, publication, accepted-term derivation, routes, shared runtime/repository, issuance, portable evidence, and recovery.
- Credits authority: domain client/service grant identity and ownership verification only; it remains authoritative for quota, key hashes, balances, grants, and consumption.
- Deployment/evidence: API-credit config/examples, `compose.apicredits.yml`, wheel/image pins, role identities/Secrets, E2E scenarios, report schema, and release verification.
- Permanent documentation: API credits, composition, publication, buyer, servicing, deployment, testing, cookbook/quickstarts, architecture, and roadmap.

## Non-Goals

- Provider/Stripe models, credentials, webhooks, IDs, actions, reconciliation, or recovery in API-credit code.
- VM, bare-metal, physical-resource, site-capacity, lease-executor, or provisioning dependencies.
- Treating API key bearer identity as marketplace or hosted payer identity, or exposing bearer secrets in settlement evidence/logs/public results.
- A distributed transaction across hosted funding and credits issuance; exact identities, ordering, idempotency, and reclaim/incident semantics provide recovery.
- New metering, route pricing, refund, credit clawback, or key possession-challenge semantics beyond current API-credit behavior.

## Permanent documentation impact

- [x] `openspec/specs/{api-credits,market-composition,storefront-publication,buyer-orchestration,settlement-servicing,deployment-state,test-compatibility}/spec.md`
- [x] Applicable subsystem architecture companions
- [x] `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING,ROADMAP}.md`
- [x] `docs/cookbooks/vllm-apicredits-seller.md` and API-credit buyer/seller quickstarts
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Promote hosted funding-to-issuance-to-evidence-to-collection ordering, exact-once grant identity, failure/reclaim, and identity/secret boundaries to API credits and settlement servicing.
- Promote mechanism-neutral API-credit listing/selection/publication and shared hosted transport composition to storefront publication, buyer orchestration, and market composition.
- Promote wallet-free Ed25519 role/config/release/Secret wiring and evidence attribution to deployment state, test compatibility, and repository development docs.
