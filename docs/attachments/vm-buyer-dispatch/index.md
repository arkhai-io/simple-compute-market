# VM buyer settlement dispatch — implementation evidence

Code revision: `81eff1d5` (dispatch in `caeea481`; run-log metadata repair in `b6ca3968`). Scope: task 2.1 of `route-settlement-by-mechanism`. These are implementation self-checks, not independent acceptance or live payment/VM qualification.

## Setup and replay

Required/prepared target: checkout-local buyer library and CLI composition, owned by the `vm-buyer-dispatch` worktree. Internal dependencies are rebuilt into `.dist` and reinstalled through the buyer's `reinit` target. Wheel/import inspection finds `settlement_stages.py` in the buyer wheel, and the installed plugin exposes the identical buyer table used for admission and dispatch. No service deployment or external credential is required for this controlled lane.

Tests use deterministic Ed25519 marketplace signers, public synthetic payment accounts/policy, injected publisher trust, signed seller HTTP responses and temporary v3 run-log directories. The payment approval method is replaced at the domain's external approval seam; this lane does not measure receipt verification, the live ledger or physical delivery. The approval/receipt checks in `VmArkhaiPaymentsBuyer.approve` are unchanged. Temporary run logs are removed by pytest; no server, browser, container or external target remains running.

From the repository root, this command prepares and opens the fresh/payment-recovery surface:

```sh
make dist && make -C domains/vms/buyer reinit && (cd domains/vms/buyer && uv run --no-sync pytest tests/test_buy_orchestrator.py::test_payment_dispatch_and_run_recovery_ignore_stray_escrow -q)
```

The replay invokes the VM settlement hook for fresh accepted work, then drives the actual `market settle --from <run>` command through Typer with the persisted exact Agreement and mandate. It runs both without an escrow proposal and with a stray one. No ignored setup file is needed.

## Observed boundaries

- Payment dispatch selects the payment entry in both variants, without wallet or chain resolution. Fresh and resumed approval receive byte-identical accepted Agreement bytes and the same mandate.
- Changing admission priority to Alkahest and disabling payment for new work does not redirect accepted payment recovery.
- Existing Alkahest flows retain escrow creation, signed seller submission, retry classification and polling. Recovery with an existing escrow skips creation and preserves the accepted SSH key after configuration rotation.
- Missing accepted support is refused before chain resolution. An Alkahest run with no existing escrow and no accepted artifacts is refused rather than synthesizing a proposal from current configuration.
- Recovery can derive the Agreement projection from its persisted bytes, but compares negotiation, listing, buyer and any existing projection before entry lookup. Payment entries do not decode stray Alkahest artifacts as authoritative inputs.
- The CLI replay found that `settle_resumed` overwrote reserved `run_id` metadata. The separate repair leaves that identity to `RunLog` and makes real v3 replay usable.

## Validation

After final `make dist` and consuming `make -C domains/vms/buyer reinit`:

```sh
cd domains/vms/buyer
uv run --no-sync pytest tests/test_buy_orchestrator.py tests/test_vm_settlement_helpers.py tests/test_buy_resume_cli.py tests/test_resume_helpers.py tests/test_plugin_export.py tests/test_buyer_client.py tests/test_buyer_client_resume.py tests/test_buy_pricing_and_filters.py tests/test_aggregation_policy.py tests/test_explain_cli.py tests/test_settlement_config_template.py tests/test_config_migration_cli.py -q
```

**101 passed.** `make check-comment-hygiene` and diff whitespace checks passed. The VM buyer has no declared static typecheck target. No core or storefront file changed.

Touched-import review retained one function-local table import in `deal_helpers.py`: moving it to module scope was tried and the plugin suite failed collection with a concrete `settlement_composition → settlement_stages → deal_helpers → settlement_composition` cycle. Restoring the deferred import made the final suites pass. Mechanism comparisons in the affected buyer production paths now remain only in the declaration or the owned payment/raw Alkahest utilities; optional carrier projections remain.

Initial consumer runs exposed the expected core signature cutover and fixtures lacking declared Agreement options. Fixtures now supply supported options without removing their existing behavioral assertions. The new controlled replay initially lacked injected registry trust, then exposed byte-only recovery and the reserved-metadata defect; the final run has no failures.

Seller evidence/progress separation, receipt-gated physical delivery, exact-once provisioning, live complete-deal qualification and post-review VM documentation promotion remain with tasks 2.2–2.6. Existing permanent destinations are the buyer-orchestration stage/recovery contract and architecture, plus the VM fulfillment and physical-provisioning destinations named in the change design. No visual evidence applies to this CLI/library boundary.
