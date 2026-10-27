## MODIFIED Requirements

### Requirement: Deal-scoped lifecycle events

Provisioner lifecycle events MUST carry stable event identity, allocation ID, deal reference, event kind, and versioned event payload, and event sinks MUST handle duplicate delivery idempotently. The one event a provisioner sends to a storefront is `capacity_released`, when a reservation's capacity returns to the site; a storefront learns every other fulfillment transition by reading the fulfillment.

#### Scenario: A reservation's capacity is released

- **WHEN** a lease's release completes and its capacity returns to the site
- **THEN** the owning storefront receives one `capacity_released` event for the reservation, signed by the provisioner, without the provisioner depending on the full storefront client

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** no event is sent, and the storefront observes the transition through the fulfillment's status

### Requirement: Explicit contract incompatibility

Clients and servers MUST reject unsupported major contract versions with actionable version information rather than coercing them through VM-specific or legacy shapes. The contract's major is 3, and every party MUST accept only major 3: a major-3 schedule response names its resource's host, and a major-3 lease has no `provisioning_failed` state, so a major-2 party can honour neither. A provisioning service and the storefronts and clients that call it MUST therefore be upgraded, and rolled back, together.

#### Scenario: Old client calls new service

- **WHEN** a request uses an unsupported contract major version
- **THEN** the service performs no action and reports the supported version range

#### Scenario: A storefront calls a service that has not been upgraded

- **WHEN** a major-3 storefront schedules a resource through a service answering major 2
- **THEN** the storefront refuses the answer, naming the supported major, and begins nothing

## ADDED Requirements

### Requirement: A schedule response names the scheduled resource's host and machine

A schedule response MUST name the host and the physical machine of the resource it
scheduled, taken from that resource's capacity declaration, so a caller compares what was
scheduled with what it sold without reading the declaration's publication settings.

#### Scenario: A whole host is scheduled

- **WHEN** a caller schedules a resource whose declaration names a host and a physical
  machine
- **THEN** the schedule response carries that `host_id` and that `physical_host_id`
