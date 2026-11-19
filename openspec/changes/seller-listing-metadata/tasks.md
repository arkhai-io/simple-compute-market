# Tasks

- [x] Add common envelope fields in `core/src/market_core`, registry schema, migration and signed routes in `core/registry`, and registry request/read models in `core/registry-client`.
- [x] Wire seller inputs, persistence and publication through `core/storefront`, `core/storefront-client` and the VM, bare-metal and API-credits publications and seller CLI paths.
- [x] Run existing focused suites for those boundaries and exercise signed publish, GET, validation and filtering.
- [ ] Closeout: confirm comment hygiene and import placement; check documentation placement and compress notes; record roadmap and campaign dispositions; check packaging and architecture; record pipeline evidence and gaps; promote the registry discovery and storefront publication deltas; check citations and validate the change; archive.

## Validation notes

- Returned to planning at the triage of `01-implementation`. The tasks above were implemented on a base older than `dev`'s retained signed document (`published_document`), so the registry columns and migration `019_listing_details` are replaced by that document (F1), the API-credit request takes the shared description limit (F2), and the storefront paths gain focused tests: a typed-client create and republish in each storefront, a compute cycle adding, changing and withdrawing an override's details on one listing, and the API-credit refusal (F3). The replanned work starts by merging `dev`.
- `scripts/change-workflow run pre-commit seller-listing-metadata --base origin/dev` fails one check on the branch as implemented: `make check-local-imports` reports the function-level imports at `docs/attachments/seller-listing-metadata/roundtrip.py:92`, `:109` and `:115`. The replanned work moves them or gives each its reason.

- Registry: 139 unit + 128 integration (full integration directory) passed. Storefront: 182 unit passed. VM storefront: 1215 unit + 530 integration passed, 1 pre-existing skip. Bare metal: 224 domain + 590 storefront passed. API credits: 255 passed. VM buyer: 215 passed. Clients: 25 + 68 passed. Registry-client mypy clean; the VM storefront's mypy reports pre-existing errors (145 on its base) and none in the touched files.
- Signed publish → GET round trip with VM/bare-metal/API-credits resources carrying the fields: `docs/attachments/seller-listing-metadata/roundtrip.py`, output in `roundtrip-output.json` (run from `core/registry`). Covers refusal naming the field, the dry-run route, `$.metadata["acme.tier"]` filtering both by value and on missing, and unchanged reads for listings without the fields.
- Migration 019 exercised by downgrade to 018 and re-upgrade on a stamped database; fresh databases create the columns through `create_all` and stamp head.
- Tests that reach httpx fail on a machine with `ALL_PROXY` set to a SOCKS URL (`socksio` not installed); run suites with the proxy variables unset. Unrelated to this change.
- Environments install internal packages as wheels from `.dist/`, so after editing a package run `make dist` and `make reinit` in every project that installs it before trusting a test run; a stale wheel fails as an extra-forbidden field.
