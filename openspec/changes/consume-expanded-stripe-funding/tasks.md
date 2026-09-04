## Completed behavior

- [x] 1.2–1.3 — Pin, install, package, and verify the exact released hosted client `0.2.0` through `kit/hosted-settlement`, repository wheelhouse/reinit flows, and client-only package boundaries; no marketplace core/domain package imports the hosted client directly or receives hosted service/provider implementation.
- [x] 2.1–2.5 — Register strict `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1` clauses; fail closed on release/authority/profile/currency/country/interaction mismatch; publish one deterministic option per independently ready profile while preserving Alkahest alternatives.
- [x] 3.1–3.5 — Compose `market settlement stripe payer` through provider-neutral kit façades and selected/historical buyer signers; atomically persist only authority/environment, opaque payer binding, bound principal, and safe lifecycle state; keep setup/instrument actions transient and redacted.
- [x] 4.1–4.5 — Implement exact accepted-obligation authorization and disabled-by-default bounded saved-instrument automation with owner-only aggregate reservations, same-operation action fallback, conflict-safe retries, and no pre-acceptance funding/escrow effect.
- [x] 5.1–5.5 — Cut VM publication, buyer start/poll/resume, and storefront routes over to accepted negotiation/obligation identity plus safe authorization reference; reload all commercial, party, condition, expiry, and provision inputs from seller-accepted state; persist only safe public projections.
- [x] 6.1–6.6 — Extend the common runtime and hosted adapter for immutable profile/authorization inputs, authoritative funding gates, journaled cleanup/fulfillment/collect/reclaim exclusion, returns/loss/manual review, exact retry/restart, and recovery-only historical card decoding. The buyer profile-store schema-1 binding already owns the complete safe consumer projection and needs no schema migration; the settlement database owns the hosted recovery migration.
- [x] 7.1–7.3 — Cut committed config, migration, role templates, Compose/Helm surfaces, package/release verification, and independent producer/consumer artifact attribution over to API `0.2.0`, schema `5`, exact profiles, profile stores, bounded automation, and role-scoped signer Secrets.
- [x] 8.1–8.4 — Expand credential-free suites and the protected driver/report schemas for exact profiles, payer fixtures, same-operation actions, delayed/restart/reclaim/return/loss scenarios, prerequisite gating, independent release identities, and recursive secret/provider/action/source-path canaries.

## Permanent destinations

- [x] 9.1–9.5 — Promote the resulting contracts and rationale to `openspec/specs/{settlement-configuration,storefront-publication,buyer-orchestration,settlement-servicing,market-composition,deployment-state,test-compatibility}/{spec,architecture}.md`, `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG,TESTING,ROADMAP}.md`, and applicable VM buyer/seller/operator documentation. The design-promotion record names exact permanent headings, and the roadmap records the completed VM consumer plus remaining API-credit/bare-metal adopters.

## Validation evidence

- Hosted-settlement kit: `143 passed`.
- Common settlement runtime: `59 passed`.
- Core buyer: `91 passed` with one pre-existing serializer warning.
- Core storefront: `118 passed`.
- Config kit: `128 passed` with one unknown `asyncio_mode` warning.
- VM buyer full suite: `195 passed`.
- VM migration suites: `22 passed`.
- Listing integration and CSV importer: `43 passed` with one pre-existing `agent_id` default warning.
- Hosted routes: `9 passed`; seller-round hook: `8 passed` with one pre-existing `agent_id` warning.
- VM storefront after pool integration: `1054 passed, 1 skipped, 2 warnings`; focused listing immutability: `1 passed`.
- Pool/resource integration: resource-pool kit `94 passed`; site kit `149 passed`; fulfillment kit `154 passed`; provisioning service `655 passed` with six pre-existing deprecation warnings.
- Release/package scripts: `66 passed`; Helm schema/render checks passed; targeted changed-file Ruff checks passed. Upgraded VM storefront, VM operator-client, and bare-metal adapter dependency floors/locks resolve the released pool/site/fulfillment/compute contracts; both leaf packages import successfully.
- [x] 10.1 — Post-integration marketplace aggregates and package/typing-boundary suites pass. The repository defines no VM-storefront typecheck target; an exploratory whole-source mypy invocation reports 319 baseline diagnostics, predominantly missing `py.typed` markers, rather than a usable release gate.
- Both `consume-expanded-stripe-funding` and `pool-declared-offering-modes` pass strict OpenSpec validation.
- `make check-comment-hygiene` passed; direct review found no temporary change/task commentary or newly added local imports, and no core/domain direct hosted-client import or public legacy alias remains.

## Deferred and external evidence

- [ ] 1.1 — Verify one complete signed producer release and record its exact manifest/client/service/image/API/schema/migration/capability/repository/workflow/provenance/source identities. **Blocked:** local producer output has the public client `0.2.0`, OpenAPI `0.2.0`, conformance/schema `5`, and migrations `v5`, but not a complete signed release-v2 manifest matching the committed trust pin, immutable service image/digest, service wheel/SBOM/provenance set, or workflow-attested repository/run/source identities. Sibling source is not evidence.
- [ ] 7.4 — Exercise activation and rollback with matching old/new producer and consumer artifact sets. Deterministic config/package/wheelhouse/Compose/Helm/secret/rollback fixtures pass, but the staged artifact exercise requires the complete signed set blocked in 1.1.
- [ ] 10.2 — Run the protected hosted Stripe profile matrix and preserve the signed sanitized report. **Blocked:** no complete signed staged producer/consumer artifact pair or protected Stripe test-mode rail/account/browser credentials and connectivity are available; local simulation cannot substitute for those assertions.

## Closeout

- [x] 10.3 — Strict change validation, permanent documentation/index/link placement, generated release/deployment surfaces, package/import/provider boundaries, exact profile callsites, and stale-pin/legacy-alias audits are reconciled.
- [x] 10.4 — Comment hygiene and direct Python comment/docstring/import review pass; accepted decisions are promoted to permanent specifications and architecture, durable rationale remains in `design.md`, roadmap state and the design-promotion record are current, and completed history is compressed here to final behavior, evidence, permanent destinations, and exact deferred prerequisites.
- [ ] 10.5 **Campaign index currency** (part seven, added when `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven). Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend rather than replace implementation history. This change has no row in `openspec/changes/README.md`; add one under the campaign that owns it with its status and acceptance boundary, or record here why it stands outside every campaign.
