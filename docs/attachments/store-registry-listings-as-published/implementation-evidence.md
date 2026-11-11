# Retained registry publications — implementation evidence

## Scope and status

Backend-only implementation evidence, 2026-11-06. No screenshots or visual claim.
This is not independent acceptance or a deployed end-to-end pipeline result.
Maintainer review, permanent-document promotion and archival remain pending.
The branch was rebased onto dev at `b0b389703` before opening PR #349; packaging,
scoped change checks, the first-use example, and all four primary suites listed
below were rerun successfully on that rebased tree.

## First use

From a clean checkout of this branch:

```sh
make dist
make -C core/registry reinit
(cd core/registry && uv run --find-links ../../.dist python ../../openspec/changes/archive/2026-11-11-store-registry-listings-as-published/first-use.py)
```

The last command is the directly runnable story surface: a local in-process
registry with fresh temporary SQLite migrated through the packaged chain, the compute filter specification, and public
deterministic Ed25519 development seller/registry identities. No external service,
API key, secret, container or running server is required. The script checks
`GET /health` before publication, prints the returned listing and seller evidence,
verifies the seller's retained canonical request, searches, closes, and republishes
without the rate field. It disposes its database and transport state on exit.

Observed: readiness HTTP 200; `seller_verification: verified`; the first document
has top-level `rate_structure` and an arbitrary nested null; search count 1; the
replacement has `replacement_term`, no old rate/opaque term, and retains closed
status with separate status-update evidence. Exact publication bytes are base64
encoded beside the authenticated request envelope. These are public fixture
signatures, not credentials.

An additional temporary diagnostic drove the existing VM publication app fixture
through its administrator client, then validated the actual emitted rate-bearing
publication against the compute JSON Schema. It passed. The diagnostic was removed;
it is not a new permanent acceptance test. VM publication omits absent optional
resource attributes instead of sending schema-invalid nulls.

## Existing regression suites

| Command (within named project) | Result |
|---|---|
| `core/registry`: `uv run --find-links ../../.dist pytest tests/unit tests/integration -q` | 267 passed |
| `core/registry-client`: `uv run --find-links ../../.dist pytest tests -q` | 25 passed |
| `core/storefront`: `uv run --find-links ../../.dist pytest tests/unit/test_registry_publication.py tests/unit/test_listing_models.py tests/integration/test_rate_structure_column.py -q` | 7 passed |
| `domains/vms/storefront`: `ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --find-links ../../../.dist pytest tests/unit/test_listing_model_capacity_identity.py tests/unit/test_publication_terms_composition.py tests/unit/test_publications.py tests/unit/test_publication_wiring.py tests/unit/test_publications_wiring.py tests/integration/test_publication_loop.py -q` | 110 passed |
| VM pricing-resolution/startup-rate suites alongside publication loop | 110 passed (overlapping publication-loop cases, not an additional disjoint count) |

Existing tests were amended for deliberate contract changes: schema-valid gate and
rotation setup, document-backed filter seeding, filter-spec version 9, published
rate presence rather than absence, and omission of uncommitted null resource fields.
No kept ownership, signing, query, refresh or reopen assertion was removed. No new
permanent tests were added.

## Migration and packaging

A temporary SQLite experiment replayed the blank Alembic chain, seeded a valid
publisher/principal and legacy listing at revision 018, upgraded to head twice,
read the row through the current ORM/serializer, and compared model column names
with the migrated schema. All passed; legacy content survived and publication
proof remained null. A downgrade to the retired-column 017 shape followed by
upgrade to head also passed. The experiment's temporary databases were deleted.

This first exposed base-chain defects, repaired separately in `5fe46dd7a`:
revision 018 attempted to rename an already-current column on fresh replay, and
migration-derived schemas lacked listing demands and API-key storage. The repair
recognizes both supported shape names and adds missing schema without rewriting
existing data. Its compatibility downgrade deliberately retains carrier data.

- `make check-packaging`: passed, including wheelhouse, all lock/project checks,
  Python-version selection, package layout and all architectural dependency rules.
- `make check-change CHANGE=store-registry-listings-as-published`: passed, including
  comment hygiene, citations, task/index checks, strict pinned OpenSpec validation,
  decision destinations, history wording and touched-import checks.
- `bunx @fission-ai/openspec@1.14.0 validate store-registry-listings-as-published --strict`: passed.
- `git diff --check`: passed.

No dependency declarations changed; repository reinitialization refreshed installed
internal wheels without lockfile changes. Distribution release versions are left
unchanged in this development PR.

## Limits and next stage

No full-suite run, standalone type-checker run, browser run, external deployment,
PostgreSQL run or end-to-end pipeline run is claimed. The existing compute lanes cover publication wire
compatibility but do not assert retained arbitrary fields or seller-proof reads.
The closeout plan retains pipeline evidence and post-review documentation
promotion/archival as explicit unfinished work. Independent verification should
start with the committed first-use command above, not this session's environments.
No servers, containers, tunnels or browser pages remain running.
