## 1. Verify Prerequisites and Current Ownership

- [ ] 1.1 Confirm the site-lifecycle and compute-provisioning contract changes are implemented, synchronized, archived, and passing focused tests
- [ ] 1.2 Reconcile generic versus VM-owned versus bare-metal-owned files, routes, factories, persistence, configuration, and deployment references against current code
- [ ] 1.3 Run current startup, job, lease, VM, bare-metal, and service API suites before moving code
- [ ] 1.4 Update this design/specs if prerequisite implementation changed the destination boundary

## 2. Prepare Domain-Owned Composition

- [ ] 2.1 Move remaining request-path service resolution and background wiring from the VM `main` module into a local composition module
- [ ] 2.2 Define the compute executor adapter bundle and startup validation in the destination package
- [ ] 2.3 Export VM routers, job/action factories, release executor, result/credential codec, readiness checks, and operator surfaces as one VM adapter
- [ ] 2.4 Export corresponding access grant/reclaim, release, codec, readiness, and operator surfaces as one bare-metal adapter

## 3. Establish the Destination Service

- [ ] 3.1 Create the installable `provisioning/compute/service` package and compute-owned composition root
- [ ] 3.2 Move generic FastAPI assembly, middleware, startup/shutdown ordering, and background task lifecycle
- [ ] 3.3 Move generic job read/control, executor-neutral lease, watchdog, general health/version, capacity mount, and event-delivery surfaces
- [ ] 3.4 Keep VM host/action/playbook/result behavior and direct operator routes in the VM package
- [ ] 3.5 Keep bare-metal access/action/result/reclaim behavior and operator routes in the bare-metal package

## 4. Preserve Runtime and Persistence

- [ ] 4.1 Point destination factories at the existing service-owned databases and ordered migration histories
- [ ] 4.2 Preserve job, allocation, deal, lease, credential, event, and idempotency identifiers across the move
- [ ] 4.3 Verify startup failure, retry scheduler, watchdog, worker, and graceful cancellation behavior in the destination app
- [ ] 4.4 Add import-boundary tests rejecting concrete domain implementations from generic compute modules

## 5. Package and Deploy the Service

- [ ] 5.1 Add supported API and worker console commands and complete runtime dependency metadata
- [ ] 5.2 Build/install the destination wheel with VM and bare-metal adapter extras outside the repository layout
- [ ] 5.3 Add the destination Dockerfile/image and verify health, readiness, background lifecycle, and graceful shutdown
- [ ] 5.4 Migrate manifests, image references, operator configuration, and local/e2e launch paths

## 6. Complete the Ownership Cutover

- [ ] 6.1 Migrate all remaining imports and callers from VM-owned generic provisioning paths
- [ ] 6.2 Remove the old VM-owned generic service/client distributions and transitional re-exports
- [ ] 6.3 Remove obsolete Dockerfiles, commands, and image references after destination parity is proven
- [ ] 6.4 Scan active packages and deployments for stale ownership paths or parent-directory dependency assumptions

## 7. Verify the Extraction

- [ ] 7.1 Run destination app/startup/lifecycle and generic job/lease/capacity API suites
- [ ] 7.2 Run affected VM and bare-metal executor and release suites
- [ ] 7.3 Run destination wheel/image smoke tests and the focused storefront provisioning scenario
- [ ] 7.4 Validate package boundaries and OpenSpec artifacts after behavioral verification
