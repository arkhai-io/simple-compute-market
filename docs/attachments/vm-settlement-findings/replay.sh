#!/usr/bin/env bash
# Run from the repository root; owns only temporary controlled test state.
set -euo pipefail
make dist
make -C domains/vms/buyer reinit
make -C domains/vms/storefront reinit
(
  cd domains/vms/buyer
  .venv/bin/python -m pytest \
    tests/test_negotiate_stage_dispatch.py tests/test_buy_orchestrator.py \
    tests/test_vm_settlement_helpers.py tests/test_buy_resume_cli.py \
    tests/test_resume_helpers.py tests/test_plugin_export.py \
    tests/test_buyer_client.py tests/test_buyer_client_resume.py \
    tests/test_buy_pricing_and_filters.py tests/test_aggregation_policy.py \
    tests/test_explain_cli.py tests/test_settlement_config_template.py \
    tests/test_config_migration_cli.py -q
)
(
  cd domains/vms/storefront
  ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' .venv/bin/python -m pytest \
    tests/unit/test_vm_evidence_validation.py \
    tests/unit/test_settlement_reference_conflict.py \
    tests/unit/test_sync_negotiation_seller_round_hook.py \
    tests/unit/test_sync_negotiation_escrow_normalization.py \
    tests/unit/test_vm_fulfillment_planner.py \
    tests/unit/test_fulfillment_provisioning.py \
    tests/unit/test_fulfillment_resume_runtime.py \
    tests/unit/test_fulfill_vm_obligation_error_handling.py \
    tests/unit/test_fulfillment_reconciliation.py \
    tests/unit/test_settlement_composition.py \
    tests/unit/test_settlement_publication.py \
    tests/unit/test_fulfillment_service.py tests/unit/test_domain_runtime_wiring.py \
    tests/unit/test_architecture_imports.py \
    tests/unit/test_settlement_start_authority.py \
    tests/unit/test_migrations.py tests/unit/test_failure_policy.py \
    tests/integration/ -q
)
domains/vms/storefront/.venv/bin/python \
  docs/attachments/route-settlement-closeout/inspect_vm_schema.py
uv run --project domains/vms/storefront --locked --find-links .dist \
  --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" \
  --with "$PWD/.dist/arkhai_kit_arkhai_payments-0.1.0-py3-none-any.whl" \
  python domains/vms/storefront/examples/payment_smoke.py
make check-comment-hygiene
