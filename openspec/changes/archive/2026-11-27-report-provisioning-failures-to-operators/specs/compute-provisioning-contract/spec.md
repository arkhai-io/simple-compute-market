## ADDED Requirements

### Requirement: The job view carries the job's structured failure

`JobStatusResponse` MUST carry an optional `failure` holding the latest failed attempt's `code`, `message`, `retryable` and redacted `details`, and MUST keep `error` as the job's failure text. A client reading a service that does not report `failure` MUST read it as null.

#### Scenario: A failed job is read

- **WHEN** a client reads a job whose latest attempt failed with `cleanup_refused`
- **THEN** the view's `failure` carries that code, its message, whether it is retryable and its details, and `error` carries the failure text

#### Scenario: A job recorded before the failure was kept

- **WHEN** a client reads a job that failed before its service kept structured failures
- **THEN** the view's `failure` is null and `error` carries its text

## MODIFIED Requirements

### Requirement: Deal-scoped lifecycle events

When a lease's release completes and its capacity returns to the site, the provisioner MUST notify the owning storefront through the storefront's capacity-released callback: a `service`-role signed request carrying the reservation ID, the site ID, and the release time when known. It MUST do so for each release its lease lifecycle makes, and for no release a caller asks of the site's own release route. Its request identity MUST be derived from a stable identity of that release, so a retried notification is an exact replay, and the provisioner MUST retry it from durable state until the storefront acknowledges it or refuses it outright, answering 400, 404 or 409; a refused notification is abandoned and holds back no later one. The provisioner's internal lifecycle event, which carries the event identity, deal reference, and event kind, is not sent. Capacity release is the one fulfillment transition a provisioner pushes to a storefront; a storefront learns every other transition by reading the fulfillment.

#### Scenario: A reservation's capacity is released

- **WHEN** a lease's release completes and its capacity returns to the site
- **THEN** the owning storefront receives one capacity-released notification for the reservation, signed by the provisioner under the `service` role

#### Scenario: The storefront's acknowledgement is lost

- **WHEN** the provisioner sends a capacity-released notification and does not learn that the storefront acknowledged it
- **THEN** it resends the notification under the same request identity, and the storefront answers it as an exact replay

#### Scenario: The storefront refuses a notification

- **WHEN** the storefront answers a capacity-released notification with 404, holding no such reservation
- **THEN** the provisioner abandons that notification and delivers the notifications after it

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** no notification is sent, and the storefront observes the transition through the fulfillment's status
