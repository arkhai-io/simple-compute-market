#!/usr/bin/env bash
# Run from the repository root; controlled buyer/library checks only.
set -euo pipefail
make dist
make -C core/buyer reinit
(cd core && uv sync --dev --find-links ../.dist --reinstall)
(cd core/buyer && uv run --no-sync pytest tests/unit/test_orchestrator.py tests/unit/test_settlement_acceptance.py tests/unit/test_settlement_policy.py tests/unit/test_priceless_options.py tests/unit/test_identity_recovery.py -q)
make -C domains/vms/buyer reinit
(cd domains/vms/buyer && uv run --no-sync pytest tests/test_buy_orchestrator.py::test_payment_dispatch_and_run_recovery_ignore_stray_escrow -q)
make -C core typecheck-core
make check-comment-hygiene
openspec validate route-settlement-by-mechanism --strict
# Reinit can churn tracked locks (#257); restore generated changes only after
# reading the results, without discarding fresh local wheel installations.
