# VM seller dispatch and evidence — implementation self-check

Tested revision: `cccbe7d1`, implementation in `0e326d8a`. Scope: tasks 2.2–2.3. The committed replay/setup is on the `vm-seller-evidence` branch. This is checkout-local wiring evidence, not independent acceptance or live payment/VM qualification.

## Setup and replay

Required and prepared target: the `vm-seller-evidence` checkout of simple-compute-market. No remote deployment or inherited target selector is used. Internal packages are built into `.dist` and consuming storefront dependencies are reinstalled. The controlled example uses deterministic Ed25519 buyer, seller and payment-service personas, a synthetic accepted Agreement and its mandate, controlled payment HTTP and delivery, and a fresh temporary SQLite database. No secrets or external services are required. The example removes its database and stops its coordinator automatically.

From the repository root, this opens the story surface:

```sh
make dist && make -C domains/vms/storefront reinit && uv run --project domains/vms/storefront --locked --find-links .dist --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" --with "$PWD/.dist/arkhai_kit_arkhai_payments-0.1.0-py3-none-any.whl" python domains/vms/storefront/examples/payment_smoke.py
```

Readiness was observed by successful in-process composition and signed settlement requests, not by a deployed service probe. Old databases containing `vm_payment_records` are refused with an explicit reset diagnostic; no copy/adoption migration is provided. Use a disposable fresh database for this cutover.

## Observations

- Before approval: `pending`, zero deliveries. After approval: `provisioning`. Retry after the owned task completes: `ready`, exactly one delivery. SQL inspection: **zero `escrows` rows**.
- Seller dispatch reads the persisted Agreement's mechanism through the domain seller table. Entry-owned guards still reject substituted buyer/key/chain inputs; accepted mandate construction and publication readiness projection use the same declaration.
- Fresh SQLite bootstrap and reopen preserve evidence and delivery state. Pending evidence cannot initialize delivery. Changed mechanism, Agreement digest, established reference or physical fulfillment identity is refused. Independent owners cannot share an unexpired delivery claim or release another owner's claim.
- Recovery with a persisted physical fulfillment ID reads the active result without scheduling or beginning another fulfillment, including through the negotiation-scoped repository adapter.
- Alkahest retains genuine escrow/obligation rows. Its stage persists accepted-option-derived lease bytes and condition anchor; physical checkpoint/context/claim state is stored separately by negotiation.

## Validation

The focused command, after `make dist` and consuming `reinit`:

```sh
cd domains/vms/storefront
ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --no-sync pytest tests/unit/test_settlement_composition.py tests/unit/test_settlement_publication.py tests/unit/test_settlement_start_authority.py tests/unit/test_domain_runtime_wiring.py tests/unit/test_migrations.py tests/unit/test_fulfillment_reconciliation.py tests/unit/test_fulfillment_resume_runtime.py tests/unit/test_fulfillment_provisioning.py tests/unit/test_fulfill_vm_obligation_error_handling.py tests/unit/test_architecture_imports.py tests/integration/test_settle_controller.py tests/integration/test_negotiate_controller.py -q
```

Result: **100 passed**. The config fixture emits its existing missing-agent-ID warning. New repository/stage/coordinator modules were formatted and their unused/import-order checks passed. No storefront static Make target is declared. `make check-comment-hygiene` and `openspec validate route-settlement-by-mechanism --strict` passed. The final replay printed the sequence and zero-escrow count above.

Initial fixture adaptation exposed absent role tables and old fulfillment carrier keys; those fixtures now use the core seam. Three negotiation fixtures omitted their advertised escrow address; they now send the advertised address rather than weakening accepted-option guards. The publication helper initially reconstructed a domain contract; the architecture check caught it and the helper now binds only the seller declaration. Running the smoke without its documented buyer wheel failed import; the documented command above supplies it. Normalized claim construction also rejected the synthetic listing's missing pool identity; the example now seeds its accepted pool explicitly rather than relaxing the stage's claim guard.

## Follow-up boundary

Task 2.4 still owns removal of mechanism switches from the planner/physical delivery/restart continuation. `SettlementEvidence.evidence.delivery` already carries `vm.delivery-facts` version 1: accepted order and provision terms, required attributes, lease timing, funding expiry, lease bytes and condition anchor; payment facts additionally carry receipt identity, holds and hold end. Payment receipt revalidation is entry-owned but its invocation in recovery still sits behind the existing mechanism switch. Alkahest attestation/claim binding and accepted-source revalidation must be routed through its entry before common recovery becomes evidence-only.

`vm_delivery_repository(negotiation_id)` adapts current helper escrow-coordinate keywords to `vm_delivery_records`; it is not a payment escrow fallback. Recovery temporarily retains discovery of genuine Alkahest escrow contexts only when no delivery record exists. Task 2.4 can finish the direct delivery-key APIs and remove that path. The controlled example is mechanically adapted and self-driven here; task 2.5 remains the joined replay after 2.4. Promotion remains with task 2.6.

No screenshots apply. No server, container or external resource remains running.
