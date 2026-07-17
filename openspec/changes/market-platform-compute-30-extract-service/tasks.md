## 1. Verify Prerequisites and Current Ownership

- [ ] 1.1 Confirm the site-lifecycle and compute-provisioning contract changes are implemented, synchronized, archived, and passing focused tests
- [ ] 1.2 Reconcile generic versus VM-owned versus bare-metal-owned files, routes, factories, persistence, configuration, and deployment references against current code, including the landed POOLS-2 scheduler, POOLS-3 fulfillment/provider surfaces, and POOLS-4 storefront claim boundary
- [ ] 1.3 Run current startup, job, lease, VM, bare-metal, and service API suites before moving code
- [ ] 1.4 Update this design/specs if prerequisite implementation changed the destination boundary
- [ ] 1.5 **Absorbed from closed POOLS-5:** delete the dead duplicate
      `provisioning/compute/src/compute_provisioning/pools.py` and
      `pool_config_handler.py` (byte-identical copies of the files in
      `kit/resource-pools/src/market_resource_pools/`, unreferenced by
      `compute_provisioning/__init__.py`, which re-exports the real ones
      from `market_resource_pools` instead — verified by repository-wide
      grep, 2026-07-17). Confirm via a fresh grep for
      `compute_provisioning.pools` / `compute_provisioning.pool_config_handler`
      submodule imports immediately before deleting, in case something
      changed since. This is independent of task 1.6 below and does not
      require a design decision.
- [ ] 1.6 **Absorbed from closed POOLS-5:** as part of this change's
      design-review pass, decide whether `PhysicalSettlementScheduler`
      (currently VM-service-local), `FulfillmentProvider`/`ProviderRegistry`
      (currently `kit/resource-pools`), and the `SettlementRecord`/
      settlement-resource shapes should consolidate into
      `compute_provisioning` alongside `pools-2`'s scheduling/request
      contracts, or stay split as they are today. Record the decision and
      rationale in this change's `design.md` before implementing §2–§3
      below.

## 2. Prepare Domain-Owned Composition

- [ ] 2.1 Move remaining request-path service resolution and background wiring from the VM `main` module into a local composition module
- [ ] 2.2 Define the compute executor adapter bundle, optional fulfillment-provider contributions, and startup validation in the destination package
- [ ] 2.3 Export VM routers, job/action factories, release executor, result/credential codec, `AnsibleFulfillmentProvider`, readiness checks, and operator surfaces as one VM adapter
- [ ] 2.4 Export corresponding access grant/reclaim, release, codec, readiness, and operator surfaces as one bare-metal adapter without requiring a provider contribution where none exists
- [ ] 2.5 Reject duplicate provider identities independently from duplicate executor/action kinds and verify provider registration does not claim or select an executor kind

## 3. Establish the Destination Service

- [ ] 3.1 Create the installable `provisioning/compute/service` package and compute-owned composition root
- [ ] 3.2 Move generic FastAPI assembly, middleware, startup/shutdown ordering, and background task lifecycle
- [ ] 3.3 Move generic job read/control, executor-neutral lease, watchdog, general health/version, capacity mount, event-delivery, `FulfillmentService`, and provider-registry composition surfaces
- [ ] 3.4 Keep VM host/action/playbook/result behavior, VM fulfillment requirements, `AnsibleFulfillmentProvider`, and direct operator routes in the VM package
- [ ] 3.5 Keep POOLS-4 listing identity validation, capacity-claim construction, VM fulfillment-plan construction, and storefront failure-policy/event handling in the VM storefront
- [ ] 3.6 Keep bare-metal access/action/result/reclaim behavior and operator routes in the bare-metal package

## 4. Preserve Runtime and Persistence

- [ ] 4.1 Point destination factories at the existing service-owned databases and ordered migration histories
- [ ] 4.2 Preserve job, allocation, deal, lease, credential, event, settlement-resource, and fulfillment identifiers and behavior across the move
- [ ] 4.3 Preserve POOLS-3's durable capacity rebind and explicitly process-local fulfillment identity semantics without implying restart-safe dispatch recovery
- [ ] 4.4 Verify startup failure, retry scheduler, watchdog, worker, and graceful cancellation behavior in the destination app
- [ ] 4.5 Add import-boundary tests rejecting concrete domain executor and fulfillment-provider implementations from generic compute modules and confirm extraction does not join the provider-only path to executor dispatch

## 5. Package and Deploy the Service

- [ ] 5.1 Add supported API and worker console commands and complete runtime dependency metadata, including `kit/resource-pools` fulfillment contracts
- [ ] 5.2 Build/install the destination wheel with VM and bare-metal adapter extras outside the repository layout
- [ ] 5.3 Add the destination Dockerfile/image and verify health, readiness, background lifecycle, and graceful shutdown
- [ ] 5.4 Migrate manifests, image references, operator configuration, and local/e2e launch paths

## 6. Complete the Ownership Cutover

- [ ] 6.1 Migrate all remaining imports and callers from VM-owned generic provisioning paths
- [ ] 6.2 Remove the old VM-owned generic service/client distributions and transitional re-exports
- [ ] 6.3 Remove obsolete Dockerfiles, commands, and image references after destination parity is proven
- [ ] 6.4 Scan active packages and deployments for stale ownership paths or parent-directory dependency assumptions

## 7. Verify the Extraction

- [ ] 7.1 Run destination app/startup/lifecycle and generic job/lease/capacity/fulfillment API suites
- [ ] 7.2 Run affected VM and bare-metal executor/release suites plus POOLS-2 scheduler and POOLS-3 provider/fulfillment suites
- [ ] 7.3 Run destination wheel/image smoke tests and the focused storefront provisioning scenario, including POOLS-4 `pool_id`/`resource_id` claim precedence and missing/malformed-order failure before capacity probe or reserve
- [ ] 7.4 Validate package boundaries and OpenSpec artifacts after behavioral verification
