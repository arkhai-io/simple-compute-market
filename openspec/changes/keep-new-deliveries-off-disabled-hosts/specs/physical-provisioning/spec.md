## ADDED Requirements

### Requirement: Disabling a host keeps new deliveries off it

Disabling a registered host MUST keep new deliveries off it: no capacity
declaration naming it, in a backed pool whose provider needs a host, MAY be
admitted against, placed on, or projected enabled while it is disabled. Work
already placed on it MUST be unaffected: an assignment made before the host was
disabled keeps the host, its create waits at dispatch until the host is enabled
again, and teardown and operator jobs run against the host. Enabling the host MUST
offer its declarations again. The host authority MUST report the hosts taking new
delivery, as the identifiers of registered, enabled hosts, to the compute
composition, which supplies the report to site admission, settlement scheduling,
and the site projections.

#### Scenario: A host is disabled

- **WHEN** an operator disables a host named by an enabled declaration in a backed
  pool whose provider needs a host
- **THEN** a new claim is neither admitted against nor placed on that declaration,
  and the declaration is projected not enabled

#### Scenario: A disabled host already holds an assignment

- **GIVEN** an assignment placed on a host before it was disabled
- **WHEN** the assignment's create is dispatched while the host is disabled
- **THEN** the create is refused and retried, and is submitted once the host is
  enabled again

#### Scenario: A disabled host is enabled again

- **WHEN** an operator enables a disabled host
- **THEN** declarations naming it are admitted against, placed on, and projected
  enabled again
