## MODIFIED Requirements

### Requirement: Deal-scoped lifecycle events

When a lease's release completes and its capacity returns to the site, the provisioner MUST notify the owning storefront through the storefront's capacity-released callback: a `service`-role signed request carrying the reservation ID, the site ID, and the release time when known. Its request identity MUST be derived from a stable identity of that release, so a retried notification is an exact replay, and the provisioner MUST retry it from durable state until the storefront acknowledges it. The provisioner's internal lifecycle event, which carries the event identity, deal reference, and event kind, is not sent. Capacity release is the one fulfillment transition a provisioner pushes to a storefront; a storefront learns every other transition by reading the fulfillment.

#### Scenario: A reservation's capacity is released

- **WHEN** a lease's release completes and its capacity returns to the site
- **THEN** the owning storefront receives one capacity-released notification for the reservation, signed by the provisioner under the `service` role

#### Scenario: The storefront's acknowledgement is lost

- **WHEN** the provisioner sends a capacity-released notification and does not learn that the storefront acknowledged it
- **THEN** it resends the notification under the same request identity and origin, re-signed, and the storefront runs the notification again, which converges on the released reservation, and answers it signed, however long after the first attempt

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** no notification is sent, and the storefront observes the transition through the fulfillment's status

