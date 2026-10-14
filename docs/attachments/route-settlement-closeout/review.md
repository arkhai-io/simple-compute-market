# route-settlement-by-mechanism: independent code review

Mode: auditing. Base reviewed: `settlement-dispatch-campaign` @ 66d83b9f vs 9233a332, `core/`, `domains/`, `kit/`. Read-only; no code changed; no tests run (static review).

## Answers

1. **Core boundary: holds.** No mechanism ID or proposal-presence dispatch in `core/` or `kit/` outside the kits' own registrations. `core_buyer.orchestration.make_settle_hook` (orchestration.py ~L705-745) is an exact table lookup on `Agreement.settlement.mechanism`, raising before effects when absent; the only remaining `accepted_escrow_proposal is None` check is in `_settle_one` (~L838), the explicitly bound escrow helper. `SettlementStageTable`/`SettlementEvidence` (core/src/market_core/settlement.py) are opaque; no actor order. Core files kept: schemas flat-escrow coercion, `escrow_identity.py` default.
2. **Evidence gates delivery: holds with two weaknesses (F2, F3).** VM: `insert_vm_delivery` requires verified evidence (payment_repository.py:~122), planner refuses non-verified (vm_fulfillment_planner.py:11), resume loads evidence, requires `verified` and calls `stage.recover_evidence` before converge (fulfillment_resume_runtime.py:~600). Bare metal: every begin/status/result/teardown goes through `verified_evidence` → stage `revalidate` (settlement_service.py:176); no chain-name or escrow-row fallback remains; contact has `delivery=None` so cannot authorise physical delivery. API credits: `credit_delivery(evidence)` requires verified (settlement/fulfillment.py:~35) and issuance request is built only from it. No path found where pending/failed rows, stray escrow rows, or a mechanism ID authorises delivery.
3. **Exact-once: holds.** VM: PK `negotiation_id` on `vm_delivery_records`, `settlement_ref UNIQUE`, immutable context/fulfillment_id/capacity bindings enforced in `update_vm_delivery`; claim lease. Bare metal: lifecycle PK `negotiation_id`, `settlement_ref` and `capacity_reservation_id` UNIQUE, `ensure_*` compares expected tuple. API credits: grant key is `derive_credit_fulfillment_id(negotiation_id)`; service `_assert_replay` compares the full tuple incl. `request_digest`; `negotiation_id`/`fulfillment_id` unique. Client and service derive/digest identically (same payload keys); test_api.py drives the real typed client against the service.
4. **Transitional aliases: mostly gone.** No `vm_delivery_repository`, no `vm_payment_*` accessors, no chain-name sentinel, `credit_grants.escrow_uid`/`mechanism` removed. Survivors are listed in F6/F7 (all low).
5. **Tautological tests**: see F8. No core/behavioural test found that only restates implementation; two declaration-restating assertions.
6. **Seams**: credits producer/consumer consistent. Buyer/seller pairs consistent for payments (negotiation-ID addressing, pending/ready vocabulary). One structural gap: F4.

## Findings

### F1 (Medium) API-credit evidence store lets verified be downgraded and loses the receipt
`domains/apicredits/storefront/src/apicredits_storefront/settlement_repository.py:store` (ON CONFLICT DO UPDATE sets `status`/`evidence` from the new row) and `settlement_stages.py:PaymentSellerStage.settle` (~L292-300): every re-drive (including the GET /status re-drive) first writes a *pending* record with `source=data` over an already-verified one, then re-polls. If the 30 s poll times out, a previously verified payment is left pending and its stored receipt is gone. Delivery stays safe (pending refuses), and replay at the credits service keeps one grant, but it contradicts the VM/bare-metal repositories, which refuse changes to a verified record (payment_repository.py:~70, sqlite_client.py `save_bare_metal_settlement_evidence`), and makes lost-ack recovery depend on the payments service still answering.
Fix: in `store`, reject any write over `status='verified'` that changes status or payload; in `settle`, if `old` is verified, revalidate it (receipt_matches) instead of re-saving pending.

### F2 (Medium) Alkahest API-credit delivery re-verifies on chain inside the failure-swallowing block
`settlement_stages.py:AlkahestSellerStage.deliver_prepared` (~L440-455) calls `self.prepare(...)` (full `verify_escrow_for_settlement`) inside `try/except Exception → FulfillmentOutcome(failed)`. The coordinator already ran `prepare` immediately before, so on the fresh path this is a duplicate chain read; a transient RPC error now makes a verified, unissued deal terminally `failed` (`persist_api_credit_settlement_outcome` marks progress and escrow failed; `settle` then returns the terminal row forever). Base code had no re-verification in this step. Fix: load the evidence saved by `prepare` (`db.load_settlement_evidence`) and require `verified`, no second chain verification; or let transport errors leave progress `provisioning`.

### F3 (Low-Medium) Implicit Alkahest default for selection-less proposals in VM seller
`domains/vms/storefront/src/market_storefront/settlement_stages.py:resolve_proposal_stage` (~L620) maps a proposal without `settlement_selection` to `"alkahest.v1"`, and `negotiation_runtime.py:_accepted_settlement_artifacts` (~L478-505) falls through to the escrow artifact builder when no selection exists. This is the legacy flat-escrow carrier the design keeps, but it is a mechanism-ID default in the dispatch path that the proposal says must not exist. Post-acceptance recovery is safe (it resolves from Agreement bytes). Fix: require the Agreement/selection to name the mechanism and refuse otherwise, or isolate the legacy decoding in the carrier layer and delete when `drop-escrow-from-shared-wire` lands.

### F4 (Low-Medium) Buyer-side SettlementEvidence plumbing has no producer
Core adds `BuyResult.settlement_evidence`, `DealContext.settlement_evidence`, a `settlement_evidence` run-log event, recovery correlation and identity validation (core/buyer deal_helpers.py, orchestration.py, orchestrator.py). No buyer domain (VM, API credits, bare metal) constructs a `SettlementEvidence` (grep: none outside tests). It is exercised only by core tests with synthetic evidence. Either a stage should emit it (e.g. payments buyers could record the mandate/transaction), or this should be removed until a mechanism needs it; as it stands it is unexercised surface and the buyer-side recovery still relies on `escrow_uid`/`settlement_ref` run-log fields.

### F5 (Low) Idempotency conflict surfaces with the wrong status
VM Alkahest: a second escrow UID for the same negotiation raises `ValueError` from `save_vm_settlement_evidence` inside `prepare_vm_settlement`, which `settle_controller` maps to 404 (the `except ValueError` in the shared coordinator path, VM settlement_stages.py ~L240). Should be 409.

### F6 (Low) Escrow-named names that now carry neutral references
- `domains/apicredits/settlement/fulfillment.py` (`escrow_uid = evidence.settlement_ref`, stage events, failure-policy kwargs) and `credits_client.py:rollback_issuance(escrow_uid=...)` (reason string) carry payment transaction IDs under an escrow name; `apicredits_storefront/services/fulfillment_service.py:57` releases capacity with `deal_ref={"escrow_uid": ...}` (the ledger falls back to it only when no reservation id is given). VM `failure_actions.py` was switched to `negotiation_id` deal refs; API credits was not.
- VM migration id `20261001_011_vm_payment_records` (utils/migrations.py:505) now creates `vm_settlement_evidence`/`vm_delivery_records`.
- Kept intentionally (not findings): public DTO `escrow_uid`, `BareMetalMaterialization.escrow_uid`, capacity `deal_ref.escrow_uid`, ledger correlation, genuine Alkahest escrow rows.

### F7 (Low) Duplication across domains/roles (structural, deferred by design)
Identical `AlkahestBuyerStage.enrich/resources` in VM and API-credit buyers; `_resume_alkahest` in the VM buyer re-inlines the create→submit→poll flow that `_settle_one` implements for the live path; credits grant-id derivation and request digest exist twice (client `credits_client.py`, service `models/keys_model.py`) with parity checked only indirectly by test_api.py; evidence status vocabularies differ per domain (`verified` vs `settlement_verified`). Domain-owned by decision; candidate for a kit helper later (idea, not filed here).

### F8 (Low) Tests restating the implementation
- `domains/bare_metal/storefront/tests/test_domain_runtime.py:32` asserts `set(seller_stages) == {three literals}` and the surrounding `callable(...)`/`is not None` capability asserts: restates the table declaration.
- `core/tests/unit/test_domain_contract.py` parametrised table-shape cases are behavioural (validator rejects), keep.
- No tautological tests found among the new behavioural ones (stray-escrow ignored, evidence cannot retarget, unsupported preferred option cannot win, restart revalidation, changed reuse conflicts).
- Not covered: no direct unit test for `market_core/settlement.py` (duplicate/None-stage rejection, immutability); proposed test: `SettlementStageTable` rejects duplicate mechanisms and `SettlementEvidence.validate_identity` rejects changed ref (core carrier property).

### F9 (Info) Cost
`domains/apicredits/service/uv.lock` +973 lines: the service now carries the full domain-wheel dependency tree (web3 stack) as a dev dependency only so tests can drive the typed client; no runtime dependency added.

## Not verified
Static review only: suites not run; live payments/ledger/hardware not exercised (as the evidence packets state).
