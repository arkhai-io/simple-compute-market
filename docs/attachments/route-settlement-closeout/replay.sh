#!/usr/bin/env bash
# Run from the repository root. Controlled qualification only; no live scenarios.
set -euo pipefail
make dist-clean
make dist
for project in core/buyer core/storefront domains/vms/buyer domains/vms/storefront domains/bare_metal/storefront domains/apicredits/buyer domains/apicredits/storefront domains/apicredits/service kit/arkhai-payments e2e-tests; do
  make -C "$project" reinit
done
(cd domains/bare_metal/buyer && uv sync --dev --find-links ../../../.dist --reinstall)
(cd core && uv sync --dev --find-links ../.dist --reinstall)
(cd domains/apicredits && uv sync --dev --find-links ../../.dist --reinstall)
(cd core && uv run --no-sync pytest tests/unit/test_carrier_purity.py tests/unit/test_domain_contract.py tests/unit/test_domain_boundaries.py -q)
(cd core/buyer && uv run --no-sync pytest tests/unit/test_orchestrator.py tests/unit/test_settlement_acceptance.py tests/unit/test_settlement_policy.py tests/unit/test_priceless_options.py tests/unit/test_identity_recovery.py -q)
(cd core/storefront && uv run --no-sync pytest tests/unit/test_domain_registry.py tests/unit/test_domain_lifecycle.py tests/unit/test_publication_plugins.py -q)
make -C core typecheck-core
(cd domains/vms/buyer && uv run --no-sync pytest tests/test_buy_orchestrator.py tests/test_vm_settlement_helpers.py tests/test_buy_resume_cli.py tests/test_resume_helpers.py tests/test_plugin_export.py tests/test_buyer_client.py tests/test_buyer_client_resume.py tests/test_buy_pricing_and_filters.py tests/test_aggregation_policy.py tests/test_explain_cli.py tests/test_settlement_config_template.py tests/test_config_migration_cli.py -q)
(cd domains/vms/storefront && ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --no-sync pytest tests/unit/test_vm_fulfillment_planner.py tests/unit/test_fulfillment_provisioning.py tests/unit/test_fulfillment_resume_runtime.py tests/unit/test_fulfill_vm_obligation_error_handling.py tests/unit/test_fulfillment_reconciliation.py tests/unit/test_settlement_composition.py tests/unit/test_settlement_publication.py tests/unit/test_fulfillment_service.py tests/unit/test_domain_runtime_wiring.py tests/unit/test_architecture_imports.py tests/unit/test_settlement_start_authority.py tests/unit/test_migrations.py tests/unit/test_failure_policy.py tests/integration/ -q)
(cd domains/bare_metal/buyer && uv run --no-sync pytest tests/test_buyer_composition.py -q)
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_selection_dispatch.py tests/test_negotiation.py tests/test_domain_runtime.py tests/test_settlement.py tests/test_migrations.py tests/test_persistence.py tests/test_escrow_identity_backfill.py tests/test_fulfillment_service.py tests/test_site_clients.py tests/test_import_boundaries.py tests/test_http_settlement.py tests/test_http_negotiation.py tests/test_http_introductions.py tests/test_introduction_delivery.py tests/test_app_composition.py -q)
(cd domains/apicredits/buyer && uv run --no-sync pytest tests/test_settlement_composition.py tests/test_settle_credentials.py tests/test_negotiation_flow.py tests/test_listing_helpers.py tests/test_plugin_export.py -q)
(cd domains/apicredits/storefront && uv run --no-sync pytest tests/unit/test_selection_dispatch.py tests/unit/test_sync_negotiation.py tests/unit/test_domain_runtime.py tests/unit/test_server_composition.py tests/unit/test_settlement_fulfillment.py tests/unit/test_concept_modules.py tests/unit/test_issuance_evidence_repository.py -q)
(cd domains/apicredits && uv run --no-sync pytest tests/test_credits_client.py tests/test_credits_client_http.py tests/test_issuance_evidence.py -q)
(cd domains/apicredits/service && PYTHONPATH=src uv run --no-sync pytest src/tests/unit/test_keys_service.py src/tests/unit/test_api.py src/tests/unit/test_migrations.py -q)
make -C kit/arkhai-payments typecheck check-vectors check-generated test-unit
# Isolated slices repeat the overlapping primary groups.
(cd domains/vms/storefront && ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --no-sync pytest tests/integration/test_settle_controller.py tests/integration/test_negotiate_controller.py tests/integration/test_storefront_client.py -q)
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_http_settlement.py tests/test_http_negotiation.py tests/test_http_introductions.py -q)
(cd domains/apicredits && uv run --no-sync pytest tests/test_credits_client_http.py -q)
(cd domains/apicredits/service && PYTHONPATH=src uv run --no-sync pytest src/tests/unit/test_api.py -q)
(cd domains/vms/storefront && ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --no-sync pytest tests/unit/test_migrations.py tests/unit/test_fulfillment_resume_runtime.py -q)
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_migrations.py tests/test_persistence.py -q)
(cd domains/apicredits/storefront && uv run --no-sync pytest tests/unit/test_settlement_fulfillment.py -q)
(cd domains/apicredits/service && PYTHONPATH=src uv run --no-sync pytest src/tests/unit/test_migrations.py -q)
uv run --project domains/vms/storefront --locked --find-links .dist --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" --with "$PWD/.dist/arkhai_kit_arkhai_payments-0.1.0-py3-none-any.whl" python domains/vms/storefront/examples/payment_smoke.py
(cd domains/apicredits/service && PYTHONPATH=src uv run --project . --find-links ../../../.dist --with arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-domain python ../../../docs/attachments/apicredits-dispatch/first_use.py)
uv pip install --python domains/bare_metal/buyer/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_buyer-0.1.4-py3-none-any.whl
uv pip install --python domains/bare_metal/storefront/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_storefront-0.2.5-py3-none-any.whl
domains/bare_metal/buyer/.venv/bin/python docs/attachments/baremetal-dispatch/inspect_wheels.py buyer
domains/bare_metal/storefront/.venv/bin/python docs/attachments/baremetal-dispatch/inspect_wheels.py seller
domains/vms/storefront/.venv/bin/python docs/attachments/route-settlement-closeout/inspect_vm_schema.py
PYTHONPATH=domains/apicredits/service/src domains/apicredits/service/.venv/bin/python docs/attachments/route-settlement-closeout/inspect_credits_schema.py
domains/bare_metal/storefront/.venv/bin/python docs/attachments/route-settlement-closeout/reclaimed_gate.py
# Reinit can churn locks (#257). Review and restore only generated lock changes;
# do not discard deliberate dependency edits or resync before reading evidence.
