# Joined production inventory

Base `66d83b9f`. Production Python under `core/` and `domains/`; exclude `.venv`, `build`, `tests`, and `__pycache__`. Literal grep plus Python AST comparison/type-test scan, followed by caller/control-flow reading. T = declaration/admission hook; E = downstream evidence/authorization; M = owned mechanism guard. Carrier projections are explicitly deferred, not T/E dispatch.

## Concrete comparisons

The requested payment/Alkahest equality scan still finds **11** sites. Each is listed here; no core site remains.

| Production file / line | Class and actual control flow |
|---|---|
| `domains/apicredits/buyer/payments.py:68` | T: payment candidate filter invoked by `PaymentBuyerStage.select` |
| same `:80` | M: payment-only helper's non-preferred selection validation; current entry uses `prefer_payment=True` |
| same `:99` | M: accepted payment mandate policy |
| same `:150` | M: payment execution's selected-input guard |
| `domains/apicredits/settlement/payments.py:25` | M: payment publication clause validator, entry-owned hook |
| same `:47` | M: payment Agreement policy validator |
| `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/arkhai_payments.py:49` | M: payment acceptance guard |
| `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/arkhai_payments.py:38` | M: payment option guard |
| `domains/vms/buyer/arkhai_payments.py:73` | M: payment approval Agreement guard |
| same `:167` | M helper guard, **but generic standalone negotiation also calls it directly** (finding F2) |
| `domains/vms/storefront/src/market_storefront/arkhai_payments.py:38` | M: payment option guard |

Expanded AST scan also finds four contact comparisons omitted by the original payment/Alkahest pattern:

- bare-metal buyer `cli.py:242,435`: M in explicit `introductions` recovery/request utilities, not generic `buy` dispatch.
- bare-metal storefront `introduction_routes.py:43`: M in the dedicated authenticated introduction surface's accepted-plan validator.
- bare-metal storefront `api.py:179`: contact-route configuration availability guard, not generic financial/physical dispatch. It consults current enablement; disabled-contact accepted reveal/re-read is not proved by the existing first-use drive. Review should reconcile this with the accepted-recovery contract before claiming that lane.

`selected['mechanism'] != self.mechanism` checks in VM seller stage methods are M, and repository comparisons against a previously stored mechanism or the accepted Agreement are identity-conflict protection, not concrete dispatch.

**Renamed branch found:** `domains/vms/buyer/negotiate_cli.py:381–417` calls `payer_selection` directly then branches on `selected_settlement.registration.config_key == 'alkahest'` to choose escrow parsing, policy validation, chain/wallet inputs and token scaling. At `:541–551`, `picked_entry is None` chooses selection vs escrow construction. This is not an opaque carrier projection: it selects prerequisites and request construction before negotiation. Fresh `buy` and accepted-run `settle` are table-routed; standalone `market negotiate` is not fully table-routed. Inventory acceptance is therefore **not clean**, despite the 11-site literal result.

## All accepted-proposal presence checks

The AST scan finds **31 None comparisons including aliases: 17 M and 14 carrier projections**. No T dispatch remains in core. The following grouped list covers every comparison, including alias checks excluded by a literal attribute grep. Line numbers are on the tested base.

| Production file | Presence sites | Disposition |
|---|---|---|
| core buyer `deal_helpers.py` | 351,357,769,775 | carrier: raw optional field capture plus conflict-protected prior capture |
| core buyer `negotiation_client.py` | 233 | carrier serialization |
| core buyer `orchestration.py` | 652;839 (`accepted_proposal`) | carrier; M in explicit `_settle_one`, no default dispatch |
| API-credit buyer `buyer_client.py` | 58,94 | carrier serialization/model projection |
| API-credit buyer `negotiate_cli.py` | 611 | carrier run-log projection |
| API-credit buyer `settle_cli.py` | 249 | M inside selected `_alkahest` execution closure |
| API-credit buyer `settlement_stages.py` | 62,68 | M accepted Alkahest requirement/enrichment |
| API-credit `negotiation/policies.py` | 179,186 (`accepted_proposal_dict`) | M legacy materialization/projection adapter; does not authorize issuance |
| API-credit storefront `negotiation_runtime.py` | 520 (`accepted_proposal`) | carrier response projection on nonaccepted rounds |
| VM buyer `buyer_client.py` | 116,209 | carrier serialization/model projection |
| VM buyer `buy_cli.py` | 229 | carrier resumed negotiation recording |
| VM buyer `negotiate_cli.py` | 624 | carrier run-log projection (distinct from F2) |
| VM buyer `escrow_cli.py` | 409,471,517 | M namespaced raw Alkahest utility |
| VM buyer `settlement_stages.py` | 85,115,309,333,392 | M selected Alkahest acceptance/enrichment/recovery |
| VM `negotiation/policies.py` | 194,196,200 | M legacy accepted-proposal materialization/projection adapter |

Additional shape/alias checks read directly:

- Core buyer `deal_helpers.py:352,770` dictionary guards and `:358,776` transcript equality are carrier parsing/conflict protection. `negotiation_client.py:296,298` decode `raw_esc` only.
- Core storefront `sqlite_client.py:2423` parses persisted `raw_proposal` strings, not dispatch.
- VM `escrow_cli.py:88,403` and both buyers' `_accepted_proposal_chain` dictionary readers are raw Alkahest field readers.
- API-credit seller `settlement_stages.py:198–200` accepted-artifact shape belongs to its Alkahest builder.
- VM seller `negotiation_runtime.py:619–637` retains the nonaccepted-round proposal shape branch; `_accepted_settlement_artifacts` resolves the table via `resolve_proposal_stage`, whose flat-wire Alkahest coercion is explicitly deferred. Accepted response data independently resolves the Agreement-selected entry. This branch does not authorize delivery.
- Domain legacy round-zero policies materialize optional flat proposals, while selected settlement carriers resolve through their registrations/table entries. These are retained carrier/wire compatibility adapters, not common delivery gates.

## Original 23 T sites

Core acceptance now invokes the selected entry validator; core dispatch and admission use the immutable table. API-credit buy/accepted-run CLI calls buyer entries; seller controller `_context` selects the accepted Agreement's entry; negotiation calls entry selection/artifact/hold hooks; readiness/client construction lives on entries. Bare-metal buyer purchase uses its payment table; seller runtime obtains entry resources; settlement service selects the Agreement stage. VM buyer buy/settle and seller controller/accepted-data/readiness/publication use entries. The extra standalone VM negotiation path above fails the same invariant even though it was absent from the original concrete-ID equality count.

## All original 14 E sites and the gate map

| Original E owner / number | Joined control flow |
|---|---|
| credits `keys_service.py` / 3 | mechanism allowlist, escrow grant alias and legacy adoption removed; neutral immutable authorization/key/quota reads only |
| API-credit `settlement/fulfillment.py` / 3 plus authoritative-gate map | versioned `credit_delivery(evidence)` → neutral `CreditIssuanceRequest.create`; stage supplies retry policy; no mechanism-keyed gate map, common attestation or compensation |
| API-credit seller controller / 2 | negotiation/public-ref progress read; `_context` picks accepted stage, nonterminal status calls its `redrive`; public/private projection independent of mechanism |
| bare-metal settlement service / 1 | chain sentinel fallback removed; verified negotiation evidence only; selected entry revalidation precedes physical calls, **but Alkahest's gate checks only local materialization journal (F1)** |
| VM resume runtime / 2 | persisted Agreement → seller stage → `recover_evidence` before `converge_delivery_once`; selected continuation/failure policy supplied transiently |
| VM planner / 2 | verifies supported delivery-facts envelope then uses stage-supplied lease/condition/terms; no receipt decode or mechanism comparison |
| VM physical service / 1 | evidence planner/common physical result; entry continuation owns attestation/claim binding |

Physical/credit pseudo-escrow handoffs are gone. Runtime storefront carriers pass evidence plus neutral reference. Bare-metal's transient `read_verified_evidence` callback is reconstructed by the settlement boundary, not serialized. VM delivery uses negotiation-scoped records/context/claims and no escrow-context discovery fallback; API-credit issuance uses negotiation progress and separate private/signed result storage. Genuine Alkahest rows and shared/public escrow-named DTO/correlation fields remain deferred, including the credits quota ledger's neutral fulfillment correlation.

## Recovery gate judgment

VM Alkahest calls its escrow verifier on recovery; payment validates exact persisted Agreement/digest/mandate/ref and trusted receipt before physical recovery. API-credit payment polls and verifies a receipt before nonterminal issuance replay; Alkahest re-prepares/verifies before issuance/attestation, which remain stage-owned. Bare-metal payment re-derives the accepted mandate and verifies the persisted signature; begin/status/access/teardown route through that reader. Bare-metal Alkahest checks only journal materialization identity, ignoring terminal reclaim/status: F1 prevents confirmation of 6.2. Common planners/issuance themselves are evidence-only as required; source revalidation is not established merely by that structural result.
