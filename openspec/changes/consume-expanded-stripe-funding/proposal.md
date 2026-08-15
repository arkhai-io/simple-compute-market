## Why

The marketplace currently publishes and services one card-only hosted option whose public shape carries `payment_method_types`. The hosted authority's expanded signed payer/funding contract must be consumed as exact versioned profiles, with persistent buyer ownership and off-session authorization, without importing Stripe models or weakening storefront mediation and fulfillment gates.

## Dependencies

- `add-persistent-buyer-profiles` supplies selected and historical marketplace signers plus authority/environment-scoped opaque payer-binding metadata.
- `hosted-settlement-service:expand-stripe-payer-funding` supplies the exact signed client wheel, manifest, image, schema, and payer/profile/authorization capabilities. Implementation starts only after that release contract is fixed.

## What Changes

- **BREAKING**: replace new-publication `payment_method_types` with one exact typed `funding_profile`: `card.v1`, `us_bank_transfer.v1`, or `us_ach_debit.v1`. Each profile is part of deterministic option identity, accepted plan, materialization fingerprint, provider request, operation journal, recovery, and reporting.
- Publish one separate option for each configured ready funding profile and rate. Seller preflight validates the authority, exact signed release, account, resolver/condition, profile/currency/country eligibility, and profile readiness independently; one unready profile does not suppress ready peers or Alkahest.
- Extend registration-owned `stripe` settlement-clause fields and buyer compatibility to exact profile, USD, interaction capability, and selected local payer-profile readiness.
- Add `market settlement stripe payer ...` profile/setup/instrument commands backed by the released direct payer client and the selected persistent marketplace signer. Store only the hosted authority/environment opaque binding and safe lifecycle state in the local buyer profile.
- Before storefront materialization, obtain one deterministic operation-scoped `funding_authorization_ref` for the exact accepted obligation. Only that safe reference crosses storefront mediation and marketplace recovery; stable payer/instrument refs and provider data remain direct buyer-to-authority inputs.
- Add buyer-owned opt-in off-session policy with explicit authority, funding profile, currency, per-purchase and aggregate amount bounds, and optional seller bounds. Policy may sign only the exact current authorization and cannot bypass hosted consent, mandate, readiness, or action requirements.
- Preserve storefront mediation for escrow create/status/reclaim. Direct authority calls are limited to payer-profile management and exact per-purchase authorization.
- Reuse `--action open|print|fail` for setup, interactive payment, off-session confirmation, and delayed bank states. Raw actions remain transient; resume retrieves current public state rather than reading a stored URL.
- Gate VM fulfillment and collection on the hosted authority's profile-specific authoritative `funded` state. Delayed transfer/debit, expiry, reclaim, restart, and exact retry use the existing mechanism-neutral settlement runtime and immutable operation identity.
- Update VM publication, buyer selection, settlement, servicing, configuration, Compose/Helm, release verification, and protected Stripe scenarios. Existing Alkahest behavior and already accepted legacy card obligations remain unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-configuration`: add exact funding-profile vocabulary, per-profile readiness, publication/compatibility projections, automation policy, and signed-release capability pins.
- `storefront-publication`: publish distinct ready funding-profile alternatives and safe independent blockers while preserving exact server-authoritative start.
- `buyer-orchestration`: add payer management, exact funding authorization, bounded opt-in automation, transient action fallback, delayed bank state, and recovery-safe references.
- `settlement-servicing`: pin profile/authorization in each hosted obligation and enforce profile-specific authoritative funding before fulfillment, collection, reclaim, and recovery.
- `market-composition`: preserve the thin released-client ownership boundary while composing payer/direct-authorization and storefront-mediated VM paths without provider leakage.
- `deployment-state`: pin the exact client/API/schema/capability release and update buyer/seller config, Secret references, Compose/Helm, and protected inputs without deploying provider state.
- `test-compatibility`: add credential-free adapter/runtime coverage and protected VM evidence for every exact profile and off-session action fallback.

## Impact

- Hosted adapter: `kit/hosted-settlement/src/market_hosted_settlement/{adapter.py,settlement_config.py}` and its exact released-client dependency/lock.
- Buyer core and VM plugin: payer command registration, persistent-profile binding, automation policy, action handling, selection, run-log, and resume paths.
- VM storefront: per-profile registration/preflight/publication, accepted plan and deterministic IDs, server-authoritative materialization, fulfillment gate, servicing, and legacy recovery decoder.
- Deployment/release: marketplace package pins, `.dist` acquisition/verification, Compose, Helm values/schema/templates/fixtures, config migration, and protected E2E driver/report schema.
- Permanent documentation: settlement configuration, storefront publication, buyer orchestration, settlement servicing, market composition, deployment, testing, VM buyer/seller quickstarts, and repository architecture.

## Non-Goals

- API-credit or bare-metal hosted composition; those are separate adopting changes.
- Stripe SDK, Customer, PaymentMethod, mandate, webhook, provider credential/ID, raw action persistence, hosted database/migration, or provider recovery code in this repository.
- Additional countries/currencies, SEPA, wallets, or unversioned/free-form funding methods.
- Silent fallback across instruments, profiles, amounts, destinations, mechanisms, or operation identities.

## Permanent documentation impact

- [x] `openspec/specs/{settlement-configuration,storefront-publication,buyer-orchestration,settlement-servicing,market-composition,deployment-state,test-compatibility}/spec.md`
- [x] Applicable subsystem architecture companions
- [x] `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING,ROADMAP}.md`
- [x] VM buyer/seller and hosted-settlement current-state documentation
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Promote exact profile option/readiness/selection and bounded automation contracts to settlement configuration and buyer orchestration.
- Promote distinct publication, exact start input, fulfillment gate, reclaim/recovery, and legacy-decoder boundaries to storefront publication and settlement servicing.
- Promote direct payer versus mediated escrow calls and released-client dependency ownership to market composition.
- Promote signed release/config/deployment and evidence boundaries to deployment state, test compatibility, and repository development docs.
