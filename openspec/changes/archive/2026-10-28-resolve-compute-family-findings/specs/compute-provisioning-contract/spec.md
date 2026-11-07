## MODIFIED Requirements

### Requirement: Deal-scoped lifecycle events

When a lease's release completes and its capacity returns to the site, the provisioner MUST notify the owning storefront through the storefront's capacity-released callback: a `service`-role signed request carrying the reservation ID, the site ID, and the release time when known. Its request identity MUST be derived from a stable identity of that release, so a retried notification is an exact replay, and the provisioner MUST retry it from durable state until the storefront acknowledges it. The provisioner's internal lifecycle event, which carries the event identity, deal reference, and event kind, is not sent. Capacity release is the one fulfillment transition a provisioner pushes to a storefront; a storefront learns every other transition by reading the fulfillment.

#### Scenario: A reservation's capacity is released

- **WHEN** a lease's release completes and its capacity returns to the site
- **THEN** the owning storefront receives one capacity-released notification for the reservation, signed by the provisioner under the `service` role

#### Scenario: The storefront's acknowledgement is lost

- **WHEN** the provisioner sends a capacity-released notification and does not learn that the storefront acknowledged it
- **THEN** it resends the notification under the same request identity, and the storefront answers it as an exact replay

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** no notification is sent, and the storefront observes the transition through the fulfillment's status

### Requirement: Explicit contract incompatibility

Clients and servers MUST reject unsupported major contract versions with actionable version information rather than coercing them through VM-specific or legacy shapes. The contract's major is 3, and every party MUST accept only major 3. A versioned contract is versioned rather than changed in place: a major-3 schedule response names its resource's host, and a major-3 lease has no `provisioning_failed` state. A major-2 schedule response names no host, which a caller comparing hosts would otherwise refuse as a conflict with its terms rather than by version. A provisioning service and the storefronts and clients that call it MUST therefore be upgraded, and rolled back, together.

#### Scenario: Old client calls new service

- **WHEN** a request uses an unsupported contract major version
- **THEN** the service performs no action and reports the supported version range

#### Scenario: A storefront calls a service that has not been upgraded

- **WHEN** a major-3 storefront schedules a resource through a service answering major 2
- **THEN** the storefront refuses the answer, naming the supported major, and begins nothing

## ADDED Requirements

### Requirement: A schedule response names the scheduled resource's host and machine

A schedule response MUST carry the `host_id` of the resource it scheduled, taken from that
resource's capacity declaration, and MUST omit it when the declaration names no host. The
resource's physical machine MUST be its `physical_host_id` in the response's top-level
attributes. A caller compares what was scheduled with what it sold from these, without
reading the declaration's publication settings.

#### Scenario: A whole host is scheduled

- **WHEN** a caller schedules a resource whose declaration names a host and a physical
  machine
- **THEN** the schedule response carries that `host_id`, and its top-level attributes carry
  that `physical_host_id`

#### Scenario: A resource with no host is scheduled

- **WHEN** a caller schedules a resource whose declaration names no host, from a pool whose
  provider needs none
- **THEN** the schedule response omits `host_id` and the schedule succeeds
