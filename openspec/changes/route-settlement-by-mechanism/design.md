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
records the repaired findings, controlled readiness/cleanup and unrun live
lanes. The [validation record](../../../docs/attachments/route-settlement-closeout/validation.md)
names the `make` targets, the regression test holding each finding, and counts
and end-to-end runs on the merged tree. Controlled temporary databases/run logs
and synthetic signers establish wiring, not live ledger/hardware qualification.
Live payment qualification stays with the payments service's own end-to-end
suite and physical qualification with the domain release gate; neither is
substituted with mocked success.

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
- The seller introduction client has no production caller yet; a storefront
  operator command that shows one introduction would be its first. One kit client
  serving both parties, with the buyer moved off `IntroductionTransport`, is a
  possible later consolidation.

## Post-merge reconciliation

The development branch's bare-metal provisioned-deal work arrived after this
change's implementation and review. The merged tree is the one this change
closes out on; these decisions bring it back to the change's invariants and the
repository's current closeout rules.

- **Obligation servicing resolves the accepted entry.** Bare-metal servicing
  had regained a concrete-mechanism switch: the worker's ready and terminal
  hooks compared `record.obligation["mechanism"]` with Alkahest and contact
  exchange, and the runtime decided which mechanisms needed an Alkahest
  lifecycle. Each seller entry now declares an optional servicing factory
  (a `ready`/`terminal` continuation over one runtime): Alkahest builds its
  lifecycle when its section is configured, contact exchange declines because
  its reveal binds the obligation, and payments has no obligations. The
  runtime resolves the entry from the accepted Agreement of
  `record.agreement_ref`, refuses an obligation whose mechanism differs from
  that Agreement, and refuses an entry with no servicing before any effect.
  Rejected: looking up the obligation's recorded mechanism directly (it is
  accepted state too, but recovery resolves from the Agreement everywhere
  else) and keeping a conditional chain (a second dispatch declaration that a
  new mechanism must also edit).
- **Client-contract integration for the two repairs.** Standalone credits
  negotiation runs the real buyer command against the real API-credit
  storefront served on loopback, from the storefront's integration suite with
  the buyer as a development dependency. The command does not use the typed
  storefront client, and moving buyers onto it is not required here. Accepted
  contact reveal after disablement drives negotiation through
  `StorefrontClient`, the buyer's reveal/read through the production
  `IntroductionTransport`, and the seller's re-read through a typed
  `IntroductionSellerClient` in `kit/contact-exchange`; the disabled-restart
  persistence assertions stay. The seller client follows the kit's operator
  client: per-role methods over the core client's market-neutral
  `authenticated_request`, with the route and operation shared with the
  storefront route. Re-reading is its only method, since starting a reveal is
  the buyer's alone. Rejected: a role parameter on the buyer transport (seller
  code would depend on the buyer package), a method on the core client (which
  carries no mechanism vocabulary), and a domain-local helper (VM composes
  contact exchange too).
- **Validation evidence is regenerated, not annotated.** The joined replay
  scripts hard-coded wheel versions and pre-merge paths. They are replaced by a
  validation record that names `make` targets and the change's own regression
  tests, with counts from the merged tree; the pre-merge packet stays in Git
  history.
- **Public-repository discipline.** The payments wire contract is identified
  by content: the vendored schema and vectors are named by SHA-256 and
  described as the payments service's published contract, with no repository
  name or commit in the kit, its generated models, permanent documents or
  change documents. Live payment qualification is described by its owner role
  (the payments service's own end-to-end tests).
- **Fresh selections carry their bargained amount.** The first end-to-end run
  on the merged tree showed that VM buyer openings selecting a rated Alkahest
  option carried no `fields.amount`, and that the force-accept scenario still
  opened with a legacy escrow proposal; the VM seller, which requires an
  explicit selection, refused both. Explicit selection stays the rule. The
  buyer's opening now decides scalar bargaining from the selected option, as
  the seller's policies do: core places the advertised option the buyer
  selected in the opening's policy context, and the kit's opening policy
  injects the amount when that option bargains one. This replaces the
  API-credit buyer's per-entry rate injection. The force-accept scenario opens
  with a selection. The seller materializes a selected Alkahest option into a
  concrete escrow plan, so the buyer checks that plan against the selected
  entry (chain, escrow contract, token, arbiter) through the Alkahest kit, and
  the scenario's listing advertises the dev chain's real escrow contract.
  Rejected: accepting legacy escrow-shaped openings on VM by mapping them to
  Alkahest, which would infer the mechanism from an escrow proposal's presence.
- **End-to-end lease lookups follow the negotiation.** VM delivery holds and
  commits site capacity under the deal's negotiation, so a deal settled through
  escrow has no escrow on its reservation; the end-to-end lease and commitment
  checks find the reservation by the negotiation its hold names.
- **Closeout follows the current checklist:** documentation citations,
  `make check-packaging`, and the end-to-end pipeline with its run recorded.
  Goal 6's gap table drops the contact-exchange and delivery rows that the
  archived cross-compute and retention work closed.

## Design promotion record

| Accepted decision | Permanent location | Disposition |
|---|---|---|
| Opaque core carriers and unconstrained actor order | `openspec/specs/market-composition/spec.md`; `architecture.md#typed-phase-boundaries`; `docs/development/ARCHITECTURE.md#composition-from-above-and-below` / `#package-and-dependency-layers` | Permanent, promoted |
| Registration/admission is distinct from execution; support intersection | `openspec/specs/settlement-configuration/spec.md`; `architecture.md#registration-and-ownership` / `#readiness-publication-and-selection` | Permanent, promoted; B1/B2 repaired (10.2/10.3) |
| Agreement-only buyer dispatch/recovery; buyer keeps references, not evidence | `openspec/specs/buyer-orchestration/spec.md`; `architecture.md#configured-mechanism-choice-and-buyer-actions` / `#current-limits` | Permanent, promoted; standalone credits negotiation repaired (10.2) |
| Domain evidence/progress, common delivery, stage continuations and recovery gates | `openspec/specs/vm-storefront-fulfillment/spec.md` / `architecture.md#evidence-and-delivery-ownership`; `openspec/specs/physical-provisioning/spec.md` / `architecture.md#bare-metal-storefront-pull-boundary` / `#signed-payment-receipt-boundary`; `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities` / `#settlement-servicing` | Permanent, promoted |
| Credits authorization/authority, uniform grant replay, separate issuance/private results | `openspec/specs/api-credits/spec.md`; `architecture.md#authority-boundaries` / `#idempotency-boundaries` / `#payment-composition-and-recovery` / `#failure-and-compensation`; repository `ARCHITECTURE.md#authority-boundaries` | Permanent, promoted |
| Opt-in convention has a future kit home, no mandatory adapter | `openspec/specs/market-composition/architecture.md#settlement-runtime-composition`; `openspec/specs/settlement-configuration/architecture.md#registration-and-ownership` | Boundary permanent/promoted; implementation deferred; core protocol rejected |
| Explicit fresh-database reset, no compatibility adoption | Three domain specs; VM `architecture.md#explicit-database-reset`, physical `architecture.md#explicit-storefront-database-reset`, API credits `architecture.md#explicit-database-reset`; repository `ARCHITECTURE.md#build-packaging-and-initialization` | Current reset contract permanent/promoted; in-place migration method temporary provenance |
| Goal 6 current-state and gap mapping | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` | Updated: core/delivery and B1/B2 gaps closed; carrier/wire/live gaps retained |
| Seller entries own obligation servicing; hooks resolve the accepted Agreement's entry | `openspec/specs/physical-provisioning/spec.md#requirement-bare-metal-obligation-servicing-follows-the-accepted-seller-entry`; `openspec/specs/market-composition/spec.md#requirement-mechanism-continuation-stays-stage-owned`; `docs/development/ARCHITECTURE.md#settlement-servicing` | Permanent, promoted |
| Fresh selections bargain their option's amount; a materialized plan is checked against the selected entry | `openspec/specs/negotiation-protocol/spec.md#requirement-scalar-negotiation-participation-is-a-mechanism-declaration` | Permanent, promoted |
| Payments contract identified by content, not source repository | `kit/arkhai-payments/schema/SOURCE.md`; `openspec/specs/market-composition/spec.md#requirement-arkhai-payments-authority-remains-external`; `docs/development/TESTING.md#private-service-dependencies` | Permanent, promoted |
| Goal 6 gap table after cross-compute contact exchange and retention | `docs/development/ROADMAP.md#goal-6--make-the-settlement-mechanism-a-composed-choice` | Updated: one table; contact-exchange and delivery-beyond-bare-metal rows closed, second delivery event producer retained |
| End-to-end lease lookups follow the negotiation | `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py` (`SiteCapacity.reservations_for_negotiation`) | Permanent, promoted: the reservation keying is in `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-full-settlement-convergence-ownership`; the lookup is test-local |
