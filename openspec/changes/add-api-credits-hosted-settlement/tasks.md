## 1. Shared hosted transport extraction

- [ ] 1.1 Verify `consume-expanded-stripe-funding` and its exact signed producer release are complete, then inventory VM buyer/storefront hosted start/status/reclaim/action callsites and freeze the provider-neutral request/response/callback contract API credits will consume.
- [ ] 1.2 Extract signed hosted start/status/reclaim/poll/resume transport from `domains/vms/buyer/hosted_settlement.py` into a schema-opaque core buyer module accepting only accepted IDs, safe authorization reference, marketplace signer/trust, and timeout/action policy; migrate every VM caller and remove the domain copy.
- [ ] 1.3 Extract common `/api/v1/settlements` route/service mechanics from the VM storefront behind injected prepare/reserve/fulfill/project/cleanup callbacks; migrate VM routes to it while leaving `/api/v1/settle/{escrow_uid}` Alkahest behavior unchanged.
- [ ] 1.4 Add core contract/signature/redaction/retry tests and rerun focused VM hosted/Alkahest buyer, route, runtime, action, restart, and import-boundary suites before adding API-credit callers.

## 2. API-credit settlement vocabulary and selection

- [ ] 2.1 Extend `domains/apicredits/schema.py` and domain codecs with strict common `settlement_options`, exact `SettlementSelection`, canonical buyer/seller principals, and mechanism-neutral materialization/receipt references while preserving accepted-escrow decoding for historical Alkahest terms.
- [ ] 2.2 Update API-credit pricing, negotiation buyer/seller policies, round-zero construction, accepted-term persistence, and quantity multiplication to validate the exact selected carrier/rate/currency/profile/condition/parties with checked integer arithmetic.
- [ ] 2.3 Replace the chain-only buyer selection path in `domains/apicredits/buyer/` with the shared settlement registry/policy/compatibility facade across hosted options and accepted Alkahest escrows; remove local imports and flags that bypass exact hosted selection.
- [ ] 2.4 Add domain/negotiation/buyer tests for independent carriers, deterministic identities, duplicate/mismatched choices, quantity pricing, overflow/fraction rejection, condition/party mismatch, incompatible local profile, no fallback, and unchanged Alkahest selection.

## 3. Buyer and storefront composition

- [ ] 3.1 Add API-credit buyer/storefront settlement-composition modules registering Alkahest and hosted through `SettlementConfigurationRegistry`, with lazy role-applicable client/readiness construction and no wallet/chain resolution for hosted-only Ed25519 config.
- [ ] 3.2 Wire shared hosted payer commands, persistent profile selection, exact purchase authorization, bounded off-session policy, and common transient action handling into the API-credit CLI without copying hosted client/wire models.
- [ ] 3.3 Extend API-credit storefront startup/container/lifespan with the shared settlement repository/runtime/worker, exact hosted client/evidence publisher, mechanism preflight, and injected domain callbacks while retaining credits-service and Alkahest composition.
- [ ] 3.4 Add composition/config/import tests proving hosted-only startup creates no wallet, RPC, chain, Alkahest, VM, bare-metal, physical-capacity, or provider object; both-enabled dispatch remains exact and API-credit concept/authority packages stay independent.

## 4. Publication and server-authoritative preparation

- [ ] 4.1 Update `ApiCreditsListing`, `ListingService.publish_from_quota`, publication/reconciliation, config and controllers to compile independently ready shared mechanism clauses into ordered hosted options plus accepted Alkahest escrows without accepting account/condition/provider overrides.
- [ ] 4.2 Reconcile quota and settlement readiness independently: zero authoritative quota closes, quota unavailability preserves the last complete listing, and one hosted profile blocker removes only its affected option while valid peers remain.
- [ ] 4.3 Refactor API-credit settlement preparation into common accepted-state loading plus exact hosted or Alkahest verification; derive service, quantity, key target, canonical parties, amount/currency/profile, account, expiry, condition, obligation, and deterministic operation IDs only from trusted listing/accepted terms.
- [ ] 4.4 Register API-credit hosted start/status/reclaim on the shared `/api/v1/settlements` route with negotiation ID, obligation ID, and safe authorization reference only; keep the legacy Alkahest route/projection and reject mechanism/commercial/provider overrides.
- [ ] 4.5 Add storefront tests for multi-profile publication, per-profile blockers, quota/reconciliation interactions, signed route auth, exact authorization retry/conflict, option/condition/party/quantity/key mismatch, hosted-only readiness, and Alkahest non-regression.

## 5. Credits authority identity and exact-once grant

- [ ] 5.1 Extend API-credit settlement client request/result models with immutable `fulfillment_id`, obligation/mechanism attribution, canonical `{scheme,identifier}` owner, service/resource, quantity, key target, and request digest; version and rebuild its wheel without repository-relative editable imports.
- [ ] 5.2 Add credits-service migrations for unique fulfillment/grant identity, canonical owner fields, and immutable request digest; backfill valid historical Alkahest grants with `fulfillment_id=escrow_uid`, map unambiguous wallet owners to EIP-191, preserve unowned keys, and fail ambiguous migration atomically.
- [ ] 5.3 Update credits issuance transaction to reserve/check quota and key ownership, create or top up, and commit one grant under `fulfillment_id`; exact replay returns the existing result, changed service/quantity/key/owner/request conflicts before mutation.
- [ ] 5.4 Preserve new-key unused-secret rotation and used-key non-disclosure on credential retry; existing-key top-up never returns a secret and compares the complete canonical principal.
- [ ] 5.5 Add client/service/database migration and concurrency tests for Ed25519/EIP-191 ownership separation, exact retry, changed reuse, acknowledgement loss, new key, same-owner top-up, other-owner rejection, quota exhaustion, key state changes, credential retry, and historical Alkahest grants.

## 6. Issuance fulfillment and portable evidence

- [ ] 6.1 Derive a deterministic API-credit fulfillment/grant identity from the common obligation ref and update domain fulfillment to call the credits authority only after a shared fulfillment lease and authoritative hosted funded state or the existing Alkahest verification boundary.
- [ ] 6.2 Add strict canonical signed `api-credits` issuance evidence models/codecs containing condition anchor, obligation/fulfillment/grant, service/resource, quantity, key mode/public ID, canonical parties, issuer/time/version/digest and categorically no bearer/hosted/provider/private authority fields.
- [ ] 6.3 Add storefront migrations/repository/service and bounded authenticated signed resolution route for immutable evidence keyed by digest; exact publication/retrieval is idempotent, changed replay conflicts, and issuer/schema/freshness/signature/digest/anchor checks fail closed.
- [ ] 6.4 Publish canonical signed evidence through the hosted adapter's digest-only fulfillment operation, encode the returned portable-remote attestation UID/resolver as the common fulfillment ref, and configure condition demand/resolver to verify exact accepted API-credit fields.
- [ ] 6.5 Persist private new-key credentials only in the authenticated API-credit result store, public key ID/opaque reference in safe projections, and no secret in common runtime, hosted requests, evidence, logs, errors, reports, or persistent buyer profile.
- [ ] 6.6 Add domain/storefront/evidence tests for committed grant, unknown acknowledgement, signature/digest/anchor/issuer/party/service/quantity/key mismatch, changed replay, resolver unavailable, secret canaries, existing-key output, and exact credential retrieval.

## 7. Servicing, failure, and recovery

- [ ] 7.1 Wire API-credit hosted obligations through the common materialize/status/fulfill/check/collect/reclaim worker so only authoritative profile-funded state reserves issuance, committed evidence enables condition satisfaction, and satisfied evaluation enables collection.
- [ ] 7.2 Enforce compare-and-set exclusion among issuance lease/success, evidence, collection, and reclaim; retry credits/evidence under identical identities, permit reclaim after terminal no-grant failure/expiry, and reject reclaim when issuance wins the boundary.
- [ ] 7.3 Map delayed card/bank/ACH, transient action, unfunded expiry, pre-collection return, post-collection loss, and operator review through shared safe states without issuing early, choosing financial reversal operations, revoking consumed credits, or changing completed history.
- [ ] 7.4 Project hosted public status/result and authenticated credentials through API-credit serializers while preserving existing Alkahest settlement, compensation, credential, and status response behavior.
- [ ] 7.5 Add deterministic runtime/restart/race tests for no issuance before funded, exact-once grant after delayed funding, restart at every stage, failed issuance then reclaim, funding/expiry race, return/loss, evidence pending/invalid, collect acknowledgement loss, and no cross-mechanism/profile fallback.

## 8. Deployment, packages, and E2E

- [ ] 8.1 Update API-credit buyer/storefront/credits config defaults, templates, generation/migration, examples, role Secrets, and package locks for the shared `[Settlement]` hierarchy, exact hosted release/profiles/resolver, persistent profile, canonical owner/grant contract, and wallet-optional startup.
- [ ] 8.2 Update `compose.apicredits.yml`, component Compose inputs, images, volumes, health/readiness, and release verification to run independent registry, credits authority, API-credit storefront, buyer/driver, and exact hosted artifacts with no source sharing or provider credentials outside hosted execution.
- [ ] 8.3 Add wallet-free Ed25519 hosted-only fixtures and both-mechanism fixtures; reject Stripe/provider/payer/instrument/action/bearer data, wallet/chain requirements for hosted-only roles, stale wheels/images/schemas, and mismatched evidence issuer/resolver capabilities.
- [ ] 8.4 Extend API-credit E2E drivers/scenarios and signed report schema for exact profile selection, new-key purchase, API consumption through HTTP 402, same-profile same-owner top-up, other-owner rejection, delayed funding/action, restart, evidence, collection/reclaim, and independent artifact attribution.
- [ ] 8.5 Add recursive credential/provider/API-key canaries and explicit unavailable-external-prerequisite reporting; retain the API bearer credential only in owner/test-driver memory required to exercise the sample service.

## 9. Permanent documentation and promotion

- [ ] 9.1 Promote peer settlement carriers, canonical ownership, exact grant identity, hosted issuance/evidence/reclaim, and secret handling to `openspec/specs/api-credits/{spec,architecture}.md` and update the capability index description if needed.
- [ ] 9.2 Promote API-credit registry/runtime composition, shared hosted transport ownership, publication/readiness, buyer selection/actions/credentials, and server-authoritative start to `openspec/specs/{market-composition,storefront-publication,buyer-orchestration}/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md`.
- [ ] 9.3 Promote funding-to-issuance-to-evidence-to-collection ordering, exact retry/reclaim/return/loss/recovery, and focused/full evidence ownership to `openspec/specs/{settlement-servicing,test-compatibility}/{spec,architecture}.md` and `docs/development/TESTING.md`.
- [ ] 9.4 Promote wallet-free topology, artifacts/config/Secrets, authority separation, migration/activation/rollback to `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`; update `docs/cookbooks/vllm-apicredits-seller.md` and buyer/seller quickstarts as current-state instructions.
- [ ] 9.5 Update `docs/development/ROADMAP.md` with completed API-credit hosted adoption and the remaining bare-metal adopter/blockers, or record an explicit no-impact disposition if roadmap structure no longer requires an edit.

## 10. Validation and closeout

- [ ] 10.1 Run focused core transport, VM regression, API-credit domain/buyer/storefront, credits client/service/database, settlement runtime, evidence, migration, package, typing, config, Compose, redaction, and report-schema suites plus relevant integration/aggregate targets; disclose every external check not run.
- [ ] 10.2 Run the wallet-free API-credit hosted E2E through exact signed production artifacts for available card/bank/ACH and off-session boundaries, prove new-key use/exhaustion/402/top-up/other-owner behavior, preserve a signed sanitized report, and mark unavailable provider assertions explicitly.
- [ ] 10.3 Run strict OpenSpec validation, documentation/index/link checks, generated-artifact drift, comment/package/import boundaries, and applicable repository checks; confirm no VM copy, provider field, API bearer secret, wallet requirement in hosted-only config, stale legacy shortcut, or mismatched artifact pin remains.
- [ ] 10.4 Close out the change: run `make check-comment-hygiene` and directly review changed Python comments/docstrings for current-state wording; move every newly touched local import to module scope unless a reproduced circular import or documented deliberate lazy-load reason requires it and verify the real suite; re-check every accepted decision against OpenSpec documentation placement; compress completed tasks to final behavior/evidence/deferred work/permanent destinations after moving durable rationale to `design.md`; ensure roadmap currency is updated or explicitly recorded as no-impact; and complete a `## Design promotion record` in this change with exact permanent headings for every material decision.
