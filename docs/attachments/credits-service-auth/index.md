# Credits issuance authorization — implementation evidence

Tested revision: `5485d730`. Scope is the credits authority/client and grant storage. These are implementation self-checks, not independent acceptance or live payment qualification.

## Setup and first use

Required and prepared target: the real in-process credits HTTP application and SQLite database, owned by the `credits-service-auth` checkout. No inherited deployment selector, remote authority, browser or server is used. Tests install internal wheels from `.dist`, start the application's lifespan, observe `/health` returning 200, and exercise issuance through `CreditsServiceClient(transport=httpx.ASGITransport(app=main.app))`.

The deterministic seed is an empty in-memory database, quota resource `svc-quota` with 1000 API-credit units, and synthetic canonical buyer principals defined in `test_api.py`. Operator authentication uses the test fixture's `APICREDITS_STOREFRONT_ADMIN_KEY` through `X-Admin-Key`; no external secret is required. Test state is process-local and disappears on exit.

From the repository root, the entry used to prepare and open the issuance/replay surface is:

```sh
UV_DEFAULT_INDEX=https://pypi.org/simple make dist &&
UV_DEFAULT_INDEX=https://pypi.org/simple make -C domains/apicredits/service reinit &&
UV_DEFAULT_INDEX=https://pypi.org/simple make -C domains/apicredits/storefront reinit &&
(cd domains/apicredits/service &&
 PYTHONPATH=src UV_DEFAULT_INDEX=https://pypi.org/simple uv run --find-links ../../../.dist pytest src/tests/unit/test_api.py -q)
```

The service's dev dependency supplies the typed client wheel, and its `reinit` target explicitly upgrades/reinstalls that wheel. `UV_DEFAULT_INDEX=https://pypi.org/simple make -C domains/apicredits/service test` runs all 35 service tests without an extra dependency flag. Consumer reinstall completed, but the section 4 storefront producer/recovery join is not claimed here.

## Observed issuance/replay

- Typed submission of `neg-deal1` creates one key and one 3-unit grant. An unused retry returns the same key and grant, rotates the secret and leaves quota at 997.
- Read-only grant lookup returns no secret. After three consumptions, a fourth request returns HTTP 402. Replaying the original issuance returns its immutable 3-unit committed projection without revealing or rotating a secret.
- Two later authorized 2-unit top-ups reuse that key, return no secret and produce three total issuance grants. The live key balance is 3; available quota is 993.
- A different canonical owner is refused with `key_not_owned` / HTTP 403. Changed intent under the original negotiation is refused with `fulfillment_conflict` / HTTP 409, without balance or quota mutation.
- Missing operator authentication returns HTTP 401. Old mechanism/obligation payloads and digest-tampered quantity return HTTP 422.
- Service replay checks changed owner, quantity, service, resource and key target. Concurrent exact retries commit one grant. A foreign/undersized hold cannot authorize a purchase; an expired hold is released and replaced, and a changed operational hint does not change digest or grant another balance/quota allocation.

The canonical authorization binds schema, negotiation ID, its uniformly derived fulfillment ID, canonical owner, service, resource, quantity and key target. The quota-hold reference is excluded from its immutable digest. Neither request/result nor grant storage contains a settlement mechanism or escrow/obligation reference. The service has no settlement-kit import. The quota ledger retains an existing correlation field named `escrow_uid`, whose value here is only the neutral fulfillment ID; it is not a payment escrow or settlement-evidence row. Renaming that correlation API requires changes to `kit/site/src/market_site/ledger.py` and its shared consumers, outside this worker's owned files; it is left unchanged.

## Fresh storage

A separate file-backed temporary SQLite database was bootstrapped, bootstrapped again and passed `check_schema_version`. SQL and `PRAGMA table_info` / `index_list` inspection confirmed the [grant table definition](grant-schema.sql): unique negotiation and fulfillment identities, key foreign key, immutable command snapshot fields, and no mechanism/escrow/obligation columns. Admin adjustments retain null issuance identity.

The introducing grant migration validates the current neutral metadata; it does not backfill, copy, adopt or drop historical grant populations. Startup and schema checks reject old-shaped grant tables, including tables with an already-current migration marker. Quiesce issuance and explicitly reset disposable databases before cutover. No reset was performed against an inherited or external target.

The temporary database engine was disposed and its directory removed; the diagnostic printed `temporary_database_removed=True`. No server or external resources remain.

SettlementEvidence, source revalidation, issuance progress and private-result storage belong to the storefront owner in section 4. The service stores authorization/grants only; it must not duplicate the settlement gate.

## Validation and limits

- Client `test_credits_client.py` and `test_credits_client_http.py`: **13 passed**.
- Service `test_keys_service.py`, `test_api.py` and `test_migrations.py`: **35 passed**.
- `make dist`, credits-service and storefront consuming `reinit`, `make check-comment-hygiene`, strict OpenSpec validation and service `uv lock --check --offline`: passed.
- Touched production imports are module-level. The client has only an async variant; no sync API or static typecheck target/typing marker is declared by these packages.
- Two legacy grant-adoption tests and the historical grant-backfill tests were removed under the explicit no-compatibility contract; fresh bootstrap, rerun and incompatible-schema refusal replace that coverage.
- No live storefront/payment complete-deal lane or independent driver/reviewer ran. Post-review permanent promotion remains in section 5.5.
- Service lock changes add 27 packages in the dev client's dependency closure, its required eth-hash extra and the web3-required websockets downgrade (16.0 to 15.0.1). Unrelated greenlet wheel-metadata deletions were restored; other consuming locks were restored after validation. Reinit/uv sync resolution churn remains tracked in [#257](https://github.com/arkhai-io/simple-compute-market/issues/257).

Reproduction of focused validation:

```sh
(cd domains/apicredits &&
 UV_DEFAULT_INDEX=https://pypi.org/simple uv run --find-links ../../.dist pytest tests/test_credits_client.py tests/test_credits_client_http.py -q)
(cd domains/apicredits/service &&
 PYTHONPATH=src UV_DEFAULT_INDEX=https://pypi.org/simple uv run --find-links ../../../.dist pytest src/tests/unit/test_keys_service.py src/tests/unit/test_api.py src/tests/unit/test_migrations.py -q)
```
