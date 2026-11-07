# Core settlement closeout repairs

Base: `49b9fff3`. Target: the `fix-core` checkout's rebuilt wheels and local buyer/library composition. These are implementation self-checks, not independent acceptance or live payment/physical-delivery qualification.

## F4 — remove unused buyer evidence plumbing

No buyer domain produces `SettlementEvidence`: the search for `SettlementEvidence|settlement_evidence` in `domains/vms/buyer`, `domains/apicredits/buyer` and `domains/bare_metal/buyer` returned no matches before the repair. Storefront/domain seller evidence is a separate, retained delivery boundary.

Removed the evidence field from `BuyResult` and `DealContext`, dispatcher event emission, and synthetic evidence recovery correlation/identity validation. Buyer recovery keeps opaque `settlement_ref`/applicable `escrow_uid`, exact Agreement bytes and domain settlement data. The change's core design, buyer delta and completed task description now reflect that boundary. Permanent buyer spec/architecture correction is left to joined closeout promotion, outside the assigned core/change-artifact file scope.

Proving surfaces:

- `core/buyer/tests/unit/test_identity_recovery.py::test_reference_recovery_retains_accepted_state` uses actual v3 run logs and `load_deal_context`: a recorded reference and exact retry recover the accepted Agreement/reference without an escrow; changed reference reuse is rejected. It replaces the synthetic buyer-evidence cases, which no longer describe supported buyer behavior.
- `core/buyer/tests/unit/test_orchestrator.py::test_settle_hook_delegates_exact_agreement_to_declared_domain_stage` exercises the public hook with absent/stray escrow proposals, unchanged domain outcome/result, and entry-owned events.

Preparation: `make dist`, `make -C core/buyer reinit` and `cd core && uv sync --dev --find-links ../.dist --reinstall` passed before suites. The five focused buyer files from the joined replay passed **51 checks** (the former 52 included four synthetic evidence cases, now three reference-recovery cases). The existing VM fresh/payment `market settle --from <run>` CLI replay passed **2 variants**, with and without a stray escrow proposal. Core mypy passed **6 files**; comment hygiene and strict OpenSpec change validation passed.

The checked target uses deterministic synthetic Ed25519 buyer/publisher personas, temporary v3 run logs, and injected publisher trust; no external credential or deployment selector is required. No server, browser, database or container was left running.

## F8 — core carrier coverage

`core/tests/unit/test_settlement.py` calls the public carrier exports directly. It checks duplicate/empty/whitespace mechanism rejection and absent-stage refusal, defensive snapshots for mapping and pair-list composition inputs, blocked mapping mutation, and `SettlementEvidence.validate_identity` refusal of changed negotiation, mechanism or established reference (including loss of the reference). The same identity validates before each changed-reuse attempt. No mechanism table declaration or concrete domain wiring is restated.

After another `make dist`, buyer reinit and core sync/reinstall, all **11 new carrier cases** and **15 existing carrier/domain-contract/import-boundary checks** passed (**26 total**). Core's unused `asyncio_mode` warning remains owned by [#258](https://github.com/arkhai-io/simple-compute-market/issues/258); it was not suppressed.

## Replay

The run rebuilt wheels, reinstalled consumers and opened the library/run-log recovery surface plus the existing VM `market settle --from <run>` CLI replay. [route-settlement-closeout/validation.md](../route-settlement-closeout/validation.md) records how to rerun validation on the current tree. The CLI replay seeds its own exact accepted Agreement/mandate and uses controlled approval/signed seller HTTP. It does not claim live receipt, ledger or physical-delivery qualification.

The complete run was re-driven successfully: **26 carrier/boundary**, **51 buyer**, and **2 CLI checks**, plus mypy, comment hygiene and strict change validation. These repeat the focused measurements above, not additional unique coverage. Final buyer/domain-buyer grep returned no `SettlementEvidence` or `settlement_evidence` matches. Generated lock changes were restored; all processes finished and no external resources remain.

Reinit lock churn remains owned by [#257](https://github.com/arkhai-io/simple-compute-market/issues/257). Restore only generated lock changes after execution, keeping the fresh installs; do not resync to restored locks before reading evidence.
