## Context

See `proposal.md` for motivation and the delta specs for normative behavior.

API credits already has most domain and authority boundaries required by this adoption:

- `domains/apicredits/schema.py` owns versioned listing, message, terms, materialization, receipt, and result codecs.
- The storefront composes shared market-domain settlement/fulfillment capabilities and already registers API-credit obligations in `market_settlement_runtime` while preserving the legacy `/api/v1/settle/{escrow_uid}` projection.
- The credits service is independently authoritative for quota, key hashes, canonical owner, grants, balances, credentials, and consumption.
- A grant is idempotent today by Alkahest `escrow_uid`; settlement fulfillment persists the buyer credential privately and exposes a secret-free public result.
- Publication and buyer selection are still `accepted_escrows`/chain/wallet shaped, and storefront preparation verifies Alkahest before registering the common plan.

`consume-expanded-stripe-funding` supplies the reusable hosted profile registration, persistent payer binding, exact purchase authorization, transient action policy, adapter, common runtime behavior, release pins, and protected evidence boundary. This change adopts those seams. It does not fork them or wait for unrelated bare-metal work.

The hosted authority's portable-remote condition can evaluate a configured, signed remote evidence source. The API-credit domain therefore needs a durable secret-free issuance statement and resolver, not an EAS transaction or a generic fulfillment blob.

## Goals / Non-Goals

**Goals:**

- Make settlement alternatives a first-class API-credit listing/terms field without changing domain pricing or quota authority.
- Add hosted settlement by composing the same registration/runtime/transport used by VM, with no VM dependency.
- Define one exact point at which financial funding authorizes API-credit issuance and one exact point at which issuance authorizes collection.
- Reuse credits-service grant idempotency for restart-safe new-key and top-up fulfillment under a mechanism-neutral identity.
- Keep API bearer secrets out of generic settlement, hosted authority, evidence, logs, and release artifacts.
- Support a truly wallet-free Ed25519 buyer/seller path while preserving Alkahest behavior.

**Non-Goals:**

- Generalizing API-credit metering, key possession challenges, or quota economics.
- A shared cross-domain fulfillment payload; API-credit evidence remains domain-owned.
- A distributed transaction across hosted, storefront, and credits databases.
- Retrofitting existing Alkahest grants with hosted authorization/profile semantics.
- Physical capacity, VM provisioning, site/executor scheduling, or bare-metal composition.

## Decisions

### 1. Extend `api_credits.v1` with peer settlement carriers

Add `settlement_options: list[SettlementOption]` to `ApiCreditsListing` while keeping `accepted_escrows` as the Alkahest carrier. Use the common strict `SettlementOption`, `SettlementSelection`, `SettlementPlan`, and obligation codecs; do not reproduce their dict shapes in API-credit models.

`ApiCreditsMessage`/`ApiCreditsTerms` carry one exact `SettlementSelection` after the buyer chooses an option. Existing Alkahest messages retain their accepted-escrow selection representation through an explicit domain decoder/migration. New hosted terms never include an `escrow_uid`, chain, wallet, payer profile, instrument, provider field, or funding authorization; authorization occurs after acceptance.

The domain pricing hook computes `quantity * selected per-credit rate` for either carrier with checked integer base-unit arithmetic. Seller policy compares the same scalar. Canonical accepted terms bind:

- trusted listing and service/quota resource;
- quantity and key mode/key ID;
- selected settlement option/escrow identity;
- exact rate/currency/profile/condition;
- complete canonical buyer and seller/claimant principals;
- accepted expiry policy.

**Alternative considered:** convert Alkahest `accepted_escrows` into hosted-style `settlement_options` as part of this change. Rejected because it creates unrelated wire migration and could change existing escrow selection/evidence semantics. They remain peer carriers selected through the common facade.

### 2. Compose registrations and common runtime at API-credit roots

Add API-credit buyer/storefront settlement-composition modules patterned on the shared contracts, not copied VM functions. Each root creates a `SettlementConfigurationRegistry` with `create_alkahest_registration()` and `create_stripe_registration()`, resolves only enabled role-applicable configuration, runs observational readiness, and constructs clients lazily for the selected mechanism.

Hosted-only composition never resolves `Wallet`, chain address configuration, RPC, or an Alkahest client. Alkahest-only composition does not construct a hosted client or payer service. Both-enabled composition retains explicit priority/preference but accepted selection pins one mechanism permanently.

The API-credit market-domain contract continues to inject domain plan and fulfillment hooks. Common code owns selection/registration/operation lifecycle; domain code owns service, quantity, key, pricing, issuance, evidence, and result meaning.

Add import-boundary tests proving:

```text
core -> mechanism/domain opaque
kits -> core contracts
api-credits composition -> core + api-credits concepts + selected kits
api-credits concepts/credits service -X-> hosted, Stripe, VM, bare metal
```

**Alternative considered:** import `domains.vms.*settlement*` because it already drives hosted settlement. Rejected because VM preparation and fulfillment bind provisioning, duration, site, and connection evidence and would invert domain ownership.

### 3. Extract schema-opaque hosted transport, not domain preparation

Move the buyer's signed `/api/v1/settlements` start/status/reclaim/poll/action transport from the VM domain into a shared core buyer module. It accepts seller URL, accepted IDs, safe funding-authorization reference, signer/principal/trust resolver, timeout/poll policy, and returns provider-neutral public projections. VM migrates to the shared call; API credits consumes it. Core does not import hosted client models because all direct hosted authorization remains in `kit/hosted-settlement`.

Extract the duplicated storefront route mechanics into a core route/controller factory or service protocol with injected callbacks for:

- reload/prepare accepted domain obligation;
- reserve/bind legacy domain projection;
- invoke domain fulfillment after common runtime readiness;
- project authenticated credential/private result;
- handle domain terminal cleanup.

VM and API-credit roots supply their own callbacks. The shared route accepts only negotiation ID, obligation ID, and `funding_authorization_ref`, authenticates with marketplace identity, and invokes the common runtime. API credits retains `/api/v1/settle/{escrow_uid}` for Alkahest. New hosted operations use `/api/v1/settlements`; no endpoint guesses mechanism from caller fields.

**Alternative considered:** duplicate the small VM buyer and route files in API credits. Rejected because signing, response verification, action redaction, status polling, and reclaim semantics are security-sensitive and would immediately create two conventions.

### 4. Derive one server-authoritative API-credit hosted obligation

Refactor `prepare_api_credit_settlement` into mechanism-neutral accepted-state loading followed by mechanism-specific verification. The common loader reads seller-owned negotiation thread, trusted listing, accepted domain terms, and configured local principal. It validates the exact selection and reconstructs the quantity-scaled plan.

For hosted selection it creates one obligation whose immutable params contain exact profile, account, condition, funding authorization, service, quantity, key mode/key ID, canonical buyer/claimant, amount/currency, expiry, and deterministic marketplace operation ID. Buyer start contributes only the operation-scoped authorization reference; all commercial and issuance fields come from seller state. The hosted adapter/authority verify that authorization against the financial subset.

For Alkahest selection the existing authoritative escrow verification returns the matched obligation and preserves `escrow_uid`/chain projection. Both branches produce the same `PreparedSettlement` with an `ApiCreditsFulfillmentInput`; only the mechanism receipt/projection differs.

The obligation ref becomes the domain's mechanism-neutral settlement grant namespace. A deterministic fulfillment ID derived from obligation ref plus domain/version is the exact credits-service issuance key.

**Alternative considered:** use hosted settlement ref as the grant key. Rejected because it couples domain idempotency to one mechanism and would not unify Alkahest recovery.

### 5. Upgrade credits-service grants to canonical fulfillment identity

Extend the credits client/service issuance request with:

- `fulfillment_id` (immutable grant key);
- settlement mechanism and obligation ref for safe attribution;
- service/quota resource;
- quantity and key mode/key ID;
- complete canonical buyer principal;
- immutable request digest.

The credits database makes `fulfillment_id` unique and stores the canonical request digest with the grant. Exact retry reads the existing result. Changed reuse conflicts before quota, key, or balance mutation. Historical rows backfill `fulfillment_id = escrow_uid` and retain their primary/reference fields; new code accepts those only as migrated Alkahest identity.

Canonical key ownership stores `{scheme, identifier}`, not a wallet string. Migrate unambiguous historical wallet owners to `eip191`; retain unowned keys. Any ambiguous owner blocks migration rather than becoming Ed25519-compatible by text. New and existing-key issuance repeat ownership/status/quota checks in the same credits-service transaction as the grant/balance update.

The storefront's shared fulfillment lease reserves before calling the credits service. Unknown acknowledgement retries the exact request. A committed grant is successful fulfillment even if storefront persistence or credential delivery fails.

**Alternative considered:** add a storefront-side issuance idempotency table while leaving credits keyed by `escrow_uid`. Rejected because the credits service is the mutation authority and is the only place that can atomically prevent duplicate quota/balance effects.

### 6. Make the issuance statement the only hosted fulfillment evidence

Add a strict `ApiCreditsIssuanceEvidenceV1` domain model with a canonical body and marketplace-identity signature. The body includes only:

- protocol/domain/schema/capability versions;
- hosted condition anchor and marketplace obligation/fulfillment/grant identities;
- service/quota resource and quantity;
- key mode and public key ID;
- full canonical buyer and claimant;
- committed issuance status/time;
- issuer principal and request/body digest.

It excludes the bearer secret, credentials ref, balances unrelated to the grant, provider/payer/instrument data, URLs, and raw service response. Sign with the configured API-credit storefront evidence signer after a committed grant. Derive `evidence_digest = sha256(canonical signed evidence)` and persist the immutable signed object keyed by that digest in the API-credit storefront database. Exact replay returns it; changed reuse conflicts.

Expose a bounded authenticated/signed evidence-resolution endpoint keyed by digest. The hosted authority's operator-configured remote resolver knows this endpoint and expected issuer/schema; the accepted condition carries only the resolver ID and exact demand. No listing/start caller supplies a URL or issuer.

Use the hosted conditional-escrow adapter's existing `publish_fulfillment(condition_anchor, evidence=canonical_signed_evidence)` path. It sends only the digest to the hosted authority and returns a portable remote attestation UID. Encode that UID/resolver as the runtime fulfillment ref. During condition evaluation, the configured resolver matches the attested digest, retrieves the signed API-credit evidence, validates exact accepted fields/issuer, and reports provider-neutral satisfied/pending/invalid.

```text
credits grant commit
  -> signed secret-free API-credit evidence + digest (storefront-owned)
  -> hosted digest publication under condition anchor
  -> portable remote attestation UID (runtime fulfillment_ref)
  -> hosted resolver retrieves/verifies evidence by digest
  -> satisfied -> collect
```

**Alternative considered:** put the API key or credential hash in evidence. Rejected because neither is needed to prove issuance/ownership and hashes of bearer material create correlation/offline-guessing risk.

**Alternative considered:** use EAS for API credits. Rejected because this path must be wallet-free and the hosted portable condition already provides signed remote resolution.

### 7. Use the common servicing lifecycle for issuance/collect/reclaim exclusion

Register hosted obligations before financial materialization. The common runtime continues to journal materialize/status/fulfill/check/collect/reclaim. API-credit storefront servicing adds its domain fulfillment hook at `ready` exactly as VM does, but fulfillment is the credits-service grant rather than provisioning.

Ordering invariants:

1. no fulfillment lease before authoritative hosted funded state;
2. no evidence publication before committed grant;
3. no condition success before exact signed evidence retrieval;
4. no collection before satisfied evidence reservation;
5. no reclaim after fulfillment lease/success, satisfied evaluation, or collection reservation;
6. no issuance after reclaim reservation;
7. post-collection loss never rewrites issuance or consumption.

A retryable credits-service failure calls runtime fulfillment retry under the same identity. Terminal domain failure records safe reason but remains non-fulfilled; after expiry, current hosted status plus compare-and-set can permit reclaim. A pre-collection return keeps the domain unfulfilled/uncollected. If grant commit wins the expiry race, reclaim loses and restart resumes evidence/collection.

Do not reuse current Alkahest compensation for hosted failure. That compensation exists for issuance followed by a later on-chain fulfillment failure. In hosted flow the grant is the domain fulfillment effect; once it commits, recovery rolls forward to evidence/collection.

**Alternative considered:** issue after collection to eliminate reclaim complexity. Rejected because the accepted condition is issuance itself; collecting first would remove the conditional guarantee.

### 8. Keep secret delivery orthogonal to settlement completion

`FulfillmentOutcome.private_result` carries new-key credentials only into the API-credit storefront's authenticated credential store/projection. Public runtime state, evidence, receipts, reports, and generic buyer run logs contain public key ID and opaque credentials reference at most.

New-key exact retry follows the current unused-key rule: the credits authority may rotate an unused secret and invalidate the earlier one, while grant/balance/fulfillment identity remains unchanged. Once the key is used, no retry reveals a secret. Existing-key top-up never returns a bearer secret.

Buyer orchestration writes any returned credential only to the existing owner-controlled API-credit credential destination and tests actual service admission separately from settlement state. Consumption to zero yields HTTP 402; a new accepted top-up under the same canonical owner increases balance exactly once and the same credential works again.

**Alternative considered:** store API key credentials in the persistent marketplace buyer profile alongside hosted payer binding. Rejected because payer identity and API bearer identity have different authorities, rotation, disclosure, and recovery rules.

### 9. Canonical marketplace identity replaces wallet-only ownership

Use `market_identity.Identity` end to end in API-credit negotiation terms, credits client/service issuance, key owner storage, evidence, and authorization. Comparisons use complete scheme plus normalized identifier. EIP-191 remains supported for Alkahest; Ed25519 becomes sufficient for hosted.

Role composition resolves a selected persistent buyer signer and a storefront signer from Secret-backed identity config. Wallet/chain config is conditional on Alkahest enablement only. Existing-key lookup returns safe canonical owner metadata so compatibility/policy can reject another owner before negotiation, but issuance repeats the authority check.

Bearer authentication remains `<key_id>.<secret>` and does not acquire marketplace signing. Hosted payer ownership remains an opaque authority binding associated with the local marketplace profile; it is not copied into credits storage.

**Alternative considered:** map Ed25519 identities to synthetic EVM addresses for existing owner columns. Rejected because it collapses schemes, permits equal-looking collisions, and falsely introduces chain semantics.

### 10. Deployment and evidence add one domain adopter, not a combined authority

Extend API-credit storefront/buyer config with the shared `[Settlement]` hierarchy, hosted exact release/profile/resolver inputs, persistent profile path, and signer Secret references. Credits service config gains only canonical owner/fulfillment contract version; it receives no hosted URL or Stripe inputs. The hosted deployment config gains an operator-selected API-credit evidence resolver/issuer allowlist, not API bearer credentials.

`compose.apicredits.yml` runs registry, credits service, API-credit storefront, buyer/E2E driver, and separately released hosted service with independent durable stores and identities. Hosted-only fixture omits wallet/RPC/chain entirely. Both-mechanism fixtures prove optional dependencies are lazy.

Protected evidence extends the existing signed report model with exact API-credit domain/credits service/evidence resolver identities and safe usage outcomes. It records the marketplace and hosted release sets separately. The bearer secret is used only by the test driver against the sample API and is protected by recursive canary checks.

**Alternative considered:** fold credits service or evidence resolver into the hosted service. Rejected because hosted is a domain-neutral financial authority and must not own API keys, quota, or issuance meaning.

## Risks / Trade-offs

- **[Adding a second listing carrier can create ambiguous selection]** → Require exact `SettlementSelection`, duplicate-free identities, explicit mechanism/profile constraints, and seller-side revalidation against trusted listing.
- **[Three authorities cannot commit atomically]** → Journal before each effect, make credits grant/evidence/hosted operations idempotent by immutable identity, and enforce monotonic roll-forward/reclaim exclusion.
- **[Evidence resolver compromise could authorize collection]** → Pin issuer/resolver/schema, sign canonical evidence, bind condition anchor and exact obligation fields, digest through hosted attestation, and fail closed on freshness/signature/digest mismatch.
- **[Credential loss after issuance can look like fulfillment failure]** → Keep grant/fulfillment success independent from delivery; use existing unused-key rotation rule and never reissue balance to recover a secret.
- **[Historical wallet ownership migration can be ambiguous]** → Backfill only structurally valid EIP-191 owners; fail the migration for ambiguous non-null values.
- **[Shared route extraction can regress VM]** → Migrate VM to the extracted transport/factory in the same implementation section and run VM hosted/Alkahest suites before API-credit adoption is considered complete.
- **[Hosted bank delay can outlive CLI execution]** → Persist safe refs/state and make ordinary resume authoritative; never require the initiating process to stay alive.
- **[Protected tests may leak the new API key]** → Keep it only in driver memory/owner credential fixture and apply deterministic canaries to reports, logs, service artifacts, and failure output.

## Migration Plan

1. Complete and verify `consume-expanded-stripe-funding`, including the exact producer release, persistent buyer profiles, shared hosted adapter/action/authorization contract, and legacy VM regression.
2. Implement shared transport/route extraction and migrate VM callers first; prove unchanged VM hosted and Alkahest behavior before API-credit callers depend on it.
3. Add API-credit schema/selection/composition and credits-service canonical owner/fulfillment-id migrations with exhaustive historical Alkahest fixtures; do not enable hosted publication.
4. Add domain fulfillment/evidence/resolver and common servicing integration. Run credential-free exact-retry, restart, expiry/reclaim, secret-redaction, package, typing, and evidence tests.
5. Build and pin matching API-credit, marketplace, credits-service, and hosted artifacts. Update config/Compose and verify hosted-only Ed25519 startup with no wallet/chain construction.
6. Stop new API-credit negotiation admission, checkpoint active settlement workers, back up storefront/credits databases and buyer profile stores, apply migrations, install matching artifacts/config, verify releases/readiness/evidence resolver, then resume existing Alkahest processing.
7. Publish hosted API-credit options only after quota, exact profile, seller account, condition resolver/issuer, and persistent buyer readiness pass. Existing accepted Alkahest obligations keep their identities/routes.
8. Run new-key, exhaustion/402, same-owner top-up, other-owner rejection, delayed funding, restart, collect/reclaim, and supported protected profile scenarios through ordinary artifacts.
9. Before any hosted option/authorization is accepted, rollback restores prior storefront/credits databases, config, wheels/images, and Compose coordinates together. After a hosted accepted effect, roll forward; old code must not interpret new settlement/grant/evidence records.

## Design promotion plan

| Accepted decision | Permanent destination |
|---|---|
| Peer listing carriers, canonical principals, exact pricing/issuance identity, secret boundary | `openspec/specs/api-credits/{spec,architecture}.md` |
| API-credit composition and shared transport ownership | `openspec/specs/market-composition/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md` |
| Exact quota/profile publication and server-authoritative start | `openspec/specs/storefront-publication/{spec,architecture}.md` |
| Exact selection, actions/resume, credential delivery/usage checks | `openspec/specs/buyer-orchestration/{spec,architecture}.md` and API-credit quickstarts |
| Funding → issuance → evidence → collection ordering and reclaim/recovery | `openspec/specs/settlement-servicing/{spec,architecture}.md` |
| Wallet-free topology, artifacts, config, Secrets, migration/rollback | `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Focused/full evidence ownership and redaction | `openspec/specs/test-compatibility/{spec,architecture}.md` and `docs/development/TESTING.md` |
| Seller/current deployment workflow | `docs/cookbooks/vllm-apicredits-seller.md` and applicable API-credit buyer/seller docs |
| Completion state and remaining bare-metal adopter | `docs/development/ROADMAP.md` |

Implementation closeout records the exact promoted headings, runs comment hygiene, removes temporary change/migration commentary from production code, verifies touched import placement, and compresses completed tasks only after all owned validation and documentation destinations are complete.
