# Accepted introductions after contact disablement

Tested implementation: `e1c959b4`, based on `ba706fb3`.

Accepted bare-metal introductions survive disabled contact publication. The route
factory no longer uses fresh enablement as its recovery gate. Accepted prepare
loads the persisted Agreement, resolves its declared seller entry, and checks the
plan, parties and obligation reference. That entry records the completed reveal.
Fresh admission still uses the priority-derived negotiation dispatch.

## Setup and replay

Required environment: local Python/uv, staged internal wheels; no external chain,
payment, site or hardware service. Prepared target: checkout-owned in-process
bare-metal storefront with real migrated SQLite. Buyer and seller use synthetic
EIP-191 fixture signers; no external credentials are required. Each case creates
a fresh pytest-owned database, accepts a contact deal, then reconstructs the
runtime on that database with `contact.enabled = false` and empty priority.
Retained contact configuration supplies the first reveal's seller payload.

From the repository checkout:

```sh
bash domains/bare_metal/storefront/docs/attachments/contact-disablement/replay.sh
```

The command builds all wheels, reinstalls the storefront's internal dependencies,
and runs the two signed API journeys. Observed readiness: build/reinit succeeded,
and the initial negotiation accepted before either disabled-runtime encounter.
No resident server or external resource is created; TestClient and pytest clean
their owned application/database state.

## Observations

Proving test: `tests/test_http_introductions.py::test_accepted_introduction_survives_contact_disable`.

| Journey | Observation |
|---|---|
| Accepted, not yet revealed, then disabled/restarted | POST reveals the seller contact; a second POST returns the same projection. Seller GET reveals the buyer contact. Obligation reaches complete and evidence retains its original reference. |
| Revealed, then disabled/restarted | Buyer GET returns the persisted seller contact before any restart POST. Retried POST is unchanged; seller GET returns the buyer contact. Completed obligation/evidence keep the original reference. |
| Fresh work after disablement | Publication yields no contact option and new signed contact negotiation returns HTTP 400, despite the old listing remaining in SQLite. |

On the unmodified base, both new cases failed with HTTP 404 and
`contact exchange is disabled`: the unstarted case at POST and the revealed case
at GET. This establishes sensitivity to the reported guard, not just agreement
between a fixture and its own declaration.

Final validation: **6 introductions checks + 53 affected regression checks passed**.
The regression selection covers introduction delivery, HTTP negotiation and
settlement, selection dispatch, settlement helpers, app composition and domain
runtime. `make dist`, storefront `reinit`, comment hygiene, strict contact spec
validation and `git diff --check` passed.

Regression command after the setup above:

```sh
cd domains/bare_metal/storefront
uv run --no-sync pytest tests/test_http_introductions.py tests/test_introduction_delivery.py tests/test_http_negotiation.py tests/test_selection_dispatch.py tests/test_settlement.py tests/test_http_settlement.py tests/test_app_composition.py tests/test_domain_runtime.py -q
```

This is controlled local API/SQLite evidence, not live ledger or hardware
qualification. No browser or screenshots are involved. Independent driving and
the joined dispatch inventory remain with campaign integration.

## Documentation

The normative disablement scenario is in
`openspec/specs/contact-exchange-settlement/spec.md#requirement-accepted-introductions-survive-publication-disablement`.
The market-composition architecture's current-limits paragraph no longer lists
this repaired bare-metal surface; it retains the separate API-credit finding.
No persistence or wire migration is needed. Campaign closeout owns the joined
inventory and active-change task status.
