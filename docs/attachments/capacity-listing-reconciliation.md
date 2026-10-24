# Capacity-driven VM listing reconciliation evidence

## Boundary

Target: `integration/arkhai-payments`, base `4881ca816`. Verification is deterministic and in-process: real storefront routers, typed lifecycle/listing clients, SQLite listing/delivery persistence and publication runtime; controlled site HTTP and registry client boundaries. No live service, hosted purchase, capacity exhaustion on shared infrastructure, deployment pin edit or merge was performed. No servers remain running.

## Observations

`tests/integration/test_capacity_listing_lifecycle.py` in the VM storefront runs the approved property for `fungible` and `specific_resource` offers. A host declares 8 GPUs / 64 vCPUs / 512 GiB RAM / 1600 GiB disk; one offer consumes 1 / 8 / 64 / 200.

- Seven reservations keep the offer open; the eighth closes it, from freshly fetched detached projections rather than the earlier cached generation.
- Reserving returns before publication changes; the site reservation succeeds even with a failing registry boundary.
- One registry misses the close; a quiet capacity cycle resends only that target's close.
- Release restores one complete shape. A failed projection refresh holds the closed listing; a quiet successful refresh reopens the same stored ID, binding and commercial payload.
- One registry misses reopen. Reconstructed runtime, feed cursor and projection-cache objects over the same SQLite file repair that target. Removing its delivery row also remains discoverable as divergence.
- Seller closure survives later capacity reconciliation.

A diagnostic replay replaced only the VM event hook with the exact hook from the base revision, after normal pytest setup; the approved property failed at the eighth reservation (`open` instead of `closed`). This isolates the stale-input failure; it is not a claim that the entire baseline deployment was run. The repaired property passes in both modes.

## Reproduction

Build current internal wheels with `make dist-ci`. Initialize each affected project using its `reinit` target with the repository-declared Python interpreter on `PATH`; equivalently, from a project directory, invoke its existing `scripts/uv_project.py reinit` through `uv run --no-project --python 3.13 python`. No editable sibling dependency is used. Then run:

```sh
cd domains/vms/storefront
.venv/bin/python -m pytest tests/integration/test_capacity_listing_lifecycle.py tests/unit/test_remote_capacity_client.py tests/unit/test_reconciler.py tests/unit/services/test_site_projection_cache.py tests/unit/test_publications.py tests/integration/test_admin_api.py tests/integration/test_listings_api.py tests/integration/test_publication_loop.py tests/integration/test_shape_feasibility.py -q
```

Results:

| Scope | Result |
|---|---|
| VM focused unit/integration command above | 269 passed |
| `kit/capacity-publication`: `.venv/bin/python -m pytest -q` | 66 passed |
| `core/storefront`: `.venv/bin/python -m pytest -q` | 190 passed, 2 existing skips |
| Bare-metal storefront: `tests/test_publication_cycle.py tests/test_publication_cli.py tests/test_http_publication_rates.py tests/test_pool_overrides_api.py` | 56 passed |
| API-credit storefront: `tests/unit/test_capacity_reconcile_converges.py` | 3 passed |
| `make check-packaging` | Passed; wheel/lock, Python, project-layout and architecture checks |
| `make check-comment-hygiene` | Passed |
| `make check-doc-citations CHANGE=reconcile-vm-listings-on-capacity-events` | Passed |
| `make check-architecture-change CHANGE=reconcile-vm-listings-on-capacity-events` | Passed |
| Ruff `--select F` on seven touched runtime modules and the new integration property | Passed |
| Scoped strict OpenSpec, documented version 1.14.0 | Passed |

The host's default `python3` lacked `tomllib`; using the declared Python resolved setup/check invocation failures. Bare-metal client-construction tests first inherited a host SOCKS proxy without its optional dependency; rerunning with proxy environment variables removed passed without installing anything or changing product behavior.

## Explicit limitations

- Repository-wide strict OpenSpec validation with 1.14.0: 80 passed / 16 failed. A clean extraction of the approved base gives 79 passed / the same 16 failed. This change adds one passing item, not a repaired global gate. Earlier main-line validation friction is recorded at SCM #301.
- Focused mypy over the six touched kit/VM modules reports two baseline errors in `run_capacity_event_pollers` (awaitable versus coroutine and inferred task annotation). A clean extraction reports those same two plus the VM hook annotation corrected here. Follow-up: [SCM #303](https://github.com/arkhai-io/simple-compute-market/issues/303). No typing success is claimed.
- Snapshot acquisition retains the existing strict all-site failure boundary; a snapshot outage retries the pass rather than supplying unknown capacity as empty. A failed projection-family refresh after snapshots are readable holds only its site.
- Hosted end-to-end qualification and the Docker end-to-end pipeline are unrun. Hosted purchase/exhaustion checks and deployment changes were explicitly excluded. The repository's Tests workflow targets staging/dev PRs, so this integration-branch PR alone is not evidence of that pipeline passing.

## Rollout handoff

Build the storefront image from the reviewed revision and publish an immutable image digest. In a separately authorized infrastructure rollout, update both the image digest and the matching source revision pin. Reuse existing marketplace-signing and registry-writer configuration and the existing storefront process; no additional worker, scheduler or credential is required. No pins were changed here, and this is not a live readiness or credential-validity attestation.
