# Implementation Tasks

## 1. Move escrow semantics into `alkahest.v1` (deferred)

Deferred: existing escrow carriers and `kit/settlement-runtime` remain shared by Alkahest/contact exchange. Arkhai payments bypasses them without a plan or obligation. Follow-up disposition is in `design.md#closeout-disposition`.

## 2. Emit one explicit Agreement from negotiation

Dependency: Section 2 uses the existing `SettlementOption` (mechanism, option id, asset, rates, opaque params) as the Agreement's settlement section. Section 3 depends on this section's exact Agreement bytes.

- [x] 2.1 Add the Agreement wire model in `core/src/market_core/schemas.py` with negotiation/listing identity, canonical buyer and seller principals, exact selected settlement option and parameters, accepted amount/asset/duration, explicit `start_utc`, domain provision terms, and `accepted_at`.
  Exact option, accepted terms, and UTC timestamps; legacy Alkahest-only selection remains optional. Contract: `openspec/specs/negotiation-protocol/spec.md`.
- [x] 2.2 Update the acceptance chokepoint and response construction in `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py` to emit one Agreement containing accepted terms only. Resolve “now” to an explicit start at acceptance and preserve the exact serialized bytes for both parties; do not rebuild the object from negotiation history.
  Acceptance fixes timestamps once; injected builders emit exact persisted bytes retained on buyer resume. Contract: `openspec/specs/negotiation-protocol/spec.md`.
- [x] 2.3 Update domain agreement/provision-term builders and persistence at `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`, `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_service.py`, and `domains/apicredits/storefront/src/apicredits_storefront/negotiation_runtime.py`. Update existing negotiation/runtime and buyer-client tests, including `kit/negotiation-runtime/tests/unit/test_runtime.py`, `domains/vms/buyer/tests/test_buyer_client.py`, `domains/bare_metal/storefront/tests/test_negotiation.py`, and `domains/apicredits/buyer/tests/test_negotiation_flow.py`.
  All three adapters persist Agreements; Agreement-only mechanisms omit plans/expiry. Legacy Alkahest carrier changes remain deferred §1.

## 3. Add Arkhai payments, remove hosted Stripe, and wire domain stages

Dependency: exact Agreement bytes from Section 2.

- [x] 3.1 Add `kit/arkhai-payments` as a stateless `arkhai.payments.v1` client over the published `arkhai-io/arkhai-payments/schema/payments.schema.json` contract. Generate Python wire models from that schema; use RFC 8785 JCS for Agreement and mandate hashes. Implement seller mandate derivation, buyer policy validation/approval with owner-scoped WorkOS credentials, optional Agreement attachment, polling by transaction ID, Ed25519 receipt verification using the `arkhai.payments.receipt.v1` identity framing, seller-side `reverse`, and retries that preserve transaction identity. Keep transaction servicing state and any daemon in the payments service, not this kit. Extend existing package/release and typing checks for the new kit.
  Generated contract/vectors, stateless mandate/receipt client, typed registration/config/provider, and release/typing integration. Kit checks: 7 tests, vectors, generated models, typing. Contracts: settlement configuration and servicing specs.
- [x] 3.2 Remove `fiat.stripe.v1`, `kit/hosted-settlement`, and Stripe funding, setup, and recovery configuration. Delete `kit/hosted-settlement/**`, remove hosted-specific `kit/settlement-runtime/src/market_settlement_runtime/hosted_routes.py` behavior, registrations, routes, commands, dependencies, locks, and fixtures. Do not map old Stripe settings, funding profiles, operation IDs, or credentials to Arkhai payments.
  Stripe package, routes, config, commands, dependencies, and fixtures removed; legacy settings rejected, never converted. 2,251 regressions pass (one skipped), 42-source typing and wheels/CLI/Helm checks pass. Contact exchange retained. Hosted-doc cleanup promoted to permanent specs/index and guides in §4; provenance and remaining qualification are in `design.md#closeout-disposition`.
- [x] 3.3 Compose negotiation → settle → provision in VM buyer/storefront roots. Replace hosted/Stripe wiring in `domains/vms/buyer/{settlement_composition.py,hosted_authorization.py,settle_cli.py,buy_cli.py}` and `domains/vms/storefront/src/market_storefront/{settlement_composition.py,hosted_routes.py,hosted_evidence.py}` with `arkhai.payments.v1`; retain Alkahest as a peer. Gate VM provisioning on the matching signed receipt. Update existing VM buyer/storefront regressions and `domains/vms/{buyer,storefront}/pyproject.toml` plus locks.
  Exact Agreement approval and signed receipts gate selected-site fulfillment/recovery; Alkahest remains a peer. Checks: buyer 180; storefront unit 895 (one skipped), integration 152; wheels. Controlled smoke: pending → provisioning → ready, one delivery; no live-ledger/hardware claim. Contracts: settlement servicing and physical provisioning.
- [x] 3.4 Compose the same stage boundary for bare metal. Replace hosted wiring in `domains/bare_metal/src/arkhai_bare_metal/{hosted_contract.py,hosted_publication.py}` and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{settlement_composition.py,hosted_routes.py,hosted_lifecycle.py,hosted_binding.py,settlement.py}`; remove buyer funding commands from `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/{funding.py,cli.py}`. Keep selected-site provisioning gated on matching settlement evidence. Update existing bare-metal regressions, `domains/bare_metal/{pyproject.toml,storefront/pyproject.toml,buyer/pyproject.toml}`, and locks.
  Negotiation-only settlement verifies the signed receipt before selected-site fulfillment. Schema-only domain stays payment-opaque. Checks: buyer 9, storefront 92, wheels/Ruff/comment hygiene pass; no payment-service smoke. Contract: physical provisioning.
- [x] 3.5 Compose the API-credit payment stage: publish and select `arkhai.payments.v1` alongside Alkahest; persist the seller-derived mandate in the shared negotiation `settlement_data`; have the buyer approve and poll, then submit only the negotiation ID; verify the seller-side signed receipt before recoverable, idempotent credit issuance and credential delivery. Preserve Alkahest and allow payments without chain or wallet configuration. Widen the credits-service issuance mechanism contract and update existing API-credit regressions, dependencies, and locks.
  Payment receipt gates recoverable, idempotent issuance and private credentials. Checks: buyer 17, storefront 70, domain 35, service 32; core buyer 111, storefront 149 (two skipped), negotiation-runtime 7; Ruff/compile/locks pass. Runtime E2E unavailable: payments service down. Contracts: API credits and buyer orchestration.

## 4. Verify, promote, and close out

- [x] 4.0 Converge bare metal's and VMs' stored Arkhai mandate (VM adds its own payment-evidence table) onto the shared `settlement_data` persistence in `negotiation_threads` (landed with API credits), so every domain loads the mandate by negotiation id from one place.
  Storage: the original domain evidence-table definitions omit mandate columns; both tables are new on this unmerged branch, so no transfer/drop migration is needed. Domain-owned receipt and provisioning evidence remains. Rebuild, both storefront suites, Ruff and comment hygiene pass after this correction; fresh bootstrap and reopen preserve receipt columns with no duplicate mandate column or transfer migration.
- [x] 4.1 Run focused existing core-schema, Alkahest, negotiation-runtime, payments-kit, and per-domain regressions; run the relevant package, integration, packaging, and typing checks. Do not add new permanent acceptance tests in this implementation lane; record driver observations for reviewer-owned acceptance coverage.
  Core/kit/domain suites pass; counts, replay setup and evidence: `docs/attachments/settle-through-arkhai-payments/index.md`. Bare-metal and API-credit real Formance approval/poll/receipt/restart/retry smokes pass; physical providers controlled, credits authority real (one grant after lost acknowledgement). Two domain comparison defects repaired. VM mypy matches baseline 353776c3: 52 pre-existing findings in 22 files, zero introduced. 38 portable wheels, 80 release checks and Helm structural checks pass. Registry 95 unit/87 integration pass; one-line 204 compatibility repair also passes 87 under FastAPI 0.115.8.
- [x] 4.2 Validate the completed change with `openspec validate settle-through-arkhai-payments` and run `make check-comment-hygiene`.
  Strict change validation, strict validation of all permanent specs, and comment hygiene pass. Scenario headings aligned between promoted specs and deltas; archive preview notes already-promoted ADDED requirements.
- [x] 4.3 Review every changed local import against the section diff; move it to module scope where safe, and verify candidates with the real relevant suite. Re-check the accepted decisions against `AGENTS.md` and the owning architecture/specification documents.
  All 13 introduced local-import candidates moved safely; relevant suites pass. Accepted decisions compared with promotion e97b4b7a; exact Agreement enumeration and credit grant/gate wording corrected in owning specs. Comparison: `docs/attachments/settle-through-arkhai-payments/decision-review.md`. API-credit domain-local payment configuration mismatch was recorded in SCM #254 and is reconciled in §4.6; not a missing promotion.
- [x] 4.4 Promote the pipeline and shared-reader rule to `docs/development/ARCHITECTURE.md`; promote current behavior to `openspec/specs/settlement-configuration/spec.md`, `openspec/specs/settlement-servicing/spec.md`, `openspec/specs/negotiation-protocol/spec.md`, `openspec/specs/market-composition/spec.md`, and the selected-site receipt gate to `openspec/specs/physical-provisioning/spec.md`. Record each destination in the design-promotion record.
  Promoted §2–§3 and final domain decisions directly to owning permanent contracts; all 18 hosted spec/index destinations and adjacent companions/guides describe current payment composition. Deferred §1 assertions remain unpromoted; destinations are in `design.md#design-promotion-record`.
- [x] 4.5 Update Goal 6 in `docs/development/ROADMAP.md` to describe Arkhai payments as the current peer mechanism and `fiat.stripe.v1` as removed. Compress completed task notes to final behavior, validation evidence, unresolved work, and promotion destinations; complete the design-promotion record.
  Goal 6, related Goal 4/qualification gaps, and active-change index are current. Completed §1–§3 notes compressed; provenance and evidence limits retained in design. §4.0/4.1/4.3 notes untouched.
- [x] 4.6 Reconcile API-credit configuration with the shared payments kit (SCM #254): remove local config/registration/auth provision from `domains/apicredits/settlement/payments.py` and its exports; use the shared registration in buyer/storefront roots and owner-scoped clients in payment stages. Update buyer payer-account inputs, operator TOML, existing regressions and `docs/attachments/settle-through-arkhai-payments/api_credit_smoke.py`. Preserve base-unit pricing through the shared generic unit-rate builder; keep credit/token/request vocabulary in the API-credit adapter. Rebuild wheels and run API-credit buyer/storefront/domain/service and payments-kit suites.
  Shared registry/config/client helper replaces the local surface without shims. Buyer payer input and accepted seller owner stay separate from service policy. Checks: buyer 17, storefront 70, domain 35, service 32, kit 7; kit typing/vectors/generated models pass. Evidence and runnable configuration first use: `docs/attachments/settle-through-arkhai-payments/index.md#api-credit-shared-configuration-254`. Real-ledger phases updated, not rerun.
- [x] 4.7 Close out SCM #254: run Ruff on touched files, comment hygiene and strict change validation; check introduced imports and permanent configuration docs, record evidence and promotion, and compress final task notes. No roadmap change: this restores the already-promoted shared-kit boundary without changing Goal 6.
  Ruff correctness/import checks, comment hygiene and strict validation pass; no new local imports. Permanent destinations: settlement-configuration spec/architecture and deployment/config guide; promotion record updated. Recovery import shadowing and canonical publication booleans repaired separately; existing assertions retained.

## 5. Review round: one payments mechanism, agreement settlement, seller refunds

Decisions: `design.md#review-round-decisions` (R1–R10) and `design.md#planning-findings` (P1–P6). This section runs on this branch before the merge; §6 runs on the merged tree.

Dependencies:
- 5.1 comes first; every other task consumes it.
- 5.2 precedes the domain tasks 5.3–5.5, which are independent of each other.
- 5.6 needs 5.3 and 5.5.
- 5.7 needs 5.2–5.6.

No compatibility shims: the settlement-data shape, settle response fields, and client method names change directly on this unmerged branch.

- [x] 5.1 **Payments kit: one mechanism implementation** (R2, R4, R5, R7, P4, P5).
  - Final: `kit/arkhai-payments/src/market_arkhai_payments/` is the one payments implementation: mandate policy and `PaymentSettlementData` from the Agreement, the seller stage (receipt outcomes, deposit before delivery, reversal), buyer `PaymentApproval` with the `attach_agreement` policy, and the receipt fixture and `FakePaymentsClient` for consumers' tests.
  - Evidence: kit `make test` (typing, vectors, generated models, unit), including `kit/arkhai-payments/tests/test_receipt_fixture.py`'s byte-exact vector.
  - Destination: `openspec/specs/settlement-servicing/spec.md` and its `architecture.md`.

- [x] 5.2 **Core carriers and the typed client** (R1, R4, R7).
  - Final: `StorefrontClient` and `SyncStorefrontClient` have `settle_evm`, `settle_agreement`, and `refund_settlement`, built from the settlement route contract; the core response models are strict.
  - Evidence: `core/storefront-client/tests/test_settlement_requests.py` (async and sync) and `domains/vms/storefront/tests/unit/test_storefront_client_parity.py`.
  - Destination: `openspec/specs/buyer-orchestration/spec.md`.

- [x] 5.3 **VM** (R2, R4, R5, R7, R8, P4, P6).
  - Final: the VM storefront settles payment deals through the kit stage (receipt outcomes mapped to 202/409/500/503, deposit before delivery, seller refunds, and the mechanism-dispatched `refund` failure action); the VM buyer approves through `PaymentApproval`.
  - Evidence: `domains/vms/storefront/tests/integration/test_payment_settlement.py` through the typed client with the real app, and the VM storefront and buyer suites.
  - Destinations: `openspec/specs/settlement-servicing/spec.md`, `openspec/specs/physical-provisioning/spec.md`.

- [x] 5.4 **Bare metal** (R2, R4, R5, R6, R7, P3).
  - Final: a verified payment receipt starts bare-metal fulfillment (R6); refunds use the shared route, and the settlement record admits `refunded` and `refunding`. The buyer approves through `PaymentApproval` and polls fulfillment without a `begin` call.
  - Evidence: `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py` and the bare-metal storefront and buyer suites.
  - Destination: `openspec/specs/physical-provisioning/spec.md`.

- [x] 5.5 **API credits** (R2, R4, R5, R7, R8, P5, P6).
  - Final: `domains/apicredits/storefront/src/apicredits_storefront/services/payment_settlement_service.py` owns payment settlement (receipt-gated issuance, deposit before issuance, refunds); the controller is a thin binding, and the `refund` failure action dispatches on the mechanism.
  - Evidence: `domains/apicredits/storefront/tests/integration/test_payment_settlement.py` and the API-credit domain, storefront, buyer, and service suites.
  - Destination: `openspec/specs/api-credits/spec.md`.

- [x] 5.6 **API-credit payment system scenario** (R3, R7).
  - Final: `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py` covers publication through seller refund against a configured payments target, under marker `e2e_credits_payment_deal`.
  - Evidence: the e2e unit suite; without a payments target the scenario reports the unmet prerequisite. Live qualification belongs to the payments service's end-to-end tests.

- [x] 5.7 **Diagnostics, comments, and the gate** (R3, R10, P2).
  - Final: the smoke diagnostics in `docs/attachments/settle-through-arkhai-payments/` use the kit stage, approval, and fixture; the core carrier docstrings describe current behavior (R10).
  - Evidence: the gate as recorded in 6.3, including `make check-packaging`.

### Implementation review round

Decisions: `design.md#implementation-review-decisions` (R11–R17).

- [x] 5.8 **Kit: servicing from the accepted artifact** (R11).
  - Final: accepted deals are serviced from their stored mandate (R11). Changing fee policy or dispute authority, or disabling payments publication, leaves accepted deals serviceable.
  - Evidence: `kit/arkhai-payments/tests/test_agreement.py` and `test_seller.py`.

- [x] 5.9 **Kit: operator-action outcomes and reversal completion** (R12, R13).
  - Final: `ReceiptBlocked` and `RefundBlocked` classify the seller's integration faults (R13); reversal completes only when the snapshot shows every part reversed (R12).
  - Evidence: `kit/arkhai-payments/tests/test_seller.py`, one case per R13 row.

- [x] 5.10 **Kit: attachments and approval** (R15, R16).
  - Final: every Agreement attachment must match the deal (R15), and approval checks only mechanism facts; the advertised option is bound at acceptance (R16).
  - Evidence: `kit/arkhai-payments/tests/test_client.py` and `test_buyer.py`.

- [x] 5.11 **Core: ordered transitions and strict responses** (R12, R14).
  - Final: delivery start and refund intent are single-statement compare-and-set transitions (R12); agreement-settlement and refund responses are strict (R14).
  - Evidence: `core/storefront/tests/unit/test_sqlite_client_escrow_fulfillment_identity.py` and `core/storefront-client/tests/test_settlement_requests.py`.

- [x] 5.12 **VM** (R11–R14).
  - Final: VM claims delivery start before fulfilling, records refund intent before reversing, services accepted deals regardless of publication, and answers blocked faults with 500.
  - Evidence: `domains/vms/storefront/tests/integration/test_payment_settlement.py` (configuration changes after acceptance, refund and delivery races, restart reconciliation).

- [x] 5.13 **Bare metal** (R11–R14).
  - Final: bare metal starts a payment deal's lifecycle only while its record is `settlement_verified`, records refund intent before reversing, and validates payloads through the core models.
  - Evidence: `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py`.

- [x] 5.14 **API credits** (R11–R14, R16).
  - Final: API credits replaces its in-process lock with the ordered transitions, answers blocked faults with 500, and completes `refunding` deals; the buyer no longer passes an advertised option.
  - Evidence: `domains/apicredits/storefront/tests/integration/test_payment_settlement.py` (payments disabled after acceptance, both race orders, restart reconciliation).

- [x] 5.15 **Scenario wording** (review finding 8). `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py`: the second stage is idempotent re-drive from the buyer's run log, named and documented as such; task 5.6's text says the same.

- [x] 5.16 **Gate.** Rerun every suite from 5.1–5.7 plus the new cases in fresh environments, `make dist`, the packaging comparison against the baseline (P2), pyflakes over changed source plus the VM storefront and e2e ruff configurations, and `make check-comment-hygiene`.

### §5 evidence

Every suite below ran in a fresh environment against a wheelhouse rebuilt from the final tree.

| Suite | Result |
|---|---|
| `kit/arkhai-payments` (`make test`: mypy, vectors, generated models, unit) | 63 passed |
| `core/storefront-client` | 34 passed |
| `core/storefront` | 149 passed, 2 skipped |
| `kit/capacity-publication` | 8 passed |
| VM storefront (unit and integration) | 1,058 passed; 3 deselected, which fail identically on the unmodified tree (`test_alkahest` ×2 need the local chain runtime; one Alkahest amountless-escrow negotiation) |
| VM buyer | 180 passed |
| Bare-metal storefront | 95 passed |
| Bare-metal buyer | 9 passed |
| API-credit domain / storefront / buyer / credits service | 35 / 75 / 17 / 32 passed |
| e2e unit, and the payment scenario without a target | 19 passed; the scenario's 3 stages report blocked |

Packaging (P2): measured against the unmodified-tree baseline, `check-python-version`, `check-project-layout` and `check-uv-setup` report nothing new. `check-locks` falls from 36 problems to 16; the 6 beyond the baseline are the VM storefront and VM buyer locks. Lint (pyflakes over every changed source file, plus the VM storefront and e2e projects' own ruff configuration) adds no finding beyond the unmodified tree. `make check-comment-hygiene` finds nothing in source.

Deviations from the task text:

- **Two locks not refreshed.** The VM storefront and VM buyer locks resolve optional torch metadata from `download-r2.pytorch.org`, which this environment could not reach, and the VM storefront lock resolves third-party packages from `mirrors.aliyun.com`, also unreachable. Their suites ran in environments built from the declared dependencies and the rebuilt wheelhouse. Relocking both is carried into §6.3.
- **Test environments.** Every suite ran in an environment built from PyPI and the rebuilt wheelhouse rather than from the project lock, for the reason above and for consistency. Each project's tests import its own `src/`.
- **`examples/local_e2e.py` kept as a client smoke.** It exercises the `PaymentsClient` primitives against a live service with a minimal deal object; the README states that scope.
- **Smaller additions.** `services/payment_selection.py` in the API-credit storefront breaks an import cycle. API-credit seller authentication now accepts empty bodies. A sync/async parity test removed redundant annotation quoting from seven async client methods. The VM refund route uses the existing `settlements_router`. `e2e-tests` declares its direct payments-kit dependency.

### Implementation review evidence

Every suite ran in a fresh environment against a wheelhouse rebuilt from the final tree.

| Suite | Result |
|---|---|
| `kit/arkhai-payments` (`make test`) | 81 passed |
| `core/storefront-client` / `core/storefront` / `kit/capacity-publication` | 37 / 154 (2 skipped) / 8 passed |
| VM storefront / VM buyer | 1,064 passed (the same 3 deselected) / 180 passed |
| Bare-metal storefront / buyer | 99 / 9 passed |
| API-credit domain / storefront / buyer / credits service | 35 / 78 / 17 / 32 passed |
| e2e unit, and the payment scenario without a target | 19 passed; 3 stages blocked |

New cases cover:
- each R13 outcome;
- servicing after fee, dispute-authority and priority changes and after payments is disabled (the bare-metal case also drops payments from priority);
- both race orders in all three domains;
- an interrupted reversal completing (VM, bare metal);
- missing and renamed client response fields;
- attachments for another deal in either position.

Packaging matches P2: `check-locks` reports 15 problems against the baseline's 36, the 6 beyond the baseline still being the two VM locks, and the other three checks report nothing new. Lint adds no finding beyond the unmodified tree; `make check-comment-hygiene` finds nothing in source.

Deviations from the task text:

- **`servicing_stage` in the kit.** The three compositions share one kit helper that builds the stage from servicing fields, rather than each repeating that rule.
- **R8 guard.** The refund failure action's guard reads `ready`, not the delivery-start marker, which is always set once a started delivery has failed; `design.md` R12 is corrected.
- **Abandoned refund intent.** `abandon_refund_intent` (core) and `abandon_bare_metal_refund_intent` restore the prior state when a reversal finds nothing to reverse, and a refund confirms a verified payment before recording intent, so no deal is left in `refunding`.
- **VM settle payload.** Job serialization dropped `settlement_ref` and `retryable` from VM settle responses for deals with an escrow row; the server-side validation from R14 exposed it, and the controller now carries the neutral fields through.
- **No separate VM priority test.** VM servicing never reads priority, so the case is covered by the kit's `servicing_stage` test and the bare-metal disabled-and-deprioritized case.
- **Test support.** `domains/bare_metal/storefront/tests/test_fulfillment_service.py`'s fake database answers the payment-record lookup with no record, as the real one does for escrow deals.

## 6. Merge with the development branch

Runs on the conflicted snapshot after `bare-metal-mock-provisioned-deal` lands; the decisions are taken with the reviewer.

- [x] 6.1 Resolve merge items M1–M7 (`design.md#merge-with-the-development-branch`) and record each outcome in `design.md`. Recorded in `design.md#merge-outcome`; M3's settlement route contract is `storefront_client.settlement_routes`.
- [x] 6.2 Make `kit/identity`'s field framing public as `frame_fields`, use it in `kit/arkhai-payments/src/market_arkhai_payments/receipts.py`, bump `arkhai-kit-identity` once, and move every pin to it in one step (P1). `arkhai-kit-identity` 0.4.0; every exact pin and minor-bump bound moved, with the patch bumps that cascade.
- [x] 6.3 Relock `domains/vms/storefront` and `domains/vms/buyer` where `download-r2.pytorch.org` is reachable, re-run every suite from §5 on the merged tree, then `make check-packaging` (P2), and resolve every failure.
  - Evidence: every lock is current (`make lock`); `make check-packaging` passes; the full `make test` passes on the reviewer's machine, now including the registry client, VM provisioning adapter, e2e unit tests, release tooling, and Helm render contracts. The reconciliation query's later move into each domain's persistence was verified by the affected suites: core, the API-credit storefront (116), the bare-metal storefront (237), and the VM storefront's unit and payment integration suites (1,090).
  - Findings and fixes: `design.md#merge-outcome` (gate findings).

## 7. Closeout

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match; read touched comments for review or migration provenance the target cannot catch.
  - Done 2026-10-08: `make check-comment-hygiene` passes. Stale hosted wording was removed from a settlement-runtime comment and three storefront-client docstrings, and a dead `_HOSTED_PROJECTIONS` test constant went with its deleted file. The receipt and refund outcome docstrings now match the five-outcome taxonomy: `ReceiptUnavailable` is transient only, and `RefundUnavailable` and `RefundBlocked` state their split.
- [x] 7.2 **Import placement.** Review each function-level import added or touched by §5–§6 and move it to module scope where safe, verifying with the relevant suites.
  - Done 2026-10-08: three added function-level imports moved to module scope (VM's resume hook, and API credits' composition and refund handler). The rest stay deliberately: CLI command bodies import lazily by those files' convention, and configuration commands must not initialize storefront settings.
- [x] 7.3 **Documentation compliance.** Re-check R1–R10, P1–P6 and the merge outcomes against `openspec/README.md` placement. Reconcile the delta specs: align the eight reworded deltas with the merged permanent text, add deltas for R1–R16, address the >500-character warnings, and pass `openspec validate settle-through-arkhai-payments --strict` (R10, R17; the deferred §1 statements were removed in review).
  - Done 2026-10-08: `proposal.md` names the blocked outcome. The 15 added requirements over 500 characters were split by behavior or had edge cases moved into scenarios, with every scenario kept. The deltas are the exact difference between the development branch's permanent specs and the final ones: added and modified requirements carry the final text, and removals keep their recorded reasons. `openspec validate settle-through-arkhai-payments --strict` reports the change valid, with no warnings.
- [x] 7.4 **Narrative compression.** Compress §5–§6 notes to final behavior, validation evidence, unresolved work, and destinations; move any debugging narrative into `design.md` first.
  - Done 2026-10-08: §5 notes now state final behavior, evidence, and destinations; stale version pins and moved or tombstoned paths are gone. 6.3's gate narrative moved to the merge record's gate findings.
- [x] 7.5 **Roadmap currency.** Goal 6 current state names agreement settlement, owned attachment policies, and seller-initiated refunds in `docs/development/ROADMAP.md`; the live-qualification row stays until a live run. Name the update in the promotion record.
  - Done 2026-10-08: Goal 6's current state names agreement settlement through the typed client, the owned attachment policies, seller-initiated refunds, and seller-side reconciliation. The live-qualification row stays open, now owned by the payments service's end-to-end tests. The update is in the promotion record.
- [x] 7.6 **Promotion.** Apply `design.md#accepted-permanent-wording` and every row of `design.md#planned-promotion`, then move each row into the design promotion record.
  - Done 2026-10-08: the accepted wording is in `TESTING.md` and the settlement-servicing spec; every row is stated at its destination, R5 and R8 as new settlement-configuration requirements and R9, R12, and R15 in the servicing architecture's charge-first section; the rows are in `design.md#promotion-record`.
- [x] 7.7 **Campaign index currency.** Update this change's row and dependency edges in `openspec/changes/README.md`, and name the update in the promotion record.
  - Done 2026-10-08: the row records implementation, the merge, and promotion, with end-to-end evidence remaining; its acceptance boundary names the route contract, attachment policies, refunds, and reconciliation. The edge to `buyers-use-the-storefront-client` stands.
- [x] 7.8 **Documentation citations.** `make check-doc-citations CHANGE=settle-through-arkhai-payments` passes.
- [x] 7.9 **Packaging.** `make check-packaging` passes on the merged tree (reviewer's machine, recorded under 6.3).
- [ ] 7.10 **End-to-end pipeline.** Run the end-to-end workflow on the closed-out branch and record the run, its result, and the scenarios exercising this change. The credits deal scenario covers the Alkahest settlement path this branch's configuration fix restored; the payment scenario reports its unmet prerequisite without a payments target.
