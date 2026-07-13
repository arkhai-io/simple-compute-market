# Known Operational Issues

These are operational gotchas in the current stack, not a normative backlog. Proposed fixes belong in [`openspec/changes/`](../../openspec/changes/); current contracts belong in [`openspec/specs/`](../../openspec/specs/).

## Negotiation orphans

Negotiations may remain nonterminal long enough for `negotiation_watchdog.py` to intervene. Until the recovery contract is documented by `complete-development-documentation`, inspect the negotiation thread and stage events before forcing a terminal action.

## Buyer opening price and the seller floor

`extract_initial_price_from_order()` uses the advertised primary rate as the seller price. The maximizing bisection strategy exits with `price_unreasonable` when the buyer opens below the supported range rather than countering. E2E constants using an explicit initial price must satisfy:

```text
BUYER_INITIAL_PRICE >= primary_rate_value(accepted_escrows[0])
```

The default `listed_price` buyer policy satisfies this by opening at the advertised rate.

## Global pause persists for the process lifetime

The storefront global pause flag is process memory and is distinct from per-listing pause. A manually paused live storefront rejects `/negotiate/new` with HTTP 503 and `{"reason":"global"}` until resumed. The VM e2e fixture resumes the storefront during teardown; for a live environment call the authenticated `POST /admin/resume` endpoint before testing.

## Resource importer and storefront database paths must match

The resource importer resolves its SQLite target from `--db-path`, then `STOREFRONT_DB_PATH`, then configured `db_path`. If this differs from the server path, the storefront starts with no resources and negotiation returns `409 no_matching_inventory`. `GET /api/v1/system/status` exposes `resource_count`; zero indicates the mismatch. Compose pins the importer path explicitly.

## E2E stage dependencies require exact state names

The staged e2e flow relies on `require_state(deal_state, "field")`. Missing producers and misspelled field names can cause downstream skips that obscure the originating failure. When adding a `DealState` field, add an exact downstream consumer and keep the producer/consumer transition covered by the scenario.
