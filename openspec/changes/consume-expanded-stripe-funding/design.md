## Context

See `proposal.md` for motivation and the delta specs for normative behavior.

The marketplace already has the correct high-level split:

- `kit/settlement-runtime` owns typed mechanism registration, deterministic option publication, mechanism-neutral obligation journals, leases, and collect/reclaim exclusion.
- `kit/hosted-settlement` is a thin adapter over the exact released `hosted_settlement_client`; it verifies signed health/account state, maps one hosted obligation into the common runtime, and carries no Stripe credentials or provider behavior.
- VM storefront composition reloads accepted terms, materializes through the runtime, waits for authoritative funding, provisions once, binds fulfillment evidence, and services condition/collect/reclaim.
- VM buyer composition selects an advertised option, signs storefront requests, applies one transient browser-action policy, and resumes from an append-only run log.
- `add-persistent-buyer-profiles` plans an XDG-owned selected buyer profile with current/historical signers and authority/environment-scoped opaque hosted binding metadata.

The current hosted consumer is card-only in several coupled places: `StripePublicationInput.method`, option `payment_method_types`, one mechanism-wide readiness result, `HostedObligationParams`, buyer selection projections, start payload, and protected Stripe evidence. It also has no direct payer-control composition and assumes that storefront materialization can create the interactive financial operation without a prior payer-signed purchase authorization.

The producer change `hosted-settlement-service:expand-stripe-payer-funding` is authoritative for payer profiles, instruments, funding authorization, exact profile behavior, financial state, Stripe credentials and identifiers, webhooks, reconciliation, migration, and operator recovery. Its immutable release is a prerequisite, not code to reproduce here.

## Goals / Non-Goals

**Goals:**

- Extend existing settlement registration/runtime seams rather than creating rail-specific marketplace engines.
- Make profile, authorization, obligation, and operation identities immutable and visible at the minimum safe layer.
- Add direct buyer payer-control calls without making core orchestration or VM semantics depend on hosted wire/provider models.
- Preserve server-authoritative storefront materialization and authoritative-funding-before-fulfillment.
- Keep all URLs/details transient and make every delayed state resumable from safe identifiers.
- Provide an atomic public-config/package cutover while preserving exact historical card recovery.

**Non-Goals:**

- A generic marketplace payment-instrument database or provider abstraction.
- Seller/storefront proxying of payer setup, instruments, mandates, or purchase consent.
- Rail-specific workers, provider status enums, or provider operation selection in marketplace code.
- API-credit and bare-metal domain adoption; those changes consume the common result after this one.
- Backward-compatible public aliases for `payment_method_types` or `card`.

## Decisions

### 1. Extend the existing mechanism registration with a closed profile contract

`kit/hosted-settlement/src/market_hosted_settlement/settlement_config.py` remains the single marketplace owner of hosted configuration, preflight, clause fields, option construction, buyer compatibility, and released-client construction.

Replace `StripePublicationInput.method` with `funding_profile: Literal["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"]`. Add an interaction capability projection rather than a provider-method list. The registration exposes `stripe.funding_profile`, `stripe.currency`, and `stripe.interaction` clause fields; `stripe.funds_flow` remains fixed to `separate_charges_transfers`. Remove `stripe.method` from new config/query schemas and all generated examples.

Seller configuration represents ordered clauses, not one mechanism-global method. Each clause binds:

- exact profile;
- lowercase currency and positive minor-unit rate;
- account and fixed funds flow;
- one condition profile;
- interaction capability required by that profile;
- optional profile-specific public eligibility policy admitted by the producer contract.

The shared `SettlementPublicationClause` remains the rate container. Its mechanism input carries only profile and fixed funds flow; account, resolver and exact release pins remain role config. The option builder includes profile in `params` before deriving `option_id`, so equal economics under different rails never collide.

**Alternative considered:** register `fiat.stripe.card.v1`, `fiat.stripe.bank-transfer.v1`, and `fiat.stripe.ach.v1` as separate settlement mechanisms. Rejected because the hosted authority, conditional-escrow lifecycle, funds flow, adapter, and recovery contract are one mechanism; only funding behavior/profile differs. Separate mechanism IDs would duplicate configuration and servicing while obscuring shared financial authority.

### 2. Make readiness a profile-indexed result inside one mechanism

The common runtime currently returns one `MechanismReadiness`. Preserve that public registration contract and place a sorted safe per-profile map in declared public details, with one readiness/blocker set per configured profile. Mechanism-level `ready` means at least one configured profile is publishable for the current role. Release/authority failures that invalidate every profile remain mechanism-wide; account, resolver, currency/country, capability, mandate-mode, and rail availability blockers attach to the affected profile.

The hosted registration performs observational calls only:

1. verify exact health manifest/API/schema/capabilities;
2. verify seller account and transfer readiness for seller role;
3. ask the released client for safe profile readiness supported by the signed contract;
4. combine marketplace-owned clause completeness and resolver checks;
5. expose only stable blocker codes and safe messages.

Publication iterates ordered clauses and consumes the corresponding ready entry. It does not abort on the first blocked clause. The common readiness logger remains allowlist-driven; add only declared keys.

Buyer readiness combines verified release capability with the selected persistent local profile's authority/environment binding and safe interaction/instrument readiness. Explicit interactive ACH requires the active binding and an interaction-capable action policy, not a pre-existing saved mandate; only saved/off-session ACH requires the exact ready bank instrument and mandate. Discovery does no network mutation. Revalidation immediately before negotiation and purchase authorization prevents stale local metadata from authorizing a purchase.

**Alternative considered:** create one `MechanismReadiness` registration per profile. Rejected because it would give one configured mechanism multiple priorities/clients and would make accepted `mechanism` unstable.

### 3. Keep payer control in the hosted kit, compose it at the buyer root

Add provider-neutral façade functions/classes in `kit/hosted-settlement`; they accept the released client, selected `market_identity.Signer`, authority trust/config, and typed public inputs. They return strict released-client models or smaller safe projections. They do not redefine request signing, canonical encoding, payer/instrument models, or action formats.

VM buyer composition registers a Typer subtree:

```text
market settlement stripe payer
  create | show | delete
  owner rotate | retire
  setup start | status
  instrument list | default | revoke | delete
```

The command implementation obtains the selected profile and signer through the `add-persistent-buyer-profiles` service. Ownership operations can resolve a historical/overlapping signer exactly as profile rotation requires. Successful create/import/rotation/readiness updates are written atomically to the owner-only profile store as authority/environment plus opaque binding and safe lifecycle metadata. Instrument references are used only during the direct command/authorization call and are not copied into storefront state or generic buyer config.

Core `market` CLI knows only how a settlement registration contributes a namespaced command group. It does not import the hosted client or payer models. VM-specific purchase flow calls the hosted kit façade after option acceptance because VM owns the accepted terms projection.

**Alternative considered:** implement payer commands in `core/buyer`. Rejected because core must remain mechanism-opaque and cannot acquire a hosted client dependency.

**Alternative considered:** put payer commands in the VM buyer package directly. Rejected because API credits and bare metal need the same provider-neutral payer lifecycle; the hosted kit owns the reusable integration, while domain packages only register and supply accepted obligation inputs.

### 4. Split direct authorization from storefront-mediated escrow

The purchase flow has two authenticated paths:

```text
selected local buyer profile
        |
        | direct: payer/setup/instruments + exact authorization
        v
hosted authority

accepted VM terms + funding_authorization_ref
        |
        | signed marketplace request
        v
seller storefront -- released client --> hosted escrow authority
```

After seller-accepted terms are durably appended to the run log, VM orchestration derives one deterministic `marketplace_operation_id` from the accepted agreement/obligation identity. It builds the producer's strict funding-authorization model from accepted state plus the selected local payer binding and user-selected instrument/interactive mode. The released client canonicalizes and signs it. The run log receives only profile, marketplace operation ID, and returned operation-scoped `funding_authorization_ref`.

`domains/vms/buyer/hosted_settlement.py:start_hosted_settlement` adds only that safe reference to negotiation and obligation IDs. It removes redundant payer/claimant parameters from the request because the storefront reloads parties from accepted state. VM storefront routes and `load_hosted_agreement` reject all other caller-supplied money, account, profile, payer, claimant, condition, or provider fields.

`HostedObligationParams` adds exact `funding_profile` and `funding_authorization_ref`. The adapter passes them to the released client's materialize request. The authority resolves and verifies the authorization; marketplace does not decode its hidden payer/instrument fingerprint.

**Alternative considered:** send the signed authorization envelope through the storefront. Rejected because it exposes stable payer/instrument references to the seller and creates a second persistence/redaction burden.

**Alternative considered:** let the storefront request authorization. Rejected because the seller is not the payer and cannot exercise current purchase consent.

### 5. Off-session policy decides whether to sign; it never changes the authorization

Add a strict buyer-owned policy under the hosted buyer section/profile metadata with:

- enabled flag;
- exact authority/environment;
- exact funding profile and currency;
- positive per-purchase maximum;
- positive aggregate maximum and explicit rolling/fixed window;
- optional canonical seller-principal allowlist;
- selected saved-instrument mode required by the profile.

The policy evaluator is pure and receives the already accepted obligation plus recent successful/pending authorizations from the owner-only profile/run index. Evaluation either permits signing that exact producer authorization or requires interactive handling. It cannot select a different profile, amount, destination, seller, obligation, instrument, or expiry. Reserve aggregate usage under the deterministic marketplace operation ID before direct authorization so concurrent buyer processes cannot each pass the bound; exact retry reuses the reservation. Failed/expired authorization releases or terminally classifies the reservation according to policy semantics.

A producer `requires_action` result under off-session use remains the same authorization and financial operation. The common `--action open|print|fail` path handles it. `fail` stops local interaction but does not manufacture provider failure or a replacement authorization.

**Alternative considered:** configure automation at the storefront/listing. Rejected because it would let sellers influence payer consent and cannot enforce buyer-local aggregate limits.

**Alternative considered:** treat a ready mandate as authorization. Rejected because setup consent and current commercial consent are separate.

### 6. Generalize transient action handling without persisting action material

Reuse the existing buyer action dispatcher rather than adding rail-specific UI. Normalize released action models into safe categories used only during the current process:

- setup/Account Link;
- interactive payment/Checkout;
- off-session confirmation;
- bank instructions.

The value passed to `open`/`print` is never sent to run-log serialization. Durable events contain action kind, expiry, safe reason/deadline, settlement/authorization refs, and profile only. On resume the buyer calls storefront status for escrow actions or direct payer status for payer setup and uses the fresh returned action. A stale action can therefore expire without losing resumability.

`open` remains meaningful only for browser-capable actions. For instruction payloads it displays the authority-produced transient representation in the current terminal/browser surface according to the released client contract; it does not parse bank fields into marketplace models. `print` emits the transient value to the user-controlled terminal, not structured logs/evidence. `fail` returns a deterministic interaction-required error.

**Alternative considered:** store action URLs/details encrypted in buyer run logs. Rejected because they are bearer-like, expire, and would make marketplace responsible for material already recoverable from the authority.

### 7. Preserve one common asynchronous servicing state machine

Do not add ACH or bank-transfer jobs. `kit/settlement-runtime` continues to journal `materialize`, `status`, `fulfill`, `check`, `collect`, and `reclaim`. Profile and authorization live in immutable obligation params; normalized hosted reason/deadline/action metadata lives in mechanism state.

Update adapter projections so only the producer's authoritative funded/available public state maps to runtime `ready`. `awaiting_payment`, setup complete, bank instructions issued, ACH processing, `requires_action`, webhook delivery, and provider pending all remain `pending`/`requires_action`. A return before fulfillment prevents fulfillment/collection and follows eligible hosted reclaim/recovery. A return after VM fulfillment begins but before collection preserves the immutable fulfillment record, blocks collection, and orders domain-owned VM teardown/capacity cleanup to convergence while the hosted authority owns financial recovery. A post-collection loss maps to `manual_required`/incident while completed marketplace effects remain immutable.

At the expiry edge, the existing runtime status retrieval and compare-and-set are authoritative. It reuses the accepted profile, authorization, settlement, obligation, and operation IDs. Current config/profile readiness is admission policy only and cannot redirect recovery.

`ensure_hosted_fulfillment` remains the only VM provision gate. It is called only after the runtime record has authoritative hosted ready state and uses the accepted VM provision terms exactly once.

**Alternative considered:** provision on Checkout completion or accepted debit. Rejected because neither proves profile-specific available funding.

### 8. Legacy card data has a decoder, not an alias

Marketplace storage migrations classify already accepted card-only obligations by their persisted historical shape and preserve every option ID, obligation ref/hash, hosted settlement ref, operation ID, state, receipt, and request fingerprint. The adapter selects a legacy decoder only when reading such persisted records. It invokes the producer's recovery-compatible historical operation without requiring a payer profile or a newly signed authorization.

The buyer profile store requires no consumer schema migration: its schema-1 `AuthorityPayerBinding` already contains exactly authority, environment, opaque binding reference, bound principal, and lifecycle state. Expanded funding writes that existing owner-only field and deliberately adds no instrument, provider, action, or commercial data to profile metadata.

New config, publication, query parsing, compatibility, plan creation, and materialization reject `payment_method_types`, `method="card"`, and the producer's internal recovery-only classification. Config migration maps a valid seller card publication clause to `card.v1`; that changes future option IDs intentionally and does not rewrite accepted options.

Ambiguous rows fail migration atomically and are reported for operator repair. No code infers a new authorization or relabels an historical operation as satisfying the expanded contract.

**Alternative considered:** rewrite all historical rows to `card.v1`. Rejected because historical purchases never signed the new authorization envelope.

### 9. Release, deployment, and evidence cut over together

Update `kit/hosted-settlement/pyproject.toml` and lock to the exact producer client wheel. Repository `.dist` and initialization/reinitialization targets explicitly rebuild/verify/reinstall it; no editable sibling path is added. Marketplace release verification records the hosted producer manifest/client/service/schema/migration/provenance coordinates separately from marketplace wheels/image/source/workflow.

Compose and Helm schemas/config templates gain only exact public profile policy, authority release pins, buyer local-profile/config paths, and marketplace signer Secret references. They reject provider credentials/IDs, stable payer/instrument data, hosted persistence, and raw actions. The hosted service remains separately deployed.

Credential-free marketplace tests use injected exact released-client collaborators at the hosted kit seam and the real common runtime/repositories. Producer-internal provider-port and webhook-inbox recovery remain established by signed producer conformance evidence; marketplace tests verify that evidence and do not import or simulate hosted internals. The protected lane expands the existing ordinary VM flow rather than adding a test-only financial client. Reports identify each selected profile and independent marketplace/producer release, and mark unavailable external Stripe assertions explicitly.

**Alternative considered:** pin only a compatible client version and check server capabilities at runtime. Rejected because released schema/canonicalization/profile behavior is security- and recovery-sensitive and must be exact.

## Risks / Trade-offs

- **[One mechanism readiness object now carries a profile map]** → Keep the map typed, sorted, allowlisted, and covered by shared conformance; retain mechanism-wide fields for existing callers.
- **[A direct authority path can accidentally spread hosted models into core/domain code]** → Keep façade and client dependency in `kit/hosted-settlement`; add import-boundary and package-content tests.
- **[Concurrent automation can exceed aggregate limits]** → Reserve against the owner-only buyer profile/run index under the deterministic operation ID before signing; exact retry is idempotent.
- **[A saved instrument changes after option selection]** → Treat discovery readiness as advisory and revalidate immediately before exact authorization; never fall back after acceptance.
- **[Delayed bank funding makes CLI runs long-lived]** → Persist only safe state and make ordinary resume authoritative; never block correctness on a live process or webhook.
- **[Legacy and new card paths can be confused]** → Select legacy decoding only from migrated accepted rows, reject it at every admission boundary, and cover terminal/nonterminal fixtures.
- **[Protected Stripe test mode may not expose every ACH/return timing]** → Attribute only exercised retrieval-backed assertions and record exact unavailable prerequisites.
- **[Producer and consumer releases can drift]** → Verify exact manifest, wheel, API/schema/capability, service image, and independent source identities before publication or mutation.

## Migration Plan

1. Land and publish the producer's signed expanded release; verify its exact client wheel, service image, schema migration, capabilities, conformance, and recovery fixtures without changing marketplace activation.
2. Implement marketplace read/validation support, profile-indexed readiness, buyer payer façade, authorization flow, runtime persistence additions, legacy decoder, migrations, and focused tests while old card publication remains active only in the pre-activation artifact set.
3. Build marketplace wheels/image and generated config/Helm/Compose/release evidence against the exact producer release. Run credential-free package, typing, migration, redaction, adapter, buyer, storefront, runtime, and legacy recovery checks.
4. Preflight a protected environment with the new producer release and marketplace artifacts. Create/attach payer fixtures only through direct released-client commands; do not copy provider identities into marketplace config.
5. Stop new negotiation admission, drain or durably checkpoint active starts, back up buyer profile stores and storefront databases, apply config/data migrations, install matching artifacts, and verify schema/release/profile readiness before resuming publication.
6. Activate new `card.v1` publication first, then enabled bank profiles only when their exact readiness passes. Existing accepted card obligations continue through the recovery-only decoder.
7. Run protected card, bank transfer, ACH, off-session action fallback, restart, fulfillment, collection/reclaim, and evidence checks supported by the environment. Mark unavailable external assertions explicitly.
8. Rollback before new-profile publication/authorization restores the matching prior marketplace config, stores, wheels/image, and producer coordinates together. After any new expanded authorization or publication is accepted, roll forward; do not expose aliases or ask the old consumer to interpret new records.

## Design promotion plan

| Accepted decision | Permanent destination |
|---|---|
| Exact profile vocabulary, per-profile readiness, compatibility, automation bounds, recovery pins | `openspec/specs/settlement-configuration/{spec,architecture}.md` |
| Separate ready options, exact safe start input, delayed funding gate, legacy publication cutover | `openspec/specs/storefront-publication/{spec,architecture}.md` |
| Direct payer commands, exact authorization, local policy, action/resume contract | `openspec/specs/buyer-orchestration/{spec,architecture}.md` and VM buyer current-state docs |
| Immutable profile/authorization, authoritative funding, common runtime/reclaim/loss semantics | `openspec/specs/settlement-servicing/{spec,architecture}.md` |
| Thin kit boundary and direct payer versus mediated escrow paths | `openspec/specs/market-composition/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md` |
| Exact artifact/config/secret/migration/rollback boundaries | `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Credential-free and protected profile evidence attribution | `openspec/specs/test-compatibility/{spec,architecture}.md` and `docs/development/TESTING.md` |
| Current delivery status and remaining domain adopters | `docs/development/ROADMAP.md` |

The implementation closeout records these exact destinations in this change's promotion section, runs comment hygiene, removes temporary migration commentary from production code, and compresses completed task history only after every promoted destination and required check is verified.

## Design promotion record

| Material decision | Permanent heading |
|---|---|
| Closed funding-profile vocabulary, independent readiness, clause identity, compatibility, bounded automation, and immutable recovery pins | `openspec/specs/settlement-configuration/spec.md` — `Requirement: Hosted options use exact funding profiles`, `Requirement: Hosted profile readiness is independent and exact`, `Requirement: Buyer hosted compatibility includes local payer readiness`, `Requirement: Buyer off-session automation policy is explicitly bounded`, and `Requirement: Recovery uses pinned mechanism identity`; `openspec/specs/settlement-configuration/architecture.md` — `Expanded hosted funding profiles` |
| Separate ready VM options, authoritative accepted-state derivation, exact safe start, and transient public actions | `openspec/specs/storefront-publication/spec.md` — `Requirement: Hosted publication separates ready funding alternatives`, `Requirement: Hosted accepted plan carries authorization safely`, `Requirement: Delayed funding does not authorize VM fulfillment`, and `Requirement: Server-authoritative settlement start`; `openspec/specs/storefront-publication/architecture.md` — `Exact hosted alternatives and accepted authorization` |
| Direct payer/setup/instrument/authorization ownership, storefront-mediated escrow, persistent signer selection, action policy, and restart | `openspec/specs/buyer-orchestration/spec.md` — `Requirement: Buyer payer-profile utilities are direct and namespaced`, `Requirement: Exact purchase authorization precedes storefront start`, `Requirement: Off-session automation is buyer-owned and obligation-exact`, and `Requirement: Storefront-mediated hosted buyer action`; `openspec/specs/buyer-orchestration/architecture.md` — `Persistent payer binding and exact authorization`; `docs/buyer-quickstart.md` — `2. Configure`, `4. Buy`, `5. Resume an interrupted buy`, and `Hosted funding profiles` |
| Provider-neutral kit ownership, released-client signer boundary, and distinct direct-payer and mediated-escrow lanes | `openspec/specs/market-composition/spec.md` — `Requirement: Hosted payer calls bypass storefront without bypassing authority`, `Requirement: Hosted consumer remains provider-neutral`, and `Requirement: Thin hosted consumer boundary`; `openspec/specs/market-composition/architecture.md` — `Direct payer lane and mediated escrow lane`; `docs/development/ARCHITECTURE.md` — `Hosted fiat settlement boundary`; `docs/seller-quickstart.md` — `2. Configure` and `Optional hosted fiat publication` |
| Immutable profile/authorization binding, authoritative funding gates, common leases/CAS journal, legacy-card recovery, and loss/reclaim semantics | `openspec/specs/settlement-servicing/spec.md` — `Requirement: Hosted obligation pins profile and authorization`, `Requirement: Authoritative profile funding precedes every domain effect`, `Requirement: Profile-specific reclaim and loss remain authority-owned`, and `Requirement: Legacy card obligations recover without public alias`; `openspec/specs/settlement-servicing/architecture.md` — `Profile-bound hosted servicing` |
| Atomic configuration/data/artifact cutover, exact release pins, secret separation, staged activation, and rollback | `openspec/specs/deployment-state/spec.md` — `Requirement: Expanded hosted config cutover is explicit and atomic`, `Requirement: Marketplace deployment never owns payer/provider state`, `Requirement: Immutable hosted release consumption`, and `Requirement: Marketplace deployment config contains consumer data only`; `openspec/specs/deployment-state/architecture.md` — `Expanded consumer cutover and rollback`; `docs/development/DEPLOYMENT_AND_CONFIG.md` — `Settlement consumer configuration and cutover` |
| Credential-free consumer jurisdiction, protected provider evidence attribution, independent release identities, prerequisite failure, and recursive redaction | `openspec/specs/test-compatibility/spec.md` — `Requirement: Expanded hosted consumer behavior is tested at owned boundaries` and `Requirement: Protected hosted evidence is attributable and sanitized`; `openspec/specs/test-compatibility/architecture.md` — `Expanded consumer evidence matrix`; `docs/development/TESTING.md` — `Hosted Settlement Evidence` |
| VM delivery status and remaining independent adopters | `docs/development/ROADMAP.md` — `Hosted settlement release status` |
