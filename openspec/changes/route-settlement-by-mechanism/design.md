# Design

## Accepted boundary

Each domain role declares one immutable `mechanism -> stage` table. Registration
owns configuration, publication, readiness and compatibility; a role table owns
execution support. Accepted dispatch uses the exact Agreement's mechanism and
unchanged outcome. Missing accepted support refuses before effects; priorities
and enablement are fresh-admission policy, not authority to reinterpret a deal.

`market_core` owns dependency-light `SettlementStageTable[StageT]` and
`SettlementEvidence`. Table values are opaque: no callable bound, mandatory
stage methods, financial lifecycle or actor order. Evidence carries exactly
negotiation ID, mechanism, opaque reference, domain status and domain payload.
Core validates shape/identity; the selected seller stage verifies authoritative
source evidence and supplies validated delivery facts. Seller-first and fused
contact stages remain valid. `_settle_one` is an explicitly bound helper, never
an escrow fallback. Buyer recovery retains opaque references and exact accepted
inputs; unused synthetic buyer-evidence plumbing was removed after review.

Seller evidence binds negotiation, exact Agreement digest, established reference
and versioned source/delivery payload. Verified facts are immutable. Domain-owned
delivery context, phases, claims and private results remain separate. Common
physical convergence and credit issuance consume normalized evidence; selected
continuations own revalidation, attestation, claim binding, compensation and
failure policy. Continuations are reconstructed from accepted state, never
serialized or selected by current priority. Payments create no escrow progress
or obligation; genuine Alkahest servicing remains.

The credits authority receives the existing operator-authenticated immutable
issuance command, not raw settlement evidence or a mechanism allowlist. Grant
identity derives uniformly from negotiation ID; the digest binds canonical
owner, service/resource, quantity and key target. An operational quota hold is
excluded from immutable intent so an expired hold may be replaced after
rechecking. Key, balance, quota and replay remain service-owned; signed issuance
evidence and private credentials remain storefront-owned. A second authorization
protocol would duplicate policy without improving this existing operator trust
boundary and is rejected.

An optional convention belongs in a kit chosen when concrete reuse justifies
implementation, not core or either mechanism package. No protocol/adapter is
implemented here; contact, seller-first and fused stages need no convention.
Assuming settlement-runtime as its home is rejected because servicing belongs
to escrow mechanisms, not charge-first payments.

## Compatibility and execution disposition

This cutover makes no backward-compatibility promise. Introducing evidence and
grant migrations are edited in place; incompatible disposable databases require
explicit owned reset while effects/recovery are quiesced. There is no silent
copy/adoption, payment chain sentinel or old issuance-payload adapter. Shared
escrow carriers/obligation runtime and listing/registry wire changes are deferred
to `move-escrow-into-alkahest` and `drop-escrow-from-shared-wire`.

Implementation/review history is retained in Git and the [owner packets](../../../docs/attachments/route-settlement-closeout/final.md#documentation-and-residual-ownership).
The [baseline 50-site inventory](../../../docs/attachments/route-settlement-closeout/baseline-inventory.md)
preserves T/E/M and proposal classifications without duplicating them here.

Post-repair joined build/reinit, original suites and all four worker entries
pass. Malformed verified VM persistence refuses; bare-metal Alkahest recovery
checks active journal plus authoritative chain evidence/index; VM standalone
negotiation uses selected-stage hooks and fresh acceptance requires explicit
selection. API-credit verified receipt recovery survives unavailable polling,
prepared Alkahest delivery avoids duplicate preparation, and failure references
are neutral. Buyer reference recovery and real carrier properties replace
unused synthetic buyer evidence/declaration assertions.

[Final evidence](../../../docs/attachments/route-settlement-closeout/final.md)
records 680 original primary passes, 723 cases across expanded selections,
repeat slice counts, typing/vectors, controlled readiness/cleanup and unrun live
lanes. Controlled temporary databases/run logs and synthetic signers establish
wiring, not live ledger/hardware qualification. No owned ready external target
was supplied. Live qualification stays with its existing private-payment/domain
owners; it is not substituted with mocked success.

## Final inventory

The [final inventory](../../../docs/attachments/route-settlement-closeout/final-inventory.md) found two surfaces outside the tables: `market credits negotiate` resolved Alkahest wallet, chain, escrow selection, price scaling and proposal itself (B1), and bare-metal introductions required current contact enablement for accepted reveal/re-read (B2). Both now go through the declared stages: B1 in [apicredits-negotiate](../../../docs/attachments/apicredits-negotiate/index.md), B2 in [contact-disablement](../../../docs/attachments/contact-disablement/index.md). No other mechanism dispatch remains outside a stage.

## Deferred residuals

- Quota-ledger `escrow_uid` correlation API/persistence rename is added to
  `move-escrow-into-alkahest/proposal.md`, with its kit/site owner and consumers.
- Cross-domain adapter/credit-identity duplication: [idea #261](https://github.com/arkhai-io/simple-compute-market/issues/261).
- API-credit client domain wheel's web3/Alkahest dev closure in the credits service:
  [idea #262](https://github.com/arkhai-io/simple-compute-market/issues/262).
- Optional convention adapter extraction is deferred until concrete reuse earns
  a kit home. No speculative module/dependency was created.

## Design promotion record

| Accepted decision | Permanent location | Disposition |
|---|---|---|
| Opaque core carriers and unconstrained actor order | `openspec/specs/market-composition/spec.md`; `architecture.md#typed-phase-boundaries`; `docs/development/ARCHITECTURE.md#composition-from-above-and-below` / `#package-and-dependency-layers` | Permanent, promoted |
| Registration/admission is distinct from execution; support intersection | `openspec/specs/settlement-configuration/spec.md`; `architecture.md#registration-and-ownership` / `#readiness-publication-and-selection` | Permanent, promoted; B1/B2 limitations disclosed |
| Agreement-only buyer dispatch/recovery; buyer keeps references, not evidence | `openspec/specs/buyer-orchestration/spec.md`; `architecture.md#configured-mechanism-choice-and-buyer-actions` / `#current-limits` | Permanent, promoted; standalone credits limitation disclosed |
| Domain evidence/progress, common delivery, stage continuations and recovery gates | `openspec/specs/vm-storefront-fulfillment/spec.md` / `architecture.md#evidence-and-delivery-ownership`; `openspec/specs/physical-provisioning/spec.md` / `architecture.md#bare-metal-storefront-pull-boundary` / `#signed-payment-receipt-boundary`; `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities` / `#settlement-servicing` | Permanent, promoted |
| Credits authorization/authority, uniform grant replay, separate issuance/private results | `openspec/specs/api-credits/spec.md`; `architecture.md#authority-boundaries` / `#idempotency-boundaries` / `#payment-composition-and-recovery` / `#failure-and-compensation`; repository `ARCHITECTURE.md#authority-boundaries` | Permanent, promoted |
| Opt-in convention has a future kit home, no mandatory adapter | `openspec/specs/market-composition/architecture.md#settlement-runtime-composition`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership` | Boundary permanent/promoted; implementation deferred; core protocol rejected |
| Explicit fresh-database reset, no compatibility adoption | Three domain specs; VM `architecture.md#explicit-database-reset`, physical `architecture.md#explicit-storefront-database-reset`, API credits `architecture.md#explicit-database-reset`; repository `ARCHITECTURE.md#build-packaging-and-initialization` | Current reset contract permanent/promoted; in-place migration method temporary provenance |
| Goal 6 current-state and gap mapping | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` | Updated: core/delivery and B1/B2 gaps closed; carrier/wire/live gaps retained |
