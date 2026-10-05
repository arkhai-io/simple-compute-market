#!/usr/bin/env bash
# Run after replay.sh from the repository root; all state is temporary.
set -euo pipefail
bash docs/attachments/core-settlement-closeout/replay.sh
bash docs/attachments/vm-settlement-findings/replay.sh
make -C domains/apicredits/buyer reinit
make -C domains/apicredits/storefront reinit
make -C domains/apicredits/service reinit
(cd domains/apicredits/storefront && uv run --no-sync pytest tests/integration/test_payment_recovery.py tests/unit/test_settlement_fulfillment.py tests/unit/test_issuance_evidence_repository.py -q)
(cd domains/apicredits/buyer && uv run --no-sync pytest tests/test_settlement_composition.py tests/test_settle_credentials.py tests/test_negotiation_flow.py tests/test_listing_helpers.py tests/test_plugin_export.py -q)
(cd domains/apicredits && uv run --no-sync pytest tests/test_credits_client.py tests/test_credits_client_http.py tests/test_issuance_evidence.py -q)
(cd domains/apicredits/service && PYTHONPATH=src uv run --no-sync pytest src/tests/unit/test_api.py -q)
(cd domains/apicredits/service && PYTHONPATH=src uv run --project . --find-links ../../../.dist --with arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-domain python ../../../docs/attachments/apicredits-dispatch/first_use.py)
make -C domains/bare_metal/storefront reinit
uv pip install --python domains/bare_metal/storefront/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_storefront-0.2.5-py3-none-any.whl
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_http_settlement.py tests/test_fulfillment_service.py tests/test_settlement.py -q)
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_domain_runtime.py tests/test_app_composition.py -q)
(cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_http_settlement.py -k alkahest_recovery -q)
domains/bare_metal/storefront/.venv/bin/python docs/attachments/route-settlement-closeout/reclaimed_gate.py
core/.venv/bin/python docs/attachments/route-settlement-closeout/inspect_dispatch.py
make check-comment-hygiene
