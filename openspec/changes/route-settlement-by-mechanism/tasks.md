# Tasks

Final implementation and post-review closeout checklist. Completed task IDs and
ownership are retained; detailed implementation/review history is in Git and
[final joined evidence](../../../docs/attachments/route-settlement-closeout/final.md).
No escrow-carrier/runtime extraction or public listing/registry wire cutover is
included. Sections 1–9 are complete; section 10 reconciles the change with the merged development branch.

## 1. Shared core and buyer dispatch

Owner: core. Files: `market_core/{settlement,domain_contract,domain_conformance}`,
`core_buyer/{orchestration,negotiation_client,settlement,deal_helpers}` and
`core_storefront/domain_lifecycle` with their existing suites.

- [x] 1.1 Export immutable dependency-light role tables and opaque evidence; carrier/domain/import suites and typing pass.
- [x] 1.2 Require matching role tables at domain composition without universal verify/build-plan methods; explicit escrow callbacks remain helpers.
- [x] 1.3 Dispatch the exact accepted Agreement through its declared buyer entry; no proposal-presence or escrow default.
- [x] 1.4 Entry-owned acceptance validates mechanism artifacts; fresh compatibility intersects supported buyer entries.
- [x] 1.5 Storefront lifecycle carries evidence/reference continuity. Buyer recovery retains references and exact accepted state, not unused SettlementEvidence plumbing; public DTOs remain unchanged.
- [x] 1.6 Rebuild/reinstall consumers; carrier exports, `py.typed`, dependency direction and core typing pass.
- [x] 1.7 Promote core/buyer contracts to market-composition, buyer-orchestration and repository architecture; touched comments/imports and placement checked.

Final carrier/boundary group 26, buyer 51, storefront 24; core mypy 6 files.
Setup: `docs/attachments/core-dispatch/` and `core-settlement-closeout/`.

## 2. VM buyer and storefront

Owner: VM. Buyer composition/stages/CLI/recovery and storefront
composition/stages/controller/runtime/publication, evidence repository,
introducing migrations, planner, physical delivery and resume runtime.

- [x] 2.1 One buyer table governs buy/settle/recovery and standalone negotiate; resources resolve through selected-stage hooks.
- [x] 2.2 Seller entry hooks own accepted artifacts, guards, resources/readiness/publication and settlement. Fresh acceptance requires explicit selection; recovery uses exact Agreement/proposal.
- [x] 2.3 Negotiation-keyed evidence and independent delivery context/checkpoints/claims replace payment escrow progress. Verified facts are validated and conflict-protected; established-reference conflicts return 409.
- [x] 2.4 Common planner/delivery/resume consume validated evidence; selected entries own source revalidation, attestation/claim binding and failure policy.
- [x] 2.5 Rebuilt buyer/storefront wheels and controlled pending/0 → provisioning → ready/1 replay pass with zero payment escrows; accepted-run CLI retains operation identity.
- [x] 2.6 Promote VM contracts/reset and physical payment boundary to VM fulfillment and physical-provisioning specs/companions; buyer and repository boundaries match repaired code. Comments/imports checked.

Final expanded buyer/storefront groups 105/270. Setup and reset:
`docs/attachments/vm-settlement-findings/` and VM evidence packets; permanent
`vm-storefront-fulfillment/architecture.md`.

## 3. Bare-metal buyer and storefront

Owner: bare-metal buyer/storefront composition/stages, SQLite/migrations,
settlement and physical/contact services.

- [x] 3.1 Purchase declares payment support; buyer suite and installed contract/six-codec conformance pass.
- [x] 3.2 Seller declares Alkahest/payment/fused contact; hooks own acceptance/resources/settlement.
- [x] 3.3 Versioned Agreement-bound evidence is separate from escrow/lifecycle state; no chain sentinel fallback. Lifecycle references are neutral; public DTOs remain unchanged.
- [x] 3.4 Common physical begin/status/result/access/teardown consume verified evidence through selected-entry revalidation; Alkahest recovery rechecks active journal plus chain source/index.
- [x] 3.5 Enabled-contact reveal/auth/retention/delivery, installed wheels and controlled physical recovery pass. Disabled-contact accepted re-read is the B2 gap in 8.2.
- [x] 3.6 Promote table/evidence/selected-site gating/reset into physical-provisioning and market-composition architecture; comments/imports/placement checked.

15-file storefront group 90; buyer 9. Setup:
`docs/attachments/baremetal-dispatch/` and `baremetal-recovery-gate/`. Live
selected-site hardware/payment complete deal remains unavailable.

## 4. API-credit buyer and storefront

Owner: API-credit buyer/storefront tables/stages/CLI, controller/runtime,
evidence/progress repositories and common issuance; consumes section 5 DTO.

- [x] 4.1 Buy and accepted-run settlement bind selected Alkahest/payment buyer entries. Standalone credits negotiate is the B1 gap in 8.2.
- [x] 4.2 Seller entries own Agreement dispatch, payer/mandate/hold hooks and readiness/publication/client construction.
- [x] 4.3 Source evidence and issuance progress are independent of real escrow servicing, signed issuance and private results. Verified status/payload cannot be downgraded; stored receipt recovery survives unavailable polling.
- [x] 4.4 Common issuance consumes evidence/neutral authorization and entry-supplied retry policy; entries own attestation/compensation. Prepared Alkahest delivery does not repeat preparation inside terminal-failure handling.
- [x] 4.5 Real typed-credit HTTP/SQLite first use: pending0/lost-ack1/final2 grants, balance5, private owner retrieval, zero payment escrows and cleanup.
- [x] 4.6 Promote table/evidence/progress/continuation/reset into API-credit spec and payment/failure architecture; focused suites, comment/import checks and placement pass.

Expanded storefront selections cover 64 cases; buyer 17, client/domain 25.
Setup: `docs/attachments/apicredits-dispatch/` and `apicredits-settlement-repair/`.

## 5. API-credits service and typed authorization

Owner: `settlement/credits_client.py`, service models/controllers/keys service,
database/migrations and declared dev-client wheel installation.

- [x] 5.1 Client/service neutral authorization binds negotiation-derived fulfillment, canonical owner, service/resource, quantity, key target/digest and optional operational hold; old payloads rejected, sync/async parity retained.
- [x] 5.2 Exact grant replay, authoritative quota/key checks, unused-key secret rotation and no secret after consumption hold; no mechanism allowlist or historical grant adoption.
- [x] 5.3 Fresh/rerun/drift grant schema has unique negotiation/fulfillment and no settlement columns; no copy-then-drop migration.
- [x] 5.4 Rebuilt/reinstalled producer/authority consumers and typed HTTP issuance/replay pass; setup and cleanup are committed.
- [x] 5.5 Promote storefront-only settlement authority, neutral authorization/uniform grant replay and separate signed issuance into API-credit spec/authority/idempotency architecture; reset documented.

Service group 35, client/domain 25, isolated real typed-client HTTP 3. Setup:
`docs/attachments/credits-service-auth/`. Quota-ledger escrow correlation rename
belongs to `move-escrow-into-alkahest/proposal.md`; dev wheel closure is #262.

## 6. Evidence-storage contract across domains

Domain-owned repositories; no shared database/framework.

- [x] 6.1 Confirm negotiation-keyed Agreement-bound versioned evidence, immutable verified facts/references and separate progress/context/claims/private state. Fresh-schema diagnostics and named storage slices pass; malformed VM verified write now refuses.
- [x] 6.2 Confirm all 14 original E sites plus gate map are evidence/authorization readers; selected-stage source revalidation precedes protected physical/issuance recovery. Reclaimed Alkahest diagnostic refuses; pseudo-escrow handoffs removed.
- [x] 6.3 Promote explicit reset in all three architecture companions; committed entries use owned temporary databases. No new compatibility copy/adopt/drop, sentinel or payment-progress escrow write; comments/imports checked.
- [x] Bare-metal storage (6.1): fresh SQL and migration/persistence suites pass.
- [x] Bare-metal recovery gates (6.2): active journal plus authoritative chain/receipt gate before physical effects; one durable identity.
- [x] Bare-metal storage closeout (6.3): reset/current-schema instructions and permanent destinations recorded.

Storage slices VM12/bare-metal6/credit-storefront14/credits-service13; repeated
measurements, not additive coverage. Evidence: final joined packet.

## 7. Opt-in convention boundary

- [x] 7.1 Promote optional convention ownership to market-composition and settlement-configuration companions: future kit home chosen on first implementation, no mandatory contact/seller-first/fused adapter. Extraction deferred; no speculative module/dependency.
- [x] 7.2 Existing core purity, VM architecture and bare-metal import suites pass; entries use their own kit APIs, not a shared mechanism protocol.

## 9. Payment end-to-end coverage

- [x] 9.1 Typed payments-client doubles and published conformance vectors pass. Complete live payment scenarios are qualified by the payments service's own end-to-end tests, which import this repository's published packages; public CI requires no payments credentials or service.

## 8. Joined validation and plan closeout

Owner: joined post-review closeout. Exact commands/counts/readiness/limits are in
`docs/attachments/route-settlement-closeout/final.md` and final-inventory.md.

- [x] 8.1 Clean `make dist`, consuming reinit, all original named suites and four repair-worker entries pass. Original primary groups 680; expanded selections cover 723 distinct cases. Integration slices30/25/4/3, storage12/6/14/13, four payment vectors, generated models and core/payment typing pass.
- [x] 8.2 Full ID/proposal/config-key and generic control-flow inventory: no common delivery/authority switch remains. Its two failures were repaired with production-surface tests that fail on the prior code: B1 `market credits negotiate` dispatches through the buyer table and negotiates payment-only wallet-free (23 buyer tests, `docs/attachments/apicredits-negotiate/`); B2 accepted contact reveal/re-read resolves the stored Agreement's seller entry with contact disabled while fresh contact stays refused (6 + 53 tests, `docs/attachments/contact-disablement/`).
- [x] 8.3 VM/credit controlled first use, actual accepted-run CLI and bare-metal HTTP recovery/contact replays pass and clean owned state. No owned ready live target supplied; VM/API-credit/bare-metal complete-deal deployment lanes remain unavailable, not qualified.
- [x] 8.4 Comment hygiene passes; directly read added/touched comments/docstrings, removed provenance wording, no production dependency on active change docs.
- [x] 8.5 Added/touched local imports reviewed. API-credit imports moved and real suites pass; two VM cycles reproduced against actual imports/wheels, publication operator-config load deliberately lazy with local reasons.
- [x] 8.6 Six capability deltas synchronized; existing companions/repository architecture promoted and current limits disclosed. Tasks/design compressed with baseline inventory and detailed evidence retained in attachments; no new companion/index edit needed.
- [x] 8.7 Goal6 and active change status reflect repaired core/evidence boundaries and precise B1/B2 blockers while retaining carrier/wire/live gaps. Promotion record complete; residuals owned by move-escrow proposal and GitHub ideas #261/#262. Strict change/spec validation passes. Archive with `--skip-specs` after review; specs were promoted directly.

## 10. Post-merge reconciliation

Owner: joined post-merge closeout on the tree that merged the development
branch's bare-metal provisioned-deal and dead-surface work. Decisions are in
`design.md#post-merge-reconciliation`.

- [ ] 10.1 Bare-metal obligation servicing through seller entries. Files:
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{settlement_stages,settlement_composition,alkahest_lifecycle,runtime}.py`
  and tests. Add the optional entry servicing factory and continuation
  protocol; Alkahest builds its lifecycle when its section is configured,
  contact exchange declines, payments declares none. Runtime hooks resolve the
  entry from the accepted Agreement, refuse a mismatched obligation mechanism
  and a missing servicing before effects, and no longer compare mechanism IDs
  or build an Alkahest lifecycle themselves. Focused routing tests with a fake
  table; existing restart-recovery and Alkahest lifecycle integration suites.
- [ ] 10.2 Standalone credits negotiation integration (B1). Add the API-credit
  buyer to the API-credit storefront's development dependencies (lock refreshed
  through `scripts/uv_project.py`) and an integration test that runs the real
  `market credits negotiate` command against the served storefront for a
  payment-only, wallet-free negotiation and its accepted state.
- [ ] 10.3 Accepted contact reveal after disablement through the production
  clients (B2). Rewrite the successful negotiation, reveal and read in
  `test_accepted_introduction_survives_contact_disable` onto `StorefrontClient`
  and `IntroductionTransport` against a served app; keep the disabled-restart
  persistence assertions.
- [ ] 10.4 Public-repository discipline. Remove private repository names,
  commits, planning-document paths and private test-target names from this
  change, its attachments, the payments kit (`schema/SOURCE.md`, generator and
  generated models header, schema `$id` with its recorded SHA-256), permanent
  documents (`docs/development/TESTING.md`,
  `openspec/specs/market-composition/spec.md`) and the change documents that
  repeat them; identify the contract by content.
- [ ] 10.5 Regenerate joined validation on the merged tree: replace
  `docs/attachments/route-settlement-closeout/replay*.sh` and the pre-merge
  counts with a validation record naming `make` targets and this change's
  regression tests, and reconcile `final.md`, `final-inventory.md`, `index.md`
  and `design.md` to the repaired B1/B2 state.
- [ ] 10.6 Promote the servicing rule (physical-provisioning, market-composition)
  and the content-identified payments contract; reconcile Goal 6's gap table.
- [ ] 10.7 Closeout per `openspec/README.md#plan-closeout-requirements`: comment
  hygiene; import placement for touched imports; documentation compliance;
  narrative compression of this section; roadmap currency (Goal 6); campaign
  index currency (`openspec/changes/README.md` row); `make check-doc-citations
  CHANGE=route-settlement-by-mechanism`; `make check-packaging`; end-to-end
  pipeline run recorded with its scenarios (or an explicit blocker naming its
  owner); design promotion record complete.
