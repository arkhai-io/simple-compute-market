## ADDED Requirements

### Requirement: A sink delivers any deliverable

A sink MUST deliver what it is handed through `rendered`, `payload()` and `reference` alone, so that one installed sink serves both a revealed introduction and an event. A delivery event's `reference` MUST be its obligation reference, and an event's MUST be its subject as `<type>:<id>`. A sink failing on what it is handed MUST be reported as any sink failure is.

#### Scenario: One sink serves an introduction and an event

- **WHEN** the same configured mail sink is handed a revealed introduction and a `provisioning.lease_release_failed` event
- **THEN** it sends each one's rendering, its subject naming each one's reference

#### Scenario: An installed sink reads only the obligation reference

- **WHEN** an installed sink that reads `obligation_ref` is handed an event
- **THEN** that delivery fails, reported by the exception's class, and its deliveries of introductions are unaffected

### Requirement: A signing webhook signs as its composition says

A signing webhook MUST take the role and operation it signs as from the composition that builds it, not from constants, so that each service signs its deliveries as itself.

#### Scenario: The provisioning service signs a webhook delivery

- **WHEN** the provisioning service delivers an event through a webhook configured with `sign = true`
- **THEN** the request is signed with the provisioning service's identity under the role and operation its composition names

### Requirement: Configured sinks receive the events their routes select

The delivery kit's event-sink consumer MUST hand each event its routes select to each selected sink, recording each sink's outcome as that destination's delivery state, and MUST hand an event whose delivery to a sink is abandoned to the configured finally sink.

#### Scenario: An event matches a route

- **WHEN** an event is recorded that a route selecting two sinks matches
- **THEN** both sinks receive it once each, and each sink's outcome is that destination's delivery state

#### Scenario: A sink is down past the maximum age

- **WHEN** a selected sink fails every delivery of an event past the consumer's maximum age
- **THEN** that delivery is abandoned and the event is written to the finally sink, the log unless configured otherwise
