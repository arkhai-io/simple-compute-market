# Compute provisioning

`provisioning/compute` owns the versioned caller contract and lifecycle helpers for the deployable multi-domain compute provisioner. `service/` is the FastAPI composition root. It mounts the site, resource-pool, fulfillment, and service schemas and loads VM and bare-metal adapter bundles without placing domain behavior in generic modules.

## Fulfillment lifecycle

The authenticated `/api/v1` boundary exposes:

- `POST /fulfillment/schedules`;
- `POST /fulfillments/dry-run` and `POST /fulfillments`;
- `GET /fulfillments/{fulfillment_id}/status` and `/result`;
- `POST /fulfillments/{fulfillment_id}/teardown`.

The service persists immutable prepared commands before execution. A periodic claimed recovery worker submits and polls create/teardown operations, resumes after restart, and releases capacity only after successful teardown. VM and bare-metal Ansible providers are registered by exact resource kind. Pull-based result reads are authoritative; VM credentials rotate live and are never stored in the fulfillment aggregate.

## Migrations and startup

Run migrations before starting the API:

```sh
compute-provisioning-migrate
# or, from provisioning/compute/service
make migrate
```

API startup checks migration markers and required schema and fails on drift; it does not migrate in process. The active-VM migration normalizes historical capacity into the default pool and atomically creates teardown-capable backfilled fulfillment aggregates. Missing or ambiguous host, target, pool, provider, or releasing-job data aborts the migration without recording completion.

`GET /api/v1/system/status` reports fulfillment recovery counters, live/expired claims, retry and lifecycle ages, and provider failures without exposing credentials or owner principals.

## Development packaging

Internal dependencies are built as wheels into `.dist` and installed with `--find-links`; sibling editable sources are not used. From the repository root:

```sh
make dist-compute-provisioning-service
make -C provisioning/compute/service reinit
make test-provisioning
```

See `docs/development/ARCHITECTURE.md` and `openspec/specs/fulfillment/spec.md` for authority and lifecycle contracts.
