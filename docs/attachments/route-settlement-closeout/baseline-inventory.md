# Settlement dispatch baseline inventory

Planning inventory preserved from the active design before final narrative compression. This is change history, not current architecture; [final-inventory.md](final-inventory.md) is the final control-flow judgment.

## Branch inventory

Inventory at base `331768160ba5528634aefd75b09ef89efe742918`: search `core/` and `domains/` for the requested IDs/constants and `accepted_escrow_proposal`, excluding `.venv`, `build` and tests; inspect executable comparisons, then check aliases such as `ALKAHEST_MECHANISM` and the funding-gate map. Tests, literals/defaults, help examples and generic equality between selected and advertised IDs are not concrete-mechanism dispatch.

There are **50 concrete-ID comparison sites in 26 production files**: **23 T** (table-owned composition/admission hooks), **14 E** (evidence/issuance-authorization reads, including deleting compatibility fallback), **13 M** (mechanism-owned validation inside a stage). The map in `prepare_credit_issuance_request` is one additional E dispatch site with two ID keys, not a comparison. The first-pass accepted-proposal comparison scan finds **23 directly spelled None checks**: one T dispatch, eleven M stage/materialization guards and eleven carrier-projection guards. Alias/type-test sites are classified below separately, including the VM acceptance-artifact shape branch. A comparison spanning several source lines counts once; carrier parsing is not settlement dispatch.

Paths below abbreviate package roots, not ownership:

| File | Concrete comparisons | Disposition |
|---|---:|---|
| `core/buyer/src/core_buyer/negotiation_client.py` | 1 | T: Alkahest-only missing-plan validation becomes a selected entry's acceptance validator; keep generic exact-Agreement checks |
| `domains/apicredits/buyer/buy_cli.py` | 1 | T: buy settlement dispatch |
| `domains/apicredits/buyer/deal_helpers.py` | 1 | M: accepted Alkahest-obligation decode belongs in that stage |
| `domains/apicredits/buyer/payments.py` | 4 | T: registration selection; M x3: payment-only option/mandate checks |
| `domains/apicredits/buyer/settle_cli.py` | 1 | T: accepted-run dispatch |
| `domains/apicredits/service/src/services/keys_service.py` | 3 | E: remove mechanism allowlist, escrow alias and legacy Alkahest replay adoption; consume authorization |
| `domains/apicredits/settlement/fulfillment.py` | 3 + gate map | E: common issuance uses evidence; retry policy is supplied by the stage and post-issuance attestation/compensation returns to the Alkahest continuation |
| `domains/apicredits/settlement/payments.py` | 2 | M: payment clause and mandate validators |
| `domains/apicredits/storefront/src/apicredits_storefront/controllers/settle_controller.py` | 6 | T x2: dispatch/refusal; E x2: status/re-drive and reference projection; M x2: request/Agreement validation moves into payment stage |
| `domains/apicredits/storefront/src/apicredits_storefront/negotiation_runtime.py` | 3 | T: acceptance input validation, mandate construction and quota-hold hook |
| `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py` | 3 | T: Alkahest readiness inputs/client construction and payment clause validation are table-entry hooks |
| `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/arkhai_payments.py` | 1 | M: payment Agreement guard |
| `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py` | 1 | T: supported buyer stage, not a hardcoded payment-only branch |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/arkhai_payments.py` | 1 | M: payment option guard |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py` | 2 | T: resources for the enabled Alkahest entry, no implicit default |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_service.py` | 2 | T: verify dispatch; E: delete chain-name-sentinel status fallback |
| `domains/vms/buyer/arkhai_payments.py` | 2 | M: payment Agreement guard and payer selection |
| `domains/vms/buyer/settle_cli.py` | 2 | T: accepted-run dispatch and unsupported refusal |
| `domains/vms/storefront/src/market_storefront/arkhai_payments.py` | 1 | M: payment option guard |
| `domains/vms/storefront/src/market_storefront/cli_publish.py` | 1 | T: Alkahest readiness-input projection |
| `domains/vms/storefront/src/market_storefront/controllers/settle_controller.py` | 2 | T: seller dispatch/refusal |
| `domains/vms/storefront/src/market_storefront/negotiation_runtime.py` | 1 | T: accepted mandate hook |
| `domains/vms/storefront/src/market_storefront/services/fulfillment_resume_runtime.py` | 2 | E: source revalidation moves to the selected stage; delivery follows validated evidence and stage continuation |
| `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_planner.py` | 2 | E: stage-supplied lease/condition encoding, no ID switch |
| `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py` | 1 | E: delivery result returns to stage-owned completion |
| `domains/vms/storefront/src/market_storefront/settlement_composition.py` | 1 | T: Alkahest readiness-input hook |

Accepted-proposal guards by file:

- T x1: `core/buyer/src/core_buyer/orchestration.py:make_settle_hook` dispatch goes. M x1: `_settle_one` checks its own required input, reachable only from an explicit stage.
- M x10: API-credit `buyer/deal_helpers.py` (1), `buyer/settle_cli.py` (1); VM `buyer/deal_helpers.py` (1), `buyer/escrow_cli.py` (3), `buyer/settle_cli.py` (3), `negotiation/policies.py` (1). Keep/move these within Alkahest materialization or the existing namespaced raw Alkahest utility, never use them to select settlement.
- Carrier projection x11: core buyer `negotiation_client.py` (1), `orchestration.py` (1); API-credit buyer `buyer_client.py` (2), `negotiate_cli.py` (1), storefront `negotiation_runtime.py` (1); VM buyer `buyer_client.py` (2), `buy_cli.py` (1), `negotiate_cli.py` (1), storefront `negotiation_runtime.py` (1). These serialize/decode an optional existing field; they do not choose a mechanism and remain opaque.

Alias/type-test follow-up:

- T: VM storefront `negotiation_runtime.py:_build_response_artifacts` chooses escrow-artifact construction from `isinstance(proposal, Mapping)`. Bind that construction to its Alkahest entry; retain the existing flat-wire coercion that resolves the selected mechanism, not an escrow-presence settlement fallback.
- M: VM/API-credit `buyer/settle_cli.py:_accepted_proposal_chain` and VM `buyer/escrow_cli.py` proposal dictionaries are Alkahest-owned field readers. API-credit/VM `negotiation/policies.py` accepted-proposal dictionary guards are materialization/projection within the existing legacy acceptance adapter; they do not authorize delivery.
- Carrier: core buyer `negotiation_client.py:parse_accepted_terms_from_reply` checks the `raw_esc` dictionary solely to decode an optional field. `deal_helpers.py`'s two captured-proposal blocks validate presence, dictionary shape and transcript consistency; keep these fail-closed parsing checks, not mechanism choices.

The second pass also found mechanism-specific typed allowlists/defaults in API-credit `settlement/credits_client.py`, service `models/keys_model.py` and `db/migrations.py`; remove them with the authorization/grant rewrite. The existing declarations in bare-metal `settlement_composition.py` become its table, not extra registries. Core `schemas.py` flat-escrow coercion, `core_storefront/escrow_identity.py` backfill, VM `publication_migration.py`, raw escrow commands, and field-presence/transcript consistency checks are existing carrier/Alkahest compatibility surfaces, not new dispatch: retain them for the explicitly out-of-scope carrier/wire work. No contact-ID comparison was found outside kits; its supported seller entry and fused evidence handoff still have to survive composition.