# API-credit dispatch — implementation evidence

Buyer code: `9b3fc2f5`. Storefront/common issuance code: `38285a62`. These are implementation self-checks, not independent acceptance or live ledger qualification.

Buyer and seller settlement now use their declared Agreement-selected stages. Negotiation-bound source evidence and issuance progress are independent of real Alkahest escrow rows, signed issuance evidence and private credentials. Common issuance consumes verified evidence and the neutral typed authorization; Alkahest owns its later attestation and compensation.

## Required and prepared targets

The controlled first-use target is checkout-owned, in-process library/HTTP composition: actual storefront repositories, the credits FastAPI application, its quota ledger and file-backed temporary SQLite databases. It seeds a 100-unit `svc-quota` resource and two accepted Agreements for synthetic buyer/seller principals. Credits `/health` returned 200 before effects.

Only payments I/O is controlled: a timeout followed by a synthetic signed receipt. The installed payment kit verifies that signature against the exact mandate and Agreement. This is not a live payments service, wallet or ledger. Storefront HTTP authentication and buyer CLI orchestration are covered separately by existing focused suites; this joined drive uses the seller-stage library surface and the real `CreditsServiceClient` over ASGI.

No inherited deployment selector is reused. The script creates both databases under its own `TemporaryDirectory`, reopens storefront persistence during recovery, disposes the credits engine and removes the directory. No server, browser, tunnel or external resource remains.

Authentication uses synthetic marketplace signers and an ephemeral operator key supplied through `APICREDITS_STOREFRONT_ADMIN_KEY`. The script selects its own `APICREDITS_DATABASE_URL`, clears `APICREDITS_STOREFRONT_ADMIN_KEY_FILE`, and publishes no bearer secret. No external credential is required.

## First-use entry

From the repository root, this is the preparation and entry command exercised on the code revisions above:

```sh
make dist &&
make -C domains/apicredits/buyer reinit &&
make -C domains/apicredits/storefront reinit &&
make -C domains/apicredits/service reinit &&
(cd domains/apicredits/service &&
 PYTHONPATH=src uv run --project . --find-links ../../../.dist \
   --with arkhai-apicredits-storefront \
   --reinstall-package arkhai-apicredits-storefront \
   --reinstall-package arkhai-apicredits-domain \
   python ../../../docs/attachments/apicredits-dispatch/first_use.py)
```

[`first_use.py`](first_use.py) is committed setup and a controlled self-check, not an additional permanent acceptance suite. Explicit `--project .` and the `python` invocation retain the service dependency environment; passing the script itself to `uv run` initially selected the repository project and could not import `market_site`.

Reinit can rewrite unrelated dependency resolution. After running, restore only generated lock churn without reverting installed wheels; this is tracked in [#257](https://github.com/arkhai-io/simple-compute-market/issues/257).

## Observed claims

| Action | Observed result |
|---|---|
| Settle with a pending payment and try common issuance directly | Progress remains provisioning; unverified evidence is refused; zero grants |
| Verify a signed receipt, commit issuance, then lose its acknowledgement | One grant exists; storefront remains provisioning |
| Reopen storefront persistence and re-drive | Receipt revalidated, same grant replayed; new-key buyer secret retrievable |
| Project that private result for another principal | Refused |
| Issue a two-unit top-up on the buyer's existing key | Two total grants, balance five; top-up exposes no secret |
| Retry the completed original purchase | Grant and balance unchanged |
| Inspect fresh schema | Negotiation-primary-key source evidence, unique established reference, separate issuance progress and private storage; zero payment escrow rows |

The final [SQL/column and result snapshot](first-use-result.json) records source-revalidation count, table definitions and cleanup. Schema bootstrap and reopen use the introducing migrations without copy/adopt/drop or a historical escrow fallback. A stored mechanism, Agreement digest, established reference or delivery-input change conflicts in the repository. Payment recovery polls and verifies its source before issuing; Alkahest's prepared continuation re-verifies before issuance/attestation. The common issuance gate contains no mechanism allowlist or mechanism-keyed authoritative-gate map.

Alkahest's focused suite preserves accepted-obligation validation, ready-progress recovery, serialized concurrent retries, signed issuance publication and post-issuance balance compensation/new-key revocation. Existing coverage was adapted to accepted Agreements, neutral issuance and independent progress; the ready historical-escrow fixture now seeds ready issuance progress. Historical escrow-only adoption is deliberately unsupported, not silently retained.

## Focused validation

Fresh internal wheels and consumer reinstalls passed. Wheel inspection confirmed buyer `settlement_stages.py` and storefront `settlement_stages.py` / `settlement_repository.py` are packaged.

- Buyer: **17 passed** across `test_settlement_composition.py`, `test_settle_credentials.py`, `test_negotiation_flow.py`, `test_listing_helpers.py`, `test_plugin_export.py`.
- Storefront: **58 passed** across unit `test_selection_dispatch.py`, `test_sync_negotiation.py`, `test_domain_runtime.py`, `test_server_composition.py`, `test_settlement_fulfillment.py`, `test_concept_modules.py`, `test_issuance_evidence_repository.py`.
- Domain/client: **25 passed** across `test_credits_client.py`, `test_credits_client_http.py`, `test_issuance_evidence.py`.
- Credits service's actual typed-client HTTP suite `src/tests/unit/test_api.py`: **3 passed**.
- `make check-comment-hygiene`, strict OpenSpec validation and `git diff --check`: passed. All added production imports are module-level; leftover function imports are pre-existing. Unused mechanism imports removed from changed composition/orchestration modules.
- These API-credit packages declare no static typecheck target or `py.typed` marker; no static typing result is claimed.
- Existing Pydantic `schema` field-shadowing warnings remain in shared client/evidence DTOs; tracked in [#259](https://github.com/arkhai-io/simple-compute-market/issues/259).

Focused reproduction after the entry's build/reinit:

```sh
(cd domains/apicredits/buyer &&
 uv run --no-sync pytest tests/test_settlement_composition.py tests/test_settle_credentials.py tests/test_negotiation_flow.py tests/test_listing_helpers.py tests/test_plugin_export.py -q)
(cd domains/apicredits/storefront &&
 uv run --no-sync pytest tests/unit/test_selection_dispatch.py tests/unit/test_sync_negotiation.py tests/unit/test_domain_runtime.py tests/unit/test_server_composition.py tests/unit/test_settlement_fulfillment.py tests/unit/test_concept_modules.py tests/unit/test_issuance_evidence_repository.py -q)
(cd domains/apicredits &&
 uv run --find-links ../../.dist pytest tests/test_credits_client.py tests/test_credits_client_http.py tests/test_issuance_evidence.py -q)
(cd domains/apicredits/service &&
 PYTHONPATH=src uv run --find-links ../../../.dist pytest src/tests/unit/test_api.py -q)
```

## Join and remaining qualification

Section 5's authorized client/service commit `5485d730`, evidence `8f575aa2` and dev setup `38617332` are included as `b7e74462`, `144708ea` and `17e38b8f`. No independent edits were made to section 5-owned code. Core boundary docs are included as `03134062` and `f6e0b230`.

No owned ready live storefront/payments/API execution target was supplied. The deployed complete-deal entry `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py` was not run; readiness must be established for storefront, credits, payments and quota authorities first. Independent drive/review and post-review permanent promotion remain with the joiner. Promotion destinations and explicit database-reset instructions are in the active change's design. No visual evidence applies.
