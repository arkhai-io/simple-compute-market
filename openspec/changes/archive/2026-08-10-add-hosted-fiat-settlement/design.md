## Context

The three prerequisites are archived: settlement plans carry stable per-obligation identity, `arkhai-kit-settlement-runtime` owns one durable operation journal/worker with compare-and-set leases, and buyer policy has a typed constrained preference seam. Current `alkahest.v1` negotiation, `/settle`, SQLite `escrows`, run logs, and domain compositions are production compatibility surfaces. See `proposal.md` for motivation.

The hosted authority is a separate repository and trust domain. Marketplace code can consume its released client and image contract but cannot share source, state, provider credentials, or operational authority.

## Goals / Non-Goals

**Goals:**

- Add `fiat.stripe.v1` as another conditional-escrow adapter over the existing lifecycle.
- Preserve exact Alkahest behavior and legacy serialization when additive fields are absent.
- Keep provider mutation, custody, EAS/RPC implementation, and recovery outside this repository.
- Make option identity, accepted obligation identity, operation identity, and release identity deterministic and restart-safe.
- Keep fulfillment evidence minimal, versioned, and secret-free.

**Non-Goals:**

- No in-tree Stripe service, provider SDK, arbitrary arbiter execution, shared database, or generic money-movement action.
- No application fee, tax, partial refund, post-transfer reversal, or dispute allocation policy.
- No hosted settlement dependency for API credits or bare metal.
- No change to existing authentication modules, Alkahest carriers/routes, run-log fields, or escrow persistence.

## Decisions

### Cross-repository release boundary

`../hosted-settlement-service` owns `arkhai-hosted-settlement-client==0.1.0`, the `hosted_settlement_service` image, OpenAPI and generated conformance fixtures, migration version, SBOM, provenance, and a signed manifest binding all hashes. This repository pins that exact manifest/wheel/image and verifies the hosted repository/workflow identity. Local integration also consumes built wheels and image digests; it never uses an editable sibling path.

Only the released client crosses the Python boundary. The client owns provider-neutral Pydantic wire models and body-bound EIP-191 signing. `kit/hosted-settlement` imports those models rather than copying them. Marketplace deployment owns only URL, request credential reference, timeouts, expected manifest/API/capabilities, and trust identity.

### Runtime port and adapters

The landed `ConditionalEscrowClient` port remains asynchronous and contains:

- `materialize(obligation, operation_ref) -> materialization`
- `get_status(escrow_ref) -> status`
- `check(escrow_ref, fulfillment_ref, operation_ref) -> evaluation`
- `collect(escrow_ref, operation_ref) -> receipt`
- `reclaim_expired(escrow_ref, operation_ref) -> receipt`

Results use existing lifecycle vocabulary and add only opaque escrow reference, optional buyer action, optional condition anchor, and opaque durable receipt. The Alkahest adapter continues to wrap `AlkahestClient`; no HTTP behavior or SDK equivalence is claimed. The hosted adapter wraps `HostedSettlementAsyncClient`, maps `false` to pending, transport uncertainty to retry, and service review to manual-required.

`market_hosted_settlement` validates direction, integer minor units, lowercase currency, account reference, expiry, and the released typed condition before the service is called. It contains no provider branching.

### Conditions and fulfillment evidence

Core keeps `SettlementObligation.conditions` opaque. The runtime/client contract standardizes:

- `ConditionDescriptor(condition_id, evaluator, demand)`;
- evaluator kinds `alkahest.evm-arbiter.v1`, `external-http.v1`, and `builtin.v1`;
- configuration-owned `resolver_id`, never a negotiated URL;
- canonical demand encoding `evm-abi` or `application/jcs+json`;
- `FulfillmentRef` variants `eas.v1`, `portable-inline.v1`, and `portable-remote.v1`.

The VM plugin owns the evidence codec. EAS conditions project only resolver ID and fulfillment UID. Portable conditions construct only the selected allowlisted proof projection. The codec uses explicit field allowlists and canary tests; it never serializes generic fulfillment results.

### Additive negotiation carriers

`market_core.schemas` gains:

- `SettlementOption(option_id, mechanism, asset, rates, params)`;
- `SettlementSelection(mechanism, option_id, expiration_unix)`;
- optional `settlement_options` on listing/proposal envelopes and optional `settlement_selection` on accepted terms.

Serializers omit `None` and empty lists so existing model dumps and signatures are identical. Existing `accepted_escrows`, `EscrowProposal`, `accepted_escrow_proposal`, and `accepted_escrow_terms` stay live.

A VM hosted option contains account reference, separate-charge/transfer flow, card-only method tuple, currency/rate, and one typed condition. Its ID is SHA-256 of sorted compact canonical JSON. Acceptance reloads the stored option, exact-matches ID and content, applies current duration pricing/expiry, rejects values below one minor unit, and creates one buyer-funded/seller-claimed hosted obligation.

### Buyer selection and action UX

The buyer normalizes legacy entries and settlement options into the landed immutable preference candidate without changing compatibility authority. New mechanism/asset CLI filters run before policy preference. Existing interactive authority and deterministic fallback remain.

Stripe selection performs no provider call before accepted terms. After acceptance, the buyer calls the marketplace settlement-start route. Redirect URL is held only in memory, printed, and opened unless `--no-browser`; run logs persist opaque settlement reference, state, action kind, and expiry. Resume retrieves current action/status.

### Publication and public routes

VM publication preflights hosted account readiness and resolver/condition capability. Failure suppresses only hosted options and emits sanitized diagnostics. Seller acceptance always derives authoritative fields from stored option and accepted plan.

New routes are:

- `POST /api/v1/settlements` with negotiation/obligation IDs only;
- `GET /api/v1/settlements/{settlement_ref}`;
- buyer-authorized `POST /api/v1/settlements/{settlement_ref}/reclaim`.

Internal collection remains in the shared claims engine. `/api/v1/settle/{escrow_uid}` is not aliased or modified.

### Shared persistence and ordering

The shared settlement obligation table receives nullable hosted reference, public action kind, action expiry, and condition anchor plus indexes. Existing `escrows` is untouched; no backfill or dual-read is introduced. URLs and provider IDs are never persisted.

After hosted funding, the marketplace reserves `funded → fulfilling`, runs existing VM provisioning, and commits immutable fulfillment before condition evidence is submitted. Reclaim at expiry succeeds only if there is no fulfillment lease/success, collect/provider submission, or reserved satisfied evaluation. The same compare-and-set makes it mutually exclusive with satisfaction reservation. Fulfillment success resumes check/collect after restart even past expiry. Fulfillment failure drives terminal hosted reclaim/refund before the existing failure dispatcher releases capacity.

### Packaging and deployment

Root distribution, review-wheelhouse scope, publishing workflow, VM storefront package/image, and lock refresh include the exact adapter/client. API-credit and bare-metal manifests remain unchanged. Compose consumes a verified hosted image by digest for E2E and never builds sibling source. Kubernetes renders only external client configuration and trust material; no hosted service resource exists here.

### Compatibility and rollback

All additions are optional and disabled by default. Rollback disables publication/start of new hosted options while workers continue servicing already accepted hosted obligations using the pinned adapter and manifest. The adapter/client cannot be removed until no nonterminal hosted obligations remain. Alkahest rollback is unnecessary because its code and data path are unchanged.

## Risks / Trade-offs

- Platform custody and provider incidents remain a centralized trust assumption; UI/docs must not describe this as on-chain or segregated escrow.
- A remote authority outage can delay fulfillment or refund, so durable manual state is preferred over optimistic completion.
- Strict artifact pinning adds release coordination but prevents contract/image skew.
- Additive carriers increase negotiation surface; byte-parity fixtures and exact option matching contain the compatibility risk.
- One hosted mechanism serves EVM, remote, and built-in predicates; capability preflight and typed descriptors prevent mechanism proliferation from hiding evaluator differences.

## Implementation map

- Core carriers: `core/src/market_core/schemas.py` plus focused wire fixtures.
- Runtime port/models: `kit/settlement-runtime/src/market_settlement_runtime/`.
- Adapter: new `kit/hosted-settlement/`.
- Shared persistence: `core/storefront/src/core_storefront/sqlite_{client,migrations}.py` and runtime repository models.
- VM seller/publication/runtime: `domains/vms/storefront/src/market_storefront/` and domain settlement codecs.
- VM buyer: `domains/vms/buyer/` and core buyer normalization.
- Packaging/deployment: root/VM manifests, review-wheelhouse mapping, release workflows, Compose, and storefront Helm values/templates.

## Permanent documentation promotion

- Normative consumer lifecycle and adapter behavior: `openspec/specs/settlement-servicing/spec.md`.
- Negotiation carriers: `openspec/specs/negotiation-protocol/spec.md`.
- Selection and buyer action: `openspec/specs/buyer-orchestration/spec.md` and companion architecture.
- Publication/routes: `openspec/specs/storefront-publication/spec.md` and architecture.
- Cross-repository composition: `openspec/specs/market-composition/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md`.
- Consumer deployment/release pinning: `openspec/specs/deployment-state/{spec,architecture}.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, and `docs/development/RELEASING.md`.
- Current scope and authoring guidance: `docs/development/ROADMAP.md`, capability index, buyer/seller/domain-authoring documentation.


### Promotion record

| Durable decision | Permanent destination |
| --- | --- |
| Additive option/selection carriers and exact accepted-option matching | `openspec/specs/negotiation-protocol/spec.md`; `openspec/specs/storefront-publication/{spec,architecture}.md` |
| Thin released-client adapter and shared hosted obligation lifecycle | `openspec/specs/settlement-servicing/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Buyer selection, transient action handling, and compatibility authority | `openspec/specs/buyer-orchestration/{spec,architecture}.md`; buyer documentation |
| Cross-repository authority, custody, dependency, and package boundaries | `openspec/specs/market-composition/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md`; domain-authoring documentation |
| Exact release pins, startup verification, Compose, and Helm consumer-only topology | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/development/RELEASING.md` |
| Current delivery boundary and remaining external operations | `docs/development/ROADMAP.md`; `openspec/specs/README.md`; seller documentation |

### Roadmap impact

The roadmap now records hosted fiat settlement as implemented while keeping
multi-writer deployment, broader evaluator/payment support, and changed loss
allocation outside this change.

### External verification availability

- Deployed Helm smoke test: unavailable because no Kubernetes cluster or
  deployment credentials were provided.
- Stripe test credentials were supplied and verified as non-live. The platform
  has no connected accounts and Stripe rejected account creation because
  Connect is not enabled, so a connected-account transfer and pre-transfer
  refund remain unavailable; no reachable webhook endpoint was provided.
- Supported EAS testnet UID and finalized arbiter evidence: unavailable because
  no testnet RPC/EAS endpoint or funded chain signer was provided.
- Protected trusted-publisher workflow execution: unavailable because no
  repository release permission was provided. The exact signed `0.1.0` release
  was locally staged and verified instead.