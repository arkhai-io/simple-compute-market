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
  - `kit/arkhai-payments/src/market_arkhai_payments/agreement.py` (new): `mandate_policy_for_agreement(agreement, config, *, expected_payer=None)`, replacing the four copies, and `PaymentSettlementData` `{mandate, transaction_id}` with construction from an Agreement and validation of stored data against exact Agreement bytes.
  - `.../seller.py` (new): receipt outcomes `ReceiptPending`, `ReceiptVerified`, `ReceiptInvalid`, `ReceiptUnavailable`; refund outcomes `Refunded`, `NotPaid`, `NothingToReverse`, `RefundUnavailable`; `PaymentSellerStage(config, client_for_owner=...)`. The stage provides:
    - settlement data at acceptance;
    - a single-`GET` receipt check;
    - stored-receipt re-check;
    - `deposit_if_advertised`;
    - `reverse`, which re-checks the receipt first and maps service codes as P5 lists.
  - `.../buyer.py` (new): `PaymentApproval(config, payer_account, client_for_owner=...)`. Its `approve` validates Agreement bytes, the seller's transaction ID, and the optional advertised option; it attaches only under `attach_agreement`, approves, verifies the approval receipt, polls, and verifies the snapshot receipt. It never calls `ensure_agreement_attached`.
  - `.../receipts.py`: add `receipt_message(receipt)`; `verify_receipt_signature` uses it.
  - `.../settlement_config.py`: `attach_agreement: bool = False`; the seller-role preflight reports blocker `arkhai_payments.attach_agreement_buyer_only` when it is true. `payments_client_for_owner` is unchanged.
  - `.../fixtures/__init__.py`, `.../fixtures/receipts.py` (`sign_receipt`, `build_signed_receipt`), `.../fixtures/payments_client.py` (`FakePaymentsClient`: serves a receipt or none, simulates unavailable and service error codes, records approve/attach/reverse calls).
  - `.../__init__.py`: export the new public API.
  - `kit/arkhai-payments/README.md` and `kit/arkhai-payments/examples/local_e2e.py`: use the stage and approval API.
  - Tests, all new under `kit/arkhai-payments/tests/`:
    - `test_mandates.py`: hold rounding up, approval expiry rounding down, authorities, nonce, fee, per-field `check` tamper rejection.
    - `test_receipts.py`: scheme, issuer, signature, deal, from, to.
    - `test_client.py` (`httpx.MockTransport`): not-found, API errors, protocol errors, redirect, attachment.
    - `test_seller.py`: every receipt and refund outcome, deposit ordering, single `GET`.
    - `test_buyer.py`: approval checks and the attachment policy truth table.
    - `test_agreement.py`: settlement-data shape and stored-data validation.
    - `test_receipt_fixture.py`: byte-exact reproduction of the published vector.
    - `test_settlement_config.py` (extend): the seller-role blocker.
  - Bump `kit/arkhai-payments/pyproject.toml` to 0.2.0.
  - Validation: kit `make test` (typing, vectors, generated models, unit).

- [x] 5.2 **Core carriers and the typed client** (R1, R4, R7).
  - `core/storefront/src/core_storefront/models/settle_models.py`: `AgreementSettleResponse` (`negotiation_id`, `escrow_uid` equal to the negotiation ID, `settlement_ref`, `status`, `retryable`, domain fields allowed), `RefundSettlementResponse` (`negotiation_id`, `settlement_ref`, `status`). Bump `core/storefront/pyproject.toml` to 0.4.0.
  - `core/storefront-client/src/storefront_client/client.py`, async and sync:
    - rename `settle` to `settle_evm`;
    - add `settle_agreement(negotiation_id, *, request_id=None)` (buyer, `settle_escrow`, `/api/v1/settle/{negotiation_id}`, body `{negotiation_id, buyer_principal}`);
    - add `refund_settlement(negotiation_id, *, request_id=None)` (seller, `refund_settlement`, `POST /api/v1/settlements/{negotiation_id}/refund`, empty body).
  - `core/storefront-client/src/storefront_client/models.py`: matching response dataclasses.
  - `core/storefront-client/src/storefront_client/__init__.py`: exports.
  - Bump `core/storefront-client/pyproject.toml` to 0.18.0.
  - Repin consumers: `domains/vms/storefront/pyproject.toml` and `e2e-tests/pyproject.toml` (`>=0.18.0`), `provisioning/compute/service/pyproject.toml` (`==0.18.0`).
  - Rename callers: `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`, `.../test_non_erc20_settlement.py`.
  - Tests:
    - `core/storefront-client/tests/test_settlement_requests.py` (new): bodies, routes, roles, and operations for all three methods, async and sync.
    - `domains/vms/storefront/tests/unit/test_storefront_client_parity.py` (new): public method names and signatures match across `StorefrontClient` and `SyncStorefrontClient`. It sits in the owning service's suite, per `TESTING.md`.

- [x] 5.3 **VM** (R2, R4, R5, R7, R8, P4, P6).
  - Storefront `domains/vms/storefront/src/market_storefront/`:
    - `arkhai_payments.py`: tombstone; replaced by the kit stage.
    - `settlement_composition.py`: build `PaymentSellerStage` only from ready configuration; a not-ready payments registration composes no stage.
    - `negotiation_runtime.py`: settlement data from `PaymentSettlementData`.
    - `payment_settlement.py`:
      - the coordinator consumes the R2 outcomes;
      - it checks `refunded` first;
      - it deposits before delivery;
      - its `failed` write is conditional on the status not being `refunded`;
      - add `refund(negotiation_id, thread)` writing `refunded`, inserting the escrow row when absent.
    - `controllers/settle_controller.py`: outcome-to-HTTP mapping (202/409/503), the `AgreementSettleResponse` neutral fields, and `POST /settlements/{negotiation_id}/refund` on the existing empty `settlements_router` (non-payment mechanisms → 409).
    - `middleware/seller_auth.py`: resolve the refund path as seller mutation `refund_settlement` bound to the negotiation ID, authorized without a listing lookup.
    - `services/fulfillment_resume_runtime.py`: validate stored settlement data through the kit.
    - `failure_actions.py`: `refund` dispatches on the deal's Agreement mechanism; the payments branch reverses only when nothing was delivered (no `ready` escrow status and no active fulfillment) and records `refunded`.
    - `domains/vms/storefront/examples/payment_smoke.py`: receipts from the kit fixture and no `_frame` import.
  - Buyer `domains/vms/buyer/`:
    - `arkhai_payments.py`: `VmArkhaiPaymentsBuyer` replaced by the kit `PaymentApproval`; `VmSettlementTransport` stays (R1).
    - `pyproject.toml`: relock.
  - Tests:
    - `domains/vms/storefront/tests/integration/test_payment_settlement.py` (new): through `StorefrontClient.settle_agreement` and `refund_settlement` over `ASGITransport`, with the real app, SQLite and DI, and `FakePaymentsClient` injected through the stage's client factory. Cases:
      - pending, then verified;
      - impostor-signed receipt → 409, no delivery;
      - receipt for another mandate → 409;
      - unavailable → 503;
      - deposit before delivery, and a failed deposit → 503 without delivery;
      - idempotent repeat;
      - refund before delivery blocks a later settle;
      - repeated refund issues one `reverse`;
      - matured hold → 409;
      - buyer-signed refund rejected;
      - `refund` failure action enabled reverses once and records `refunded`; disabled reverses nothing;
      - a concurrent `failed` write does not overwrite `refunded`.
    - Update `domains/vms/storefront/tests/unit/test_settlement_composition.py` and `test_server_app_composition.py`, and VM buyer tests under `domains/vms/buyer/tests/`.
  - Validation: VM storefront `make test` (unit and integration), VM buyer `make test`.

- [x] 5.4 **Bare metal** (R2, R4, R5, R6, R7, P3).
  - Storefront `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/`:
    - `arkhai_payments.py`: tombstone.
    - `settlement_composition.py`: kit stage and `settlement_data_dispatch` through `PaymentSettlementData`.
    - `settlement_service.py`:
      - R2 outcomes;
      - deposit, then call `fulfillment_service.begin` after a verified receipt, as R6 specifies;
      - add `refund`.
    - `fulfillment_service.py`: `begin` refuses a `refunded` record.
    - `api.py`: payment settle response mapping; `POST /api/v1/settlements/{negotiation_id}/refund` with a new `_seller` helper over `_principal`.
    - `models.py`: the payment path returns `AgreementSettleResponse` with lifecycle fields; the Alkahest responses are unchanged.
    - `sqlite_client.py`: `mark_bare_metal_settlement_refunded`.
    - `migrations.py`: migration 0008's CHECK admits `refunded` (P3).
    - The Alkahest `begin` route stays on this tree.
  - Buyer `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/`:
    - `arkhai_payments.py`: kit `PaymentApproval`; `BareMetalSettlementTransport` stays.
    - `cli.py`: the payment flow retries `settle` while `pending`, then polls fulfillment status, with no `begin` call.
  - Packaging:
    - `domains/bare_metal/{storefront,buyer}/pyproject.toml`: payments kit `==0.2.0`.
    - The storefront dev group adds `arkhai-core-storefront-client>=0.18.0`.
    - Relock.
  - Tests:
    - `domains/bare_metal/storefront/tests/test_payment_settlement_client.py` (new), through the typed client with `FakePaymentsClient`: verified starts fulfillment once; impostor receipt → 409 with no fulfillment; refund before delivery makes `begin` refuse.
    - Update `domains/bare_metal/storefront/tests/test_http_settlement.py`, `test_persistence.py`, `test_fulfillment_service.py`, and the buyer tests.
  - Validation: bare-metal storefront and buyer `make test`.

- [x] 5.5 **API credits** (R2, R4, R5, R7, R8, P5, P6).
  - `domains/apicredits/settlement/payments.py`: remove `mandate_policy_from_agreement`; keep payer and publication-clause validation. Update `domains/apicredits/settlement/__init__.py`.
  - Storefront `domains/apicredits/storefront/src/apicredits_storefront/`:
    - `settlement_composition.py`: kit stage; `payment_settlement_artifacts` delegates to `PaymentSettlementData`.
    - `services/payment_settlement_service.py` (new): the payment orchestration moved out of the controller. It uses R2 outcomes, checks `refunded` first, deposits before issuance, keeps the uncertain-issuance-is-pending behavior, makes its `failed` write conditional (P6), and adds `refund`.
    - `controllers/settle_controller.py`: thin binding with the R2 mapping and neutral fields; the refund route.
    - `middleware/seller_auth.py`: `make_seller_auth_dep(operation, resource_param="listing_id")`; the refund route binds `negotiation_id`.
    - `services/fulfillment_service.py`: a `refund` handler on the failure policy, dispatching on mechanism, pre-delivery only.
    - `server.py`: wiring.
  - Buyer `domains/apicredits/buyer/payments.py`: kit `PaymentApproval`, keeping its listing and option binding through `advertised_option`; `submit_settlement_request` stays.
  - Packaging: the storefront dev group adds `arkhai-core-storefront-client>=0.18.0`; relock `domains/apicredits/{.,storefront,buyer}`.
  - Tests:
    - `domains/apicredits/storefront/tests/integration/test_payment_settlement.py` (new): verified issues once; impostor receipt → 409 with no grant; refund before issuance blocks a later settle; the `refund` failure action enabled reverses once.
    - Update `tests/unit/test_settlement_fulfillment.py` and `test_sync_negotiation.py`, and `domains/apicredits/buyer/tests/test_settlement_composition.py`.
  - Validation: API-credit domain, storefront, buyer, and service `make test`.

- [x] 5.6 **API-credit payment system scenario** (R3, R7).
  - `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py` (new), on `DomainDealState` and the profiled buyer CLI. Stages: publication, discovery, negotiation selecting `arkhai.payments.v1`, approval, receipt-gated issuance, consumption, status, idempotent re-drive from the buyer's run log, then a seller refund through `StorefrontClient.refund_settlement` with the transaction observed reversed.
  - `e2e-tests/src/e2e_harness/settings.py` and `e2e-tests/config/config.yml`: optional payments target settings (service URL, receipt identity, buyer and payee accounts, credential environment names). `require_state` reports the scenario blocked when they are absent or the target is not ready.
  - Register marker `e2e_credits_payment_deal` in `e2e-tests/pyproject.toml` and the API-credit lane expression in `e2e-tests/Makefile`.
  - Validation: e2e unit suite; the scenario runs here only if a payments target is reachable, otherwise its blocked result is disclosed.

- [x] 5.7 **Diagnostics, comments, and the gate** (R3, R10, P2).
  - `docs/attachments/settle-through-arkhai-payments/{vm_smoke,bare_metal_smoke,api_credit_smoke,smoke_common}.py`: move to the kit stage, approval, and fixture APIs; `index.md` records that they were updated, not rerun.
  - `core/src/market_core/schemas.py`: current-state docstrings for `SettlementPlan` and `SettlementObligation` (R10); a neutral example in the `SettlementSelection.params` comment.
  - Gate:
    - `make dist`;
    - `uv lock --check --find-links .dist` in every changed project;
    - typing for `kit/arkhai-payments` and the changed storefronts against their recorded baselines;
    - focused suites from 5.1–5.6;
    - `make check-comment-hygiene`.

    Disclose that `make check-packaging` is not available on this tree (P2).

### Implementation review round

Decisions: `design.md#implementation-review-decisions` (R11–R17). Every package touched here was already bumped in this unmerged change, so no further version bumps. Order: 5.8–5.10 (kit) first; 5.11 (core) before the domains; 5.12–5.14 (domains) are independent of each other; 5.15–5.16 last.

- [x] 5.8 **Kit: servicing from the accepted artifact** (R11).
  - `kit/arkhai-payments/src/market_arkhai_payments/agreement.py`: `PaymentSettlementData.require_bound_to(agreement)` re-derives with the fee and dispute authority recorded in the stored mandate and compares exactly; it replaces `require_derived_from`.
  - `.../seller.py`: `PaymentSellerStage` needs only the service URL and receipt identity at construction; `settlement_data()` requires the fee policy and dispute authority and refuses without them; `accepted()` uses `require_bound_to`.
  - `.../settlement_config.py`: `payments_client_for_owner` no longer refuses a disabled configuration.
  - Tests: `kit/arkhai-payments/tests/test_agreement.py` (accepted data survives fee and dispute-authority changes; tampered Agreement-bound fields are refused), `test_seller.py` (a stage from a disabled section services an accepted deal), `test_settlement_config.py`.

- [x] 5.9 **Kit: operator-action outcomes and reversal completion** (R12, R13).
  - `.../seller.py`: `ReceiptBlocked` and `RefundBlocked`; classify service codes, transport, status and protocol errors as R13's table lists; `reverse` treats "nothing left to reverse" as `Refunded` when the snapshot shows every part reversed.
  - `.../fixtures/payments_client.py`: settable service error code for reads and reverses; reversed snapshots after a reverse.
  - Tests: `test_seller.py` (one case per R13 row, including a missing credential and another transaction ID; reverse completion after a prior reverse).

- [x] 5.10 **Kit: attachments and approval** (R15, R16).
  - `.../client.py`: `ensure_agreement_attached` examines every attachment, returns the matching one, refuses any mismatch.
  - `.../fixtures/payments_client.py`: the same rule.
  - `.../buyer.py`: drop `advertised_option` from `check` and `approve`.
  - Tests: `test_client.py` (a mismatched attachment before a matching one is refused; duplicate matching attachments succeed), `test_buyer.py`.

- [x] 5.11 **Core: ordered transitions and strict responses** (R12, R14).
  - `core/storefront/src/core_storefront/sqlite_client.py`: `claim_delivery_start(escrow_uid)` (`fulfillment_phase` from `NULL` to `delivery_started` only while the status is `provisioning`; reports whether this call owns delivery) and `record_refund_intent(escrow_uid, negotiation_id)` (inserts or moves the row to `refunding` and reports whether delivery had started), each one conditional statement.
  - `core/storefront/tests/unit/test_sqlite_client_escrow_fulfillment_identity.py`: both orders of the two transitions, and repetition of each.
  - `core/storefront-client/src/storefront_client/models.py`: `AgreementSettleResponse.from_dict` and `RefundSettlementResponse.from_dict` raise on a missing required field; `client.py` surfaces that as `StorefrontClientError`.
  - `core/storefront-client/tests/test_settlement_requests.py`: missing and renamed required fields raise.

- [x] 5.12 **VM** (R11–R14).
  - `domains/vms/storefront/src/market_storefront/settlement_composition.py`: build the stage whenever the payments section has a service URL and receipt identity.
  - `.../payment_settlement.py`: map `ReceiptBlocked`/`RefundBlocked` to 500; `_provision` claims delivery start before `fulfill_domain` and stops if it does not own it; refund records intent before reversing; a `refunding` deal completes its reversal on any later settle or refund; the final provisioning write records delivery details beside a refund; validate payloads through the core response models; correct the module docstring.
  - `.../failure_actions.py`: the payments refund guard reads the delivery-start marker and `ready`.
  - `.../services/fulfillment_resume_runtime.py`: servicing uses the stage regardless of `enabled`.
  - `domains/vms/storefront/tests/integration/test_payment_settlement.py`: fee and dispute-authority change after acceptance; payments disabled after acceptance (settle and refund); priority change; refund winning the race (no dispatch); delivery winning the race (refund recorded with the delivery); crash after `reverse` before the refunded write completes on retry; one `ReceiptBlocked` case.

- [x] 5.13 **Bare metal** (R11–R14).
  - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py`: build the stage from servicing configuration.
  - `.../sqlite_client.py`: start a payment deal's lifecycle only while its record is `settlement_verified`, in one transaction; `record_bare_metal_refund_intent` moves the record to `refunding` and reports whether a lifecycle exists.
  - `.../migrations.py`: migration 0008's CHECK also admits `refunding` (P3).
  - `.../fulfillment_service.py`: `begin` uses the conditional lifecycle start for payment deals.
  - `.../settlement_service.py`: Blocked outcomes as 500; refund intent before reversing; completion of a `refunding` deal; payload validation through the core models.
  - Move `domains/bare_metal/storefront/tests/test_payment_settlement_client.py` to `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py` (with `tests/integration/__init__.py`) and add: payments disabled after acceptance; refund winning the race (no lifecycle, no reservation); delivery winning the race; reversal completion after a crash.

- [x] 5.14 **API credits** (R11–R14, R16).
  - `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py`: build the stage from servicing configuration.
  - `.../services/payment_settlement_service.py`: replace the in-process lock with `claim_delivery_start` and `record_refund_intent`; Blocked outcomes as 500; reversal completion; payload validation through the core models.
  - `.../services/fulfillment_service.py`: the refund guard reads the delivery-start marker.
  - `domains/apicredits/buyer/payments.py`: stop passing `advertised_option`.
  - `domains/apicredits/storefront/tests/integration/test_payment_settlement.py`: payments disabled after acceptance; refund winning the race; delivery winning the race.

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
- [ ] 6.3 Relock `domains/vms/storefront` and `domains/vms/buyer` where `download-r2.pytorch.org` is reachable, re-run every suite from §5 on the merged tree, then `make check-packaging` (P2), and resolve every failure.
  - Evidence on the merged tree (sandbox without `download-r2.pytorch.org`, Helm, or Cargo): `make dist` builds every wheel; 48 of 51 locks are regenerated and current. Static checks: comment hygiene, uv setup, Python version, and project layout pass; document citations match the development branch's 15 pre-existing problems.
  - Built-environment suites pass: core 478; kits except `kit/policy` (payments kit: mypy, vectors, generated models, 81 unit); compute provisioning 1,553; registry 253; bare metal 401; compute 6; VM domain 47; API-credit Python suites 232. Release tooling matches the development branch's 4 pre-existing failures.
  - VM storefront and buyer suites ran from source: storefront unit 1,064 and integration modules pass (payment settlement 17). Failures that also occur on the development tree in the same environment, or come from FastAPI 0.142 or uninstalled entry points, are environmental.
  - Fixed during the gate: development tests calling `StorefrontClient.settle` and the acceptance validator without an Agreement; the e2e payment scenario's settings import; hosted leftovers in the API-credit filter spec; identity release fixtures; and the VM and API-credit opening guards, which refused a selection's `params` and so every payment negotiation through the default chain (guard tests added).
  - The reviewer's `make lock` relocked every project, including the three that need `download-r2.pytorch.org`, and `make test` passed on their machine.
  - `make test` skipped five suites: the registry client, the VM provisioning adapter, the e2e unit tests, release tooling (`scripts/tests`), and the Helm render contracts. All five are now in its chain; only the docker-compose e2e scenarios and cluster `helm test` remain separate. Release tooling exposed two stale development tests that pinned Bob's development profile to Alkahest alone and forbade the chain address book a development change added deliberately; both were aligned with the configuration.
  - `make check-packaging` passed on the reviewer's machine: installs derive internal packages from locks, every lock is current, every Python selection reads the root declaration, and every distribution is one `src/` package that installs editable.
  - The extended `make test` failed at `helm/scripts/test-render.sh`: the payments fixture's render file was never created, because the fiat render it replaced had been removed before the merge. The script now creates and renders it; the fixture and both negative cases were checked against the generated values schemas.
  - The render contracts then failed on stale subchart archives (`helm/charts/*.tgz`, gitignored) packaged before the schema change; `test-render` now runs `helm dependency update` first. With current charts, the development identity-overlap render failed on its own: the chart's default peer identities became EIP-191 principals, so each of the scenario's four added EIP-191 principals duplicated a default. The scenario now adds each peer's Ed25519 principal, keeping two schemes per list. Failed renders now print Helm's error instead of exiting silently.
  - The overlap fixture's provisioning bootstrap identities were also Ed25519 while the chart defaults are EIP-191; the reviewer moved them to EIP-191, and the render contracts then passed.
  - Remaining: one full `make test` run with the extended chain.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every match; read touched comments for review or migration provenance the target cannot catch.
- [ ] 7.2 **Import placement.** Review each function-level import added or touched by §5–§6 and move it to module scope where safe, verifying with the relevant suites.
- [ ] 7.3 **Documentation compliance.** Re-check R1–R10, P1–P6 and the merge outcomes against `openspec/README.md` placement. Reconcile the delta specs: align the eight reworded deltas with the merged permanent text, add deltas for R1–R16, address the >500-character warnings, and pass `openspec validate settle-through-arkhai-payments --strict` (R10, R17; the deferred §1 statements were removed in review).
- [ ] 7.4 **Narrative compression.** Compress §5–§6 notes to final behavior, validation evidence, unresolved work, and destinations; move any debugging narrative into `design.md` first.
- [ ] 7.5 **Roadmap currency.** Goal 6 current state names agreement settlement, owned attachment policies, and seller-initiated refunds in `docs/development/ROADMAP.md`; the live-qualification row stays until a live run. Name the update in the promotion record.
- [ ] 7.6 **Promotion.** Apply `design.md#accepted-permanent-wording` and every row of `design.md#planned-promotion`, then move each row into the design promotion record.
