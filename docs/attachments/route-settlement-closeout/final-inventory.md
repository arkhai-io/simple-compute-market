# Final joined production inventory

Audited production: campaign `4d04fbf7`; closeout import/comment-only repair `2d22f6e4`. Scope: tracked Python under `core/` and `domains/`, excluding tests, examples, `.venv`, build, caches and docs. `inspect_dispatch.py` scans comparisons and generic conditional/type paths for mechanism/config-key, proposal, chain and settlement-data vocabulary; caller reads distinguish dispatch from identity checks and carrier projections. The original 50-site T/E/M map is preserved in [baseline-inventory.md](baseline-inventory.md); the prior audit is [inventory.md](inventory.md).

## Result: 8.2 does not hold

The original VM finding is repaired, but the broadened inventory finds an equivalent API-credit standalone path. Accepted contact recovery also still depends on current enablement. These are behavioral findings, not mechanical breakage; closeout does not repair them or tick 8.2.

### B1 — API-credit standalone negotiation bypasses the declared buyer table

`domains/apicredits/buyer/negotiate_cli.py:165–189` unconditionally resolves a wallet and refuses without an EVM address. At `:340–400` it directly selects chain/`accepted_escrows`, calls Alkahest token resolution and scales explicit prices. At `:543–561` it directly constructs an escrow proposal. This is the normal `market credits negotiate` command, including its `--from` surface, not the namespaced raw escrow utility. It has no `buyer_stage`/supported-table lookup. Payment-only listings and wallet-free negotiation cannot follow the declared payment entry. No new CLI test was added and no live payment run is claimed: this finding is direct production control-flow inspection. Existing buy/settle focused tests pass because they exercise different surfaces.

### B2 — accepted contact reveal/re-read is disabled with fresh admission

`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:176–194`, `_introduction_service`, checks `CONTACT_MECHANISM in composition.enabled_mechanisms` and returns 404 otherwise. Both POST introductions and GET an established `obligation_ref` (`:198–217`) use that factory, before the persisted accepted binding can be resolved. A retained declared seller stage is therefore insufficient to re-read accepted contact work after disabling new publication. This guard was already visible in the prior expanded inventory but was not assigned a repair. Current enabled-contact HTTP suites do not qualify disabled-contact recovery. No chain/payment/physical effect is alleged.

## Literal and proposal inventory

The payment/Alkahest concrete equality scan still has 11 sites, all inside owned stages/helpers: API-credit buyer `payments.py` (candidate filtering, option/mandate/execution guards), domain `settlement/payments.py` (clause/mandate validation), bare-metal buyer/seller payment helpers, VM buyer payer/approval helpers and VM seller payment option validation. None remains in core. Four contact comparisons are in the explicit introductions utility, accepted-plan validator and route availability factory; the last is B2, not accepted-state dispatch.

All accepted-proposal presence/shape checks were re-read, including aliases. Core `deal_helpers`, negotiation serialization and `_settle_one` respectively retain carrier conflict checks, optional wire projection and an explicitly bound Alkahest helper guard. VM/API-credit buyer outcome serializers, run-log projections, raw escrow commands, selected Alkahest enrichment/recovery and legacy policy materialization retain their corresponding carrier/M checks. VM standalone negotiation now delegates `prepare_selection`, `accepted_entry`, `negotiation_prices` and `proposal` to `selected_stage`; its final type test only projects that returned carrier. Its config-key/payer/wallet/token branches are gone. VM seller `resolve_proposal_stage` requires explicit selection or exact accepted Agreement; no default Alkahest remains. API-credit standalone escrow selection is B1, not an allowed carrier projection.

Generic option/Agreement/mechanism equality is identity protection, not concrete dispatch. Shared flat-escrow coercion, escrow-identity backfill, publication migration, policy materialization and genuinely namespaced raw escrow utilities remain the explicitly deferred carrier/wire surfaces. Generic `registration.config_key` lookups select typed configuration, not a concrete stage. No renamed mechanism branch was found in common delivery or the credits authority.

## Original 23 T sites

Core admission/acceptance/settlement, VM buy/settle/negotiate and seller acceptance/settlement/publication, bare-metal purchase/seller resources/settlement, and API-credit buy/settle/seller acceptance/settlement/readiness/client construction resolve declared entries. The additional standalone API-credit negotiation path is B1. Registration alone never supplies support in the repaired table-routed paths.

## All original 14 E sites plus gate map

| Owner / sites | Final flow |
|---|---|
| Credits authority / 3 | Neutral immutable authorization, exact key/quota checks and grant replay; no mechanism allowlist, alias or old-grant adoption |
| Common credit issuance / 3 + gate map | Validated `credit_delivery(evidence)` builds neutral authorization; selected stage supplies retry policy and owns attestation/compensation |
| API-credit seller controller / 2 | Accepted Agreement selects stage; negotiation/reference progress and private result projection have no mechanism switch |
| Bare-metal settlement / 1 | No chain sentinel fallback; selected entry revalidates before begin/status/access/result/teardown. Alkahest now checks active journal plus current chain evidence/index |
| VM resume / 2 | Exact accepted Agreement selects `recover_evidence` before convergence; continuations/failure policy are transient selected-stage callbacks |
| VM planner / 2 | Validated supported delivery facts supply timing/lease/condition/terms, not receipt decoding or concrete IDs |
| VM physical delivery / 1 | Common physical result returns to the selected continuation; no mechanism switch |

Physical/credit pseudo-escrow handoffs and payment `insert_escrow` progress writes are absent. Domain source evidence is negotiation-keyed and immutable once verified; delivery/progress/private results are separate. Real Alkahest escrow servicing remains. No new copy/adopt/drop migration or sentinel was introduced. The shared quota ledger's escrow-named neutral fulfillment correlation is deferred to `move-escrow-into-alkahest/proposal.md`.

6.1 and 6.2 now hold for storage and protected physical/issuance gates: the original malformed VM evidence and reclaimed bare-metal journal diagnostics refuse, and the worker recovery suites pass. This does not make B1/B2 disappear or establish live ledger/hardware qualification.
