# Provisioning migration plan

This document maps the current transitional provisioning service in
`domains/vms/provisioning/service` into the pieces that should move to a
site/multi-domain provisioning package and the pieces that should remain owned
by concrete domains such as VM and bare metal.

## Target shape

The deployable service should become a **site provisioning service** with a
composition root that wires domain adapters:

- shared site authority / lifecycle services from core;
- VM provisioning adapters from `domains/vms`;
- bare-metal provisioning adapters from `domains/bare_metal` or a bare-metal
  provisioning package;
- compatibility import paths in `domains/vms/provisioning/service` until callers
  and images are migrated.

The shared service should not import VM request models, Ansible VM playbook
parameters, or bare-metal access models directly. Those remain adapter inputs.

## Already extracted into core storefront

| Boundary | Core module | VM provisioning status |
| --- | --- | --- |
| Site resource/allocation adapter | `core_storefront.site_resources` | `services.site_resources_service` is a re-export shim. |
| Lease lifecycle state machine | `core_storefront.lease_lifecycle` | `services.lease_lifecycle_service` wires VM/bare-metal delegates. |
| Release executor dispatch | `core_storefront.release_dispatcher` | `services.release_executors.ExecutorReleaseDispatcher` preserves VM default. |
| Executor lease registration/listing | `core_storefront.executor_leases` | `BareMetalLeaseService` maps bare-metal models to core registration. |

These are the main lifecycle seams needed before the provisioning service can be
moved out of `domains/vms` without also moving concrete VM implementation code.

## Current ownership map

### Should move to site/multi-domain provisioning

These pieces are site authority or deployable-service infrastructure, not
intrinsically VM-specific:

| Current file | Notes |
| --- | --- |
| `main.py` app shell | FastAPI app, shared middleware wiring, route composition, startup/shutdown task lifecycle. Needs adapter/router injection before moving. |
| `container.py` composition root | Currently wires VM and bare-metal together. Should become the new site provisioning composition root with domain adapter registration. |
| `controllers/system_controller.py` | Health/status/version/check-leases/watchdog control. `ansible/readiness` is executor-backend specific and should be injected or split. |
| `controllers/jobs_controller.py` | Generic job read/cancel surface as long as the service uses the shared job runner. |
| `controllers/leases_controller.py` lifecycle operations | Generic lease lifecycle endpoints are mostly executor-neutral; VM-shaped create/update response models need adapter treatment. |
| `market_site.router.make_capacity_router(...)` mounting | Site capacity authority should remain with site provisioning. |
| `services/lease_watchdog.py` | Generic timer around the core lifecycle service. |
| `services/system_service.py` health/watchdog parts | Split filesystem/Ansible readiness from generic health/watchdog/status parts. |
| `services/async_job_queue.py` | Generic in-process job queue if retained for all provisioning executors. |
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
| `services/bare_metal_lease_service.py` | Thin model-to-core registration adapter; should move when bare-metal package owns provisioning APIs. |
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
   - `core_storefront.provisioning_app` now accepts routers and middleware
     settings and builds the FastAPI app shell.
   - `core_storefront.provisioning_lifecycle` centralizes named background task
     creation and cancellation.
   - Current `main.py` uses these helpers without changing routes.
   - Remaining: extract startup/service resolution assembly from the lifespan.
   - Validation: focused provisioning API tests; e2e recommended because startup
     lifecycle changes are runtime-sensitive.

2. **Startup/service resolution assembly**
   - Extract the ordered startup sequence from `main.py`: DB init, service
     resolution, inventory seeding, job queue startup, retry scheduler, lease
     watchdog startup, shutdown cancellation.
   - Keep concrete service factories in VM provisioning for now.
   - Validation: focused provisioning tests plus e2e.

3. **Generic job runner seam**
   - Introduce a core protocol for queued jobs: submit, get, list, logs,
     credentials, cancel, retry scheduler.
   - Keep `AnsibleJobService` concrete in VM provisioning initially.
   - This is the main prerequisite for moving `jobs_controller.py` and generic
     system health without importing VM job internals.

4. **Lease controller adapter split**
   - Move executor-neutral lifecycle endpoints to site provisioning.
   - Keep VM-specific `LeaseCreate`, `LeaseUpdate`, and `LeaseResponse` mapping
     as a VM adapter or compatibility route.
   - Bare-metal lease registration remains a bare-metal adapter.

5. **New site provisioning package/image**
   - Create the destination package and Dockerfile.
   - Register/mount VM and bare-metal adapters from domain packages.
   - Keep the old VM provisioning package as a compatibility distribution or
     route/import shim until deployments switch over.

## Next checkpoint recommendation

The next low-risk code checkpoint should be **shared provisioning app/lifespan
assembly**. It is the first move that reduces ownership of the deployable
service itself while keeping concrete VM and bare-metal execution untouched.
Because it changes runtime startup/shutdown behavior, run focused provisioning
tests and then a full e2e run after the checkpoint.
