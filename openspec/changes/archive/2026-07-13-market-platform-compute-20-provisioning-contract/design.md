## Context

The current `provisioning_client` distribution is under the VM domain and exposes VM hosts, VM action requests, Ansible-shaped jobs, credentials, and leases. The service also supports bare-metal allocation/release through additional routes and adapters. Moving the service before stabilizing this wire would either make generic packages import VM models or force a second wire migration after extraction.

The prerequisite site-lifecycle change establishes allocation and event ownership. This change leaves the service deployed in its current location while replacing the shared caller contract.

## Goals / Non-Goals

**Goals:**

- Define one versioned compute command/job/lease/event contract.
- Keep executor parameters and results typed and domain-owned.
- Migrate VM and bare-metal producers and consumers in place.
- Establish dependency direction for provisioner-to-storefront events.
- Replace the VM-owned shared client package.

**Non-Goals:**

- Move the deployable service or build its destination image.
- Put compute contracts in core storefront.
- Force API credits or future non-compute domains to implement the contract.
- Standardize placement policy or concrete executor payloads.

## Decisions

### Own the contract under compute provisioning

Create a compute-owned contracts/client package under `provisioning/compute`. It may begin as one distribution and split later only if service, client, and DTO release cadences require it. Core and domain concept packages do not own or import this optional infrastructure contract.

### Use typed versioned envelopes

Commands carry contract version, allocation ID, deal reference, executor kind, action kind, idempotency key, and executor parameters. Accepted responses return durable job identity. Terminal results carry result kind, typed executor result, credentials, and structured failure information.

The shared envelope is concrete and validated. VM and bare-metal adapters register parameter/result validators for their executor/action kinds; generic code never switches on concrete payload fields.

### Separate command, job, lease, and event resources

The public contract has four coherent surfaces:

1. executor action submission and cancellation;
2. durable job status, logs, credentials, retry, and terminal result;
3. allocation-backed lease registration, inspection, termination, retry release, and force release;
4. provisioner lifecycle events addressed by allocation/deal ownership.

Direct VM host administration may remain a VM operator API and is not part of the common storefront contract.

### Make idempotency and correlation mandatory

Action submission is idempotent by caller key within allocation/action scope. Every job and lease retains allocation ID, deal reference, and executor kind. Infrastructure names derived by adapters use allocation identity where retry safety requires deterministic names.

### Treat reverse callbacks as transport adapters

The contract defines lifecycle event payloads and delivery semantics without requiring provisioning to depend on the full storefront client. HTTP callback, event-bus, or local test transports implement a narrow event sink. This absorbs the unresolved `extract-storefront-callback-client` concern.

### Coordinate one compatibility cutover

Introduce the compute package, adapt the current service routes, migrate storefront and test clients, then remove VM-owned shared DTO/client use. If route aliases are temporarily required during a single deployment update, they are removed before the change archives; they are not permanent compatibility API.

### Verification and rollback

Use contract tests against the in-process service and client, VM and bare-metal adapter tests, idempotent resubmission, terminal error, credential, lease-release, and callback delivery scenarios. Rollback deploys the previous client and service together; mixed contract major versions fail explicitly.

## Risks / Trade-offs

- **Opaque executor payloads could evade validation.** Mitigation: adapter registration includes validators and result codecs selected before execution.
- **One contract may overfit VM asynchronous jobs.** Mitigation: require lifecycle invariants but permit executor actions that complete immediately while still producing a terminal job resource.
- **Coordinated cutover affects several packages.** Accepted to avoid dual long-lived clients; package constraints and contract-version rejection make mismatch actionable.
- **Callbacks can be delivered more than once.** Mitigation: event IDs and allocation/deal correlation are mandatory, and sinks handle duplicates idempotently.
