# Compute provisioning migration plan

This document maps the current transitional provisioning service in
`domains/vms/provisioning/service` into a new top-level **provisioning** category.
The first target under that category is **compute provisioning**: a deployable
service for compute-like resources that can serve VM, bare-metal, and future
compute executors without being owned by any one domain package.

This is intentionally not a `core_storefront` API. Not every storefront domain
needs provisioning, and not every provisioned resource is compute. Shared pieces
that domains use to talk to a compute provisioner may become kit packages, while
the provisioner itself belongs under the provisioning category.

## Target package/category shape

Near-term target layout:

```text
provisioning/
  compute/
    service/      # deployable multi-executor compute provisioner
    client/       # HTTP/generated client for callers, if split from service
    contracts/    # shared DTOs/contracts, if they outgrow the client package
```

Current distribution:

- `arkhai-compute-provisioning` — shared app/lifecycle/startup helpers for
  compute provisioning services.

Potential future split:

- `arkhai-compute-provisioning-service`
- `arkhai-compute-provisioning-client`
- `arkhai-compute-provisioning-contracts`

The exact split can remain lazy while service, client, and contract code are not
yet large enough to justify separate wheels.

## Ownership model

### Compute provisioning service owns

The standalone compute provisioner owns cross-domain compute orchestration and
operator surfaces:

- FastAPI app shell and route composition for the deployable provisioning API;
- job queue / job state machine abstractions used by compute executors;
- capacity/resource authority for shared compute inventory;
- lease lifecycle orchestration and watchdog scheduling;
- executor release dispatch;
- domain/executor adapter registration and composition;
- generic system/job/lease/capacity routes that are not VM- or bare-metal-shaped.

### Domain packages own concrete compute semantics

Domain packages keep their deterministic market semantics and concrete executor
adapters:

- `domains/vms` owns VM request/result schema, VM action construction, KVM host
  operations, Ansible VM playbook shapes, VM release execution, and VM operator
  routes.
- `domains/bare_metal` owns bare-metal listing/terms/materialization/receipt
  schema, access grant/reclaim action vocabulary, bare-metal lease adapters,
  bare-metal release execution, and any bare-metal operator routes.

The compute provisioner should depend on these through explicit adapters rather
than importing VM request models, VM playbook parameters, or bare-metal access
models directly in generic code.

### Kit packages may own shared caller contracts

If multiple domains or apps need shared provisioning-facing helpers, those
belong in kit packages rather than core storefront. Examples:

- shared provisioning reference/receipt DTOs;
- generated HTTP client helpers;
- reusable capability/action codecs;
- helper types for provisioning-backed materializations.

A kit remains opt-in for domains that choose compatible provisioning semantics;
it is not a universal requirement for all storefront domains.

## Already extracted shared helpers

Reusable primitives are split by ownership. Storefront/site-authority primitives
remain in `core_storefront`; compute-provisioning app/runtime helpers live under
`provisioning/compute`.

| Boundary | Current module | Transitional VM provisioning status |
| --- | --- | --- |
| Site resource/allocation adapter | `core_storefront.site_resources` | `services.site_resources_service` is a re-export shim. |
| Lease lifecycle state machine | `core_storefront.lease_lifecycle` | `services.lease_lifecycle_service` wires VM/bare-metal delegates. |
| Release executor dispatch | `core_storefront.release_dispatcher` | `services.release_executors.ExecutorReleaseDispatcher` preserves VM default. |
| Executor lease registration/listing | `core_storefront.executor_leases` | `BareMetalLeaseService` maps bare-metal models to shared registration. |
| Compute provisioning app shell | `compute_provisioning.app` | `main.py` uses injected middleware/router mounts. |
| Compute provisioning background lifecycle | `compute_provisioning.lifecycle` | `main.py` uses named task creation/cancellation helpers. |
| Compute provisioning startup runner | `compute_provisioning.startup` | `main.py` uses ordered startup/shutdown/background-task assembly. |

Do not add provisioning-specific service contracts to core storefront. Future
compute-specific contracts should move to `provisioning/compute` or a kit
package, not deeper into core storefront.

## Current ownership map

### Should move to `provisioning/compute/service`

These pieces are compute provisioner authority or deployable-service
infrastructure, not intrinsically VM-specific:

| Current file | Notes |
| --- | --- |
| `main.py` app shell | FastAPI app, shared middleware wiring, route composition, startup/shutdown task lifecycle. Needs adapter/router injection before moving. |
| `container.py` composition root | Currently wires VM and bare-metal together. Should become the compute provisioner composition root with domain/executor adapter registration. |
| `controllers/system_controller.py` generic parts | Health/status/version/check-leases/watchdog control. `ansible/readiness` is executor-backend specific and should be injected or split. |
| `controllers/jobs_controller.py` | Generic job read/cancel surface as long as the service uses the shared job runner. |
| `controllers/leases_controller.py` lifecycle operations | Generic lease lifecycle endpoints are mostly executor-neutral; VM-shaped create/update response models need adapter treatment. |
| `market_site.router.make_capacity_router(...)` mounting | Shared compute capacity authority should remain with compute provisioning. |
| `services/lease_watchdog.py` | Generic timer around the lifecycle service. |
| `services/system_service.py` health/watchdog parts | Split filesystem/Ansible readiness from generic health/watchdog/status parts. |
| `services/async_job_queue.py` | Generic in-process job queue if retained for all compute executors. |
| `services/job_service.py` job state machine | Mostly generic job persistence/retry/log/credential lifecycle; still coupled to `AnsibleJobParams` and VM result parsing. Needs a job runner protocol before moving. |

### Should remain VM domain-owned

| Current file | Notes |
| --- | --- |
| `controllers/vms_controller.py` | Direct KVM VM operator API. Could be mounted as a VM router adapter. |
| `controllers/hosts_controller.py` KVM host semantics | Host inventory may later become generic executor-host inventory, but current model and docs are KVM-specific. |
| `services/vm_operations_service.py` | Builds VM action jobs from VM request models. |
| `services/host_operations_service.py` | KVM capacity/connectivity checks using VM action params. |
| `services/provisioning_service.py` | VM playbook vars/result parsing (`ProvisioningParams`, `ProvisioningResult`). |
| `models/vm_request_model.py` | VM request-to-Ansible parameter mapping. |
| VM portions of `services/ansible_service.py` | Inventory/playbook backend can become a runner, but VM playbook shape stays VM-owned. |
| `VmReleaseExecutor` in `services/release_executors.py` | Concrete VM teardown submission. |
| VM-specific config keys and IAC under `domains/vms/provisioning/iac` | Domain-owned deployment/playbook assets. |

### Should become bare-metal domain-owned

| Current file | Notes |
| --- | --- |
| `controllers/bare_metal_leases_controller.py` | Transitional adapter. Should move with bare-metal provisioning/access domain. |
| `services/bare_metal_lease_service.py` | Thin model-to-registration adapter; should move when bare-metal package owns provisioning APIs. |
| `services/bare_metal_operations_service.py` | Bare-metal access grant/reclaim job construction and host validation. |
| `BareMetalReleaseExecutor` in `services/release_executors.py` | Concrete reclaim delegate wrapper. |
| Bare-metal action constants/models in `arkhai_bare_metal` | Already domain-owned. |

### Compatibility shims to keep during migration

Keep these import paths working until images and callers migrate:

- `services.site_resources_service`
- `services.lease_lifecycle_service`
- `services.release_executors.ExecutorReleaseDispatcher`
- `services.bare_metal_lease_service.BareMetalLeaseService`

Additional shims may be needed for controllers if routes move before clients are
updated.

## Extraction sequence

1. **Provisioning app shell** — implemented as a first low-risk slice.
   - `compute_provisioning.app` accepts routers and middleware settings and
     builds the FastAPI app shell.
   - `compute_provisioning.lifecycle` centralizes named background task creation
     and cancellation.
   - Current `main.py` uses these helpers without changing routes.
   - Validation: focused provisioning API tests; e2e recommended because startup
     lifecycle changes are runtime-sensitive.

2. **Startup/service resolution assembly** — implemented as transitional
   infrastructure.
   - `compute_provisioning.startup` centralizes ordered startup steps, named
     background task scheduling, shutdown steps, and background task
     cancellation.
   - Current `main.py` uses this shared sequence for DB init, service
     resolution, inventory seeding, job queue startup, retry scheduler, lease
     watchdog startup, and shutdown.
   - Keep concrete service factories in VM provisioning for now.
   - Validation: focused provisioning tests plus e2e.

3. **Destination scaffold for compute provisioning**
   - Add the `provisioning/compute` package directory and minimal package/docs
     once the first code is ready to move.
   - Treat current `domains/vms/provisioning/service` as the compatibility host
     until the new service package has a Dockerfile and route parity.

4. **Generic job runner seam**
   - Introduce a compute-provisioning job runner protocol for submit, get, list,
     logs, credentials, cancel, and retry scheduling.
   - Keep `AnsibleJobService` concrete in VM provisioning initially.
   - This is the main prerequisite for moving `jobs_controller.py` and generic
     system health without importing VM job internals.

5. **Domain/executor adapter registry**
   - Define adapter registration in `provisioning/compute`, not in
     `core_storefront`.
   - VM and bare-metal packages register routers, release executors, job action
     factories, readiness checks, and optional operator surfaces.

6. **Lease controller adapter split**
   - Move executor-neutral lifecycle endpoints to compute provisioning.
   - Keep VM-specific `LeaseCreate`, `LeaseUpdate`, and `LeaseResponse` mapping
     as a VM adapter or compatibility route.
   - Bare-metal lease registration remains a bare-metal adapter.

7. **New compute provisioning package/image**
   - Create the destination package and Dockerfile.
   - Register/mount VM and bare-metal adapters from domain packages.
   - Keep the old VM provisioning package as a compatibility distribution or
     route/import shim until deployments switch over.

## Next checkpoint recommendation

The next low-risk checkpoint should be a **VM-owned composition cleanup**, not a
new core interface: move remaining request-path service resolution/background
wiring out of `main.py` into a local VM provisioning composition module. That
prepares code for movement while avoiding a false `core_storefront` provisioning
contract.

After that, start the **job runner seam** in the future compute-provisioning
shape. Run focused provisioning tests for the composition cleanup; reserve full
e2e for the first checkpoint that changes runtime startup semantics or creates
the new deployable package/image.
