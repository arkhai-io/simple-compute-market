## Context

All local prerequisites are accepted in this checkout. The runnable `arkhai-bare-metal-buyer` contribution uses the core plugin and persistent-identity boundary; the dedicated storefront uses `MarketDomainContract`, `SettlementConfigurationRegistry`, `SettlementRuntime`, trusted selected-site capacity/fulfillment clients, and the shared hosted transport/route service. The POOLS-7 cutover owns Capacity Reservation, fulfillment result/recovery, access teardown, and capacity release. Permanent capability specs now state the one-domain composition, selected-site, hosted servicing, and physical-result contracts.

Accepted inventory: `domains/bare_metal/{src/arkhai_bare_metal, buyer/src/arkhai_bare_metal_buyer, storefront/src/arkhai_bare_metal_storefront}` own codecs, buyer commands, accepted binding, publication, callbacks, persistence, and HTTP composition; `core/buyer/core_buyer/hosted_settlement.py` owns the schema-opaque buyer transport and hosted settle hook; `kit/settlement-runtime/market_settlement_runtime`, `kit/hosted-settlement/market_hosted_settlement`, `kit/site-client`, and `provisioning/compute-provisioning` own the canonical shared route service/runtime, hosted adapter facade, site, and fulfillment mechanisms; `compose.bare-metal.yml`, the bare-metal Helm chart, domain/root Makefiles, and role pyprojects own packaging and deployment. Focused domain/buyer/storefront/shared-runtime/site/provisioning suites own deterministic local evidence. Signed hosted producer artifacts, protected Stripe rails, and real disposable-host access/revocation/teardown remain external qualification evidence rather than local prerequisites.

The durable architectural boundaries are already clear:

- shared marketplace settlement runtime owns mechanism-neutral plan/obligation servicing and opaque domain fulfillment references;
- the hosted repository is the only Stripe/provider and hosted financial authority;
- the storefront owns accepted commercial terms, the billable negotiation hold, selected-site orchestration, and the decision to begin physical work;
- the site authority owns Physical Resources, Capacity Reservations, committed allocations, and cross-mode exclusion;
- compute provisioning owns resource scheduling, provider dispatch, result convergence, and teardown, without commercial identities or Stripe state;
- the bare-metal domain owns its listing/demand/terms/materialization/result/access interpretation;
- secrets and raw provider/executor results never become settlement evidence.

A billable negotiation-time hold and a committed physical allocation are different lifecycle facts. This design permits an already accepted, paid-for hold to remain while funding is pending, bounded by its original deadline. It never renews or replaces that hold because payment is slow, and it does not commit, schedule, allocate, provision, or grant access until hosted funding is authoritative.

## Goals / Non-Goals

**Goals:**

- Make the prerequisite gate mechanically reviewable so implementation cannot hide a missing buyer, incomplete composition, or fake fulfillment behind task status.
- Reuse the shared hosted consumer and physical fulfillment contracts once their accepted APIs are present; keep one implementation of signatures, transient actions, servicing, and recovery.
- Preserve every authority boundary while correlating one commercial obligation with one accepted site/resource hold, one physical fulfillment, one public evidence record, and one teardown lifecycle.
- Define exact deadline, failure, reclaim, restart, and post-collection teardown decisions before code is touched.
- Make release qualification prove usable whole-host access and later revocation, not only payment or provisioning API responses.

**Non-Goals:**

- Designing missing prerequisite APIs inside this change. If the completed prerequisite differs from the contracts assumed here, update this change before implementation rather than building an adapter to an obsolete draft.
- Moving hosted financial authorization into the site/provisioning service or making that service validate marketplace agreement identities.
- Adding a second capacity hold for hosted funding, renewing an accepted hold, or turning provider latency into new inventory rights.
- Combining financial reclaim with physical teardown.
- Returning SSH private keys, bearer credentials, raw connection details, or provider metadata through hosted fulfillment evidence.

## Decisions

### 1. Use an evidence-backed prerequisite gate, not change/task status

The first implementation section produces a prerequisite matrix with one row per gate and four independently checked columns:

1. accepted permanent requirement/architecture heading;
2. exact shipped package/API/config surface;
3. focused/integration evidence proving the surface;
4. migration/deployment readiness where persistent or runnable behavior is involved.

A checked active-change task is provenance, not acceptance. An absent package/change, unresolved design question that changes the caller contract, permanent statement that contradicts completion, or test built around an injected fake leaves the row failed. Every later task depends on all rows passing.

For missing `bare-metal-buyer-domain`, `storefront-domain-parameterization`, and `multi-domain-storefront-composition`, the row may name an explicitly accepted superseding change only when that replacement supplies the same observable contract. It may not waive the capability. `kit-storefront-composition-seam`, the bare-metal seller change, POOLS-7, and `consume-expanded-stripe-funding` must be implemented, promoted, and supported by the evidence each owns.

Alternative considered: begin domain schema work while prerequisites land. Rejected because the schema and route contracts are owned by the shared composition cutover; guessing them would create exactly the bare-metal-local parallel path the program is intended to remove.

### 2. Keep one domain per role process and register mechanisms through shared composition

The completed bare-metal buyer and storefront remain independent runnable role packages. Each installs one `MarketDomainContract` and registers Alkahest and `fiat.stripe.v1` through the shared settlement configuration/registry. The hosted integration is the manifest-pinned released `arkhai-hosted-settlement-client` behind `market_hosted_settlement`; bare-metal packages see only mechanism-neutral ports and public models.

Buyer composition injects its selected persistent buyer identity/signer, payer-profile resolver, safe transient-action presenter, and domain adapter. Storefront composition injects its seller identity/signer, seller account binding, shared settlement runtime, selected-site capacity/fulfillment clients, and bare-metal fulfillment/evidence adapter. Hosted-only composition does not initialize wallet, RPC, chain, EVM address projection, or Alkahest clients.

Alternative considered: add hosted calls directly to `arkhai_bare_metal_storefront` and later extract them. Rejected because signature verification, payer state, authorization, status, recovery, and safe action semantics already have one shared owner and direct integration would violate the clean dependency cutover.

### 3. Extend shared publication carriers; keep physical vocabulary in the domain payload

`BareMetalListing` continues to describe the trusted physical offer: domain kind, machine/executor-local identifier, Physical Resource and physical-host identity where operator policy intentionally publishes a specific resource, access methods, duration, site labels, and allowlisted capabilities. Mechanism alternatives remain in the shared listing carrier as `settlement_options`; they are not added to `BareMetalListing` and are not mirrored into `accepted_escrows`.

The publication adapter constructs one hosted option per exact ready profile. Its deterministic identity is derived from the canonical mechanism/profile, currency/rate, seller/claimant, condition/evidence mode, accepted offer/funding deadline, and the signed listing generation/derivation key. Card, US bank transfer, and US ACH are separate options. Omission is per profile: a card-ready listing is not suppressed because ACH is unavailable.

Readiness is an intersection, never a union:

- trusted complete resource/site generation and authoritative availability;
- configured site binding and the listing's exact derivation key;
- advertised access method supported by the bare-metal adapter;
- hosted release/authority and seller connected-account readiness;
- selected condition resolver/evidence mode;
- supported USD profile and canonical quote/rate;
- offer, hold, funding, and fulfillment windows that can coexist.

Publication reads these facts through their owners. It does not copy provider IDs, credentials, URLs, or live hosted payer state into the listing.

Alternative considered: one generic `fiat.stripe.v1` option whose profile is selected after negotiation. Rejected because readiness, deadlines, transient actions, and authorization differ by profile; late selection would allow the buyer to request an unadvertised rail.

### 4. Persist one server-authoritative accepted binding

At accepted terms, the storefront derives and stores one immutable binding containing:

- agreement/listing/negotiation and settlement obligation references;
- canonical buyer/payer and seller/claimant principals;
- selected mechanism/profile, amount/rate/currency, condition/evidence mode, and canonical accepted-plan digest;
- signed demand, listing generation/derivation, and seller-term digests;
- trusted selected `site_id`, resource/pool constraint, Physical Resource and physical-host identity when intentionally selected, access method/policy, and accepted domain materialization digest;
- offer expiry, original billable-hold identity/expiry if one exists, funding deadline, and fulfillment deadline;
- nullable authority-owned references populated monotonically after their effects: hosted operation, Capacity Reservation/allocation, fulfillment/provider operation, public physical result/evidence, collection/reclaim, lease/access, and teardown.

Buyer fields are inputs only where the buyer is authoritative: persistent public principal, selected advertised profile, signed hosted authorization, bounded off-session permission, and public SSH key or opaque access-delivery reference accepted by the domain. The server reconstructs every seller, resource, price, condition, and deadline field from signed/trusted artifacts and rejects conflicts before mutation.

Use the shared settlement obligation/journal and domain envelope columns supplied by prerequisites. Add a bare-metal table only if the accepted shared model cannot preserve a required immutable domain binding; such a finding requires a design update and explicit migration rather than an unversioned JSON sidecar.

Alternative considered: recover site/resource and access policy from the current listing. Rejected because listings, pool membership, and availability evolve; recovery must preserve accepted facts rather than reinterpret them.

### 5. Treat the billable hold as a bounded pre-funding exclusion, not fulfillment

The funding deadline is:

`min(offer_expiry, billable_hold_expiry, hosted_profile_authorization_expiry, fulfillment_feasibility_deadline)`

where absent bounds are omitted, never synthesized. An existing accepted billable negotiation-time Capacity Reservation may remain held while card interaction, bank push, or ACH is pending. The hosted path does not create a replacement hold, extend it, rebind it to a newly published resource, commit it, or schedule against it before authoritative funding.

On authoritative funding, the storefront either commits that exact still-valid hold or creates/commits the ordinary accepted-site reservation if no hold exists and current admission succeeds. It then calls the shared selected-resource scheduler and fulfillment API. A pinned site/resource refusal is terminal for this commercial attempt; no placement fallback changes the purchased object.

On deadline, the worker first retrieves the authoritative hosted operation. A funded result recorded within the accepted boundary wins over delayed local/webhook observation. Otherwise it expires the obligation, releases the existing hold through the site authority, and enters hosted reclaim only after the shared financial exclusion check. Later resource republication creates a new offer and cannot rescue this obligation.

Alternative considered: reserve after Checkout creation to reduce post-funding stock loss. Rejected for this adoption because pending bank/ACH time can be long and the accepted design allows only the separately billable, deadline-bounded negotiation hold to exclude inventory before payment.

### 6. Use the shared durable physical lifecycle after funding

The storefront call sequence is:

```text
accepted binding
  -> immutable hosted plan/authorization
  -> authoritative funded status
  -> commit existing hold OR reserve+commit at accepted site
  -> schedule exact resource constraint
  -> begin fulfillment once
  -> pull authoritative status/result
  -> domain validates access-ready physical result
  -> storefront publishes portable signed evidence
  -> shared condition evaluation
  -> hosted collect
  -> lease remains active
  -> expiry/termination -> revoke access -> teardown -> release allocation
```

The site/provisioning service does not receive Stripe status, payer profile, price, marketplace buyer/seller principal, or agreement body. It receives its ordinary authenticated reservation, scheduling, fulfillment, and teardown calls. The storefront sequencing is the pre-funding safety boundary.

Idempotency is a chain of stable identities, not one overloaded identifier:

- accepted plan/obligation and hosted operation at the financial boundary;
- hold/Capacity Reservation and committed allocation at the site boundary;
- `fulfillment_id`, selected `SettlementResource`, provider operation, and provisioned-resource/lease identifiers at provisioning;
- condition anchor, fulfillment UID, and evidence digest at hosted evidence publication;
- access grant/revocation and teardown operation at the bare-metal adapter.

Equivalent retries return or converge the existing object. Conflicting reuse fails before a second effect. No process reconstructs another authority's missing row.

Alternative considered: have the physical service validate a signed `funded` assertion. Rejected because commercial/funding identity is not part of the provisioning contract and would make a lower authority depend on hosted settlement.

### 7. Compose portable evidence from an authoritative credential-free physical result

Compute provisioning returns a provider-neutral active result proving the selected Physical Resource, Capacity Reservation/allocation, fulfillment/lease references, access method, readiness timestamp, and expiry. For bare metal, the live access-grant result also carries the resolved buyer-reachable host, port, and public tenant user. The storefront validates the concrete result, persists a copy with host, port, and raw provider details removed, and uses only that credential-free copy for receipts, public results, and evidence.

The storefront/domain binds the credential-free physical result digest to the accepted agreement/obligation, canonical buyer and claimant, condition anchor, and fresh fulfillment UID in the shared `FulfillmentPublicationRequest`. Hosted publication signs/verifies through the released client and accepted portable condition resolver. `collect` is eligible only after authoritative hosted evaluation accepts this evidence.

Buyer access coordinates remain behind a domain-owned authenticated delivery route. The route re-fetches the active fulfillment result through the recorded selected-site binding, authorizes the exact accepted buyer, returns only SSH host, port, public tenant user, and lease expiry, and becomes unavailable when teardown starts. The run log, storefront database, portable evidence, and public result never retain those coordinates, private keys, passwords, bearer tokens, provider identifiers, authority URLs, inventory data, or raw job output.

Alternative considered: publish `connection_details` directly as evidence. Rejected because portable evidence outlives the request and is shared across authorities; capability-bearing access data would become a credential leak and an unsafe recovery dependency.

### 8. Reclaim and teardown are independent state machines

Before valid fulfillment/collection, terminal selected-site refusal, capacity loss, executor failure, access-grant failure, invalid evidence, or fulfillment expiry prevents collection. Reclaim is allowed only after authoritative hosted retrieval proves no collection effect/reservation and the physical side proves no successful lease/access evidence that would make the outcome ambiguous. An unknown collection acknowledgement freezes release/reclaim and reconciles the same financial operation.

An authoritative funding return before physical work blocks allocation and follows hosted recovery. If funding returns after allocation, provisioning, or access begins but before collection, servicing stops new physical effects, preserves all committed physical/evidence identities, blocks collection, and drives access revocation, teardown or quarantine, allocation release, and hosted financial reclaim/recovery as independent convergent operations. Once collection has committed, a later funding loss is an incident only and never authorizes financial reclaim or rewriting the delivered lease.

After collection/transfer, financial state is complete. Lease expiry or explicit authorized termination separately drives access revocation, provider teardown, allocation release, and capacity republication. Unknown/retryable teardown is retried by the provisioning-owned convergence worker. Terminal or ambiguous teardown keeps the resource quarantined/unavailable and exposes bounded operator recovery; it never triggers financial reclaim or marks capacity free.

Alternative considered: reclaim on lease termination. Rejected because reclaim reverses an uncompleted financial obligation, while lease teardown ends already delivered physical service.

### 9. Reuse shared transient action, restart, and recovery semantics

Card off-session attempts are allowed only by the selected persistent buyer profile's bounded opt-in policy. Any authentication/confirmation response becomes the shared safe interactive action. Bank transfer instructions and ACH pending/mandate/action states use the same transient-action carrier. Public state, run logs, process arguments, reports, and diagnostics contain only normalized safe action data and opaque references.

Buyer resume restores the accepted option/profile and same hosted operation from the run log. Storefront resume restores the shared obligation/journal and the exact site/physical references. Provisioning recovery owns provider command claims and status convergence. Each component queries its authority; none fabricates success from another component's cached state.

### 10. Deploy separate authorities with exact artifacts and secrets

The final bare-metal hosted stack adds only configuration supported by completed prerequisites:

- exact signed hosted release manifest/client wheel/service image and authority identity;
- bare-metal buyer/storefront distributions/images and one-domain role entry points;
- distinct buyer/storefront Ed25519 identities and trust registries;
- owner-restricted buyer profile-store path plus hosted authority/environment scope, from which the buyer resolves its opaque payer binding at runtime; storefront configuration retains only the seller's public connected-account binding;
- exact settlement option/profile policy, USD quote/rate, condition/evidence resolver, offer/hold/funding/fulfillment windows;
- trusted site authority and compute provisioner bindings, bare-metal adapter/executor configuration, and authenticated access-delivery trust;
- shared runtime, domain, storefront, site, and provisioning migrations.

Role preflight proves exact public identities/capabilities and private secret placement before startup. Hosted-only roots receive no wallet/RPC secrets. Hosted service provider credentials do not enter marketplace pods; site/provisioner/access secrets do not enter hosted service or public evidence.

Migration first installs schema/package changes with hosted disabled, migrates configuration deterministically, deploys and qualifies producer/identity/shared composition/site/provisioning dependencies, then enables hosted publication and finally buyer selection. Rollback before any mutation disables the option and restores matching artifacts/config. After financial or physical mutation, rollback pins the compatible release set and resumes immutable operations; it never downgrades away the only code able to reclaim, collect, revoke, or tear down.

### 11. Qualify the observable whole-host contract at the lowest owning levels

Focused tests use injected hosted provider outcomes only at the shared provider port, real SQLite/runtime/site/provisioning services at integration boundaries, and real public role APIs for E2E. They prove each decision independently, especially:

- profile-specific publication and omission;
- server-authoritative accepted binding and deadline minimum;
- existing hold preservation without renewal/commit before funding;
- exact selected-site/resource routing and cross-mode refusal;
- retry/restart after each financial and physical mutation;
- access-ready evidence privacy and invalid/no-op rejection;
- reclaim exclusion versus collection ambiguity;
- revocation, teardown, quarantine, and only-then capacity restoration.

Protected release qualification uses real Stripe test mode and a disposable or explicitly isolated real bare-metal resource. It performs an authenticated action before lease expiry, proves access fails after revocation, and proves capacity is republished only after teardown/release. Credential-free tests do not claim Stripe or real-host behavior. Alkahest remains a separate lane.

## Risks / Trade-offs

- **[Prerequisite planning artifacts overstate current readiness]** → Require permanent headings, shipped surfaces, and owned evidence in the gate; stop and update this change when a prerequisite contract changes.
- **[Slow ACH/bank funding outlives inventory validity]** → Use the strict deadline minimum, never renew the hold, re-retrieve hosted status at expiry, and fail/reclaim rather than switching resources.
- **[Funding succeeds but selected capacity is lost]** → Treat site refusal as terminal for this deal, collect nothing, and reclaim only after financial/physical exclusion checks.
- **[A billable hold is mistaken for allocation]** → Persist hold, commit, allocation, fulfillment, and lease as distinct states/identities and assert zero commit/schedule/provider calls while nonfunded.
- **[Commercial identity leaks into provisioning]** → Keep funding gating in storefront servicing; send only ordinary reservation/fulfillment contracts below.
- **[Physical result leaks credentials or topology]** → Validate an allowlisted public result, bind its digest into evidence, and keep access material behind authenticated domain delivery.
- **[Unknown collection or teardown acknowledgement causes contradictory cleanup]** → Preserve the same operation identities, reconcile through owning authorities, and quarantine capacity until certainty.
- **[Specific-resource publication exposes inventory]** → Retain prerequisite opt-in/allowlist and publish only accepted public identity/capability fields.
- **[Real whole-host qualification is operationally expensive]** → Use a disposable/isolated target and one exact protected lane; never replace it with a fake because real access and revocation are the acceptance boundary.

## Migration Plan

1. Run the prerequisite gate. If any row fails, leave all implementation tasks blocked, record the exact prerequisite destination, and make no production/schema/deployment edits in this change.
2. After every gate passes, pin the accepted producer/client and shared composition contracts; update this design/spec/tasks first if their interfaces differ.
3. Add or migrate shared/domain accepted-binding state and configuration while hosted remains disabled. Verify deterministic reruns and legacy Alkahest/no-hosted behavior.
4. Wire profile-aware publication and buyer exact selection without enabling production publication.
5. Wire hosted plan/authorization/status/recovery, then the post-funding selected-site fulfillment and portable evidence path.
6. Wire reclaim exclusion and independent lease revocation/teardown/quarantine recovery.
7. Build exact role artifacts, render role-scoped secrets/config, and run focused/integration/package/type checks.
8. Qualify one protected whole-host deal through real access and teardown, then enable hosted options.

Rollback before mutation disables `fiat.stripe.v1` and restores the matching artifact/config set. Rollback after mutation preserves the current compatible hosted, marketplace, site, and provisioner releases until every accepted financial and physical operation reaches a safe terminal state. Existing Alkahest behavior remains independently deployable.

## Design promotion record

| Accepted decision | Exact permanent destination |
|---|---|
| Evidence-backed prerequisite gate and one-domain shared composition | `openspec/specs/market-composition/spec.md` — “Bare-metal hosted settlement composes through shared role seams”; `docs/development/ARCHITECTURE.md` — “Bare-metal hosted adoption” |
| Profile/resource/site/deadline readiness intersection and immutable accepted binding | `openspec/specs/storefront-publication/spec.md` — “Bare-metal hosted alternatives intersect financial and physical readiness”; `docs/bare-metal-seller-quickstart.md` — “Configure public bindings” |
| Exact buyer selection, signed accepted-state recovery, funding/start/resume, safe actions, physical result/access/teardown, real-access success, and reclaim/teardown distinction | `openspec/specs/buyer-orchestration/spec.md` — “Bare-metal buyers preserve accepted hosted authority”; installed `market bare-metal` command group |
| Hold/funding deadline distinction and ordered funding-to-fulfillment-to-collection lifecycle | `openspec/specs/settlement-servicing/spec.md` — “Bare-metal hosted servicing preserves financial and physical ordering” |
| Selected-resource physical result, transient buyer-authorized SSH delivery, credential-free durable result/evidence, teardown/quarantine/release | `openspec/specs/physical-provisioning/spec.md` — “Bare-metal hosted fulfillment consumes authoritative funding”; `openspec/specs/fulfillment/spec.md` — “Fulfillment status and result queries”; `openspec/specs/storefront-publication/architecture.md` — “Trusted site routing” |
| Artifact topology, identities/secrets, migrations, cutover, and rollback | `openspec/specs/deployment-state/spec.md` — “Bare-metal hosted roles preserve authority and secret boundaries”; `docs/development/DEPLOYMENT_AND_CONFIG.md` — “Bare-metal hosted role configuration” |
| Focused ownership and real whole-host release evidence | `openspec/specs/test-compatibility/spec.md` — “Bare-metal hosted evidence is attributed by layer”; `docs/development/TESTING.md` — “Bare-metal hosted lanes” |
| Current delivery/goal state after acceptance | `docs/development/ROADMAP.md` — “Hosted settlement release status” |
