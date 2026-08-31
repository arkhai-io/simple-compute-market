## Why

Bare metal now has a runnable buyer, a dedicated storefront composition, trusted selected-site capacity and provisioning clients, durable fulfillment/recovery/teardown, and the shared expanded hosted settlement seams. This change adopts hosted funding without treating verification or a fake fulfillment flag as delivery: authoritative funding gates physical effects, portable lease-ready evidence gates collection, and physical teardown remains independent from financial reclaim.

## Prerequisite resolution and external qualification blockers

The runnable `arkhai-bare-metal-buyer`, dedicated seller composition, POOLS-7 selected-site fulfillment cutover, shared one-domain storefront seams, persistent buyer profiles, and expanded hosted consumer are present and promoted in this checkout. Bare metal consumes their APIs directly; it introduces no VM import, hosted transport copy, local route implementation, direct executor bypass, fake provisioner, or hard-coded resource.

Production qualification remains externally blocked until operators supply and verify the exact signed hosted manifest/client/service image/provenance and all protected Stripe test-mode account/rail/instrument/mandate/browser inputs. Release-qualified whole-host evidence additionally requires a disposable real target on which authenticated access and later revocation, executor teardown, Capacity Reservation release, and capacity republication are observed. Local deterministic tests and generated configuration do not substitute for either external lane.

## What Changes

- Register Alkahest and `fiat.stripe.v1` through the completed shared registry/runtime in runnable bare-metal buyer and storefront roots. Hosted-only Ed25519 roles require no wallet or chain.
- Add mechanism-neutral settlement alternatives to trusted bare-metal publication. Publish one exact hosted option per ready profile only when hosted authority/release, seller account, condition resolver, currency/rate, Physical Resource/site mapping, access capability, capacity/offer window, and funding deadline are coherent.
- Add exact buyer selection and server-authoritative obligation derivation from the versioned bare-metal demand, trusted listing, accepted seller terms, and selected site. Buyer input cannot invent or override Physical Resource, physical host, site, pool, executor machine/provider, seller/claimant, price, access policy, condition, or expiry.
- Do not commit, allocate, schedule, or provision a physical host before authoritative hosted funding. A pre-existing billable negotiation-time hold may remain only until its accepted deadline; on funded state, use that exact hold/selected trusted site and ordinary Capacity Reservation, shared fulfillment, and bare-metal executor contracts exactly once.
- Bound hosted funding expiry by the accepted offer and billable negotiation hold. Pending card/bank/ACH funding never extends or replaces capacity/offer validity; expiry re-retrieves current hosted state before releasing the hold or reclaiming.
- Publish signed portable lease-ready evidence binding agreement/obligation, Physical Resource, committed allocation and lease/fulfillment references, canonical buyer/claimant, access method, access readiness, and expiry without private SSH material, credentials, topology secrets, or provider data.
- Collect only after real whole-host access is ready and exact evidence is authoritative. Capacity loss or terminal provisioning/evidence failure before fulfillment remains eligible for reclaim under the shared exclusion rules; no fake/no-op result can satisfy the condition.
- Preserve lease teardown/revocation after collection as an independent physical lifecycle. Financial reclaim after collection/transfer remains forbidden, and teardown failure keeps capacity unavailable/operator-repairable.
- Support `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1`, bounded buyer-local off-session policy, transient action fallback, slow funding, restart, and exact recovery through shared hosted seams.
- Add release-qualified whole-host evidence for real access and revocation/teardown plus existing Alkahest and verified-only compatibility lanes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: compose hosted settlement only through completed runnable bare-metal buyer/storefront and shared roots, with explicit prerequisite enforcement and no VM/provider copies.
- `storefront-publication`: publish exact hosted profiles only when trusted resource/site/capacity, condition, account, rate, and funding-window readiness agree.
- `buyer-orchestration`: add exact bare-metal hosted selection, authorization, transient action, resume, reclaim, and real-access result behavior.
- `settlement-servicing`: order authoritative funding, selected-site reservation, physical fulfillment, lease evidence, collection/reclaim, restart, and teardown without cross-authority fallback.
- `physical-provisioning`: preserve selected-resource authority, expose immutable credential-free real whole-host lease/access results for portable evidence, and preserve teardown/release authority.
- `deployment-state`: add gated bare-metal buyer/storefront hosted config, packages/images/stack, role identity/payer bindings, site/provisioner/evidence trust, migration, and rollback.
- `test-compatibility`: require prerequisite contract checks and focused/release-qualified whole-host hosted deal, access, recovery, and teardown evidence.

## Impact

- Prerequisite artifacts/current-state specs: missing/restored buyer and shared composition changes, `market-platform-bare-metal-10-storefront-composition`, `pools-7-storefront-fulfillment-cutover`, and `consume-expanded-stripe-funding`.
- Domain/buyer: `domains/bare_metal/src/arkhai_bare_metal/` listing/demand/terms/materialization/receipt/evidence codecs and the future/restored runnable buyer package.
- Storefront: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{runtime.py,settlement.py,settlement_service.py,publication.py,domain_runtime.py,server.py}` plus completed shared composition/route/runtime seams.
- Physical path: site Capacity Reservation, selected Settlement Resource, provisioning compute client/service, bare-metal adapter/executor, durable fulfillment/result, lease release/watchdog, and access revocation.
- Deployment/evidence: bare-metal stack/config/role generation, exact wheels/images/releases, trusted site/provisioner/evidence bindings, E2E driver, and signed report schema.
- Permanent documentation: composition, publication, buyer, settlement, physical provisioning, deployment, testing, bare-metal buyer/seller/deployment docs, architecture, and roadmap.

## Non-Goals

- Implementing or simulating any missing prerequisite inside this change.
- Negotiating directly over provider/executor internals or exposing Physical Resource in the ordinary fungible case; exact resource binding applies only where the trusted listing/accepted terms intentionally select it.
- Committing/scheduling capacity, allocating/provisioning a host, renewing/replacing the original billable hold, extending offer/hold expiry for payment, or treating Checkout/action/webhook/provider state as funded.
- Stripe/provider credentials, IDs, webhooks, payer/instrument state, or recovery in bare-metal packages.
- SSH private keys, bearer credentials, provider topology, or raw access details in hosted evidence, generic settlement state, logs, or reports.
- Financial reclaim as lease teardown or lease teardown as financial reversal.

## Permanent documentation impact

- [x] `openspec/specs/{market-composition,storefront-publication,buyer-orchestration,settlement-servicing,physical-provisioning,deployment-state,test-compatibility}/spec.md`
- [x] Applicable subsystem architecture companions
- [x] `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING,ROADMAP}.md`
- [x] `docs/bare-metal-seller-quickstart.md` and the accepted buyer/deployment/operator docs supplied by prerequisites
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Promote prerequisite gates and shared buyer/storefront composition ownership to market composition and repository architecture.
- Promote resource/site/profile/funding-window publication and exact accepted binding to storefront publication and buyer orchestration.
- Promote funding-to-reservation-to-lease-evidence-to-collection ordering, reclaim/teardown independence, and recovery to settlement servicing and physical provisioning.
- Promote wallet-free topology, exact artifacts/config/Secrets/trust, migrations, and real whole-host evidence attribution to deployment state, test compatibility, quickstarts, and development docs.
