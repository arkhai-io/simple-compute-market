## ADDED Requirements

### Requirement: A storefront hears from its site only through steps a pause holds

Compute provisioning MUST send to a storefront only through its event delivery worker's consumers. A command or lease-watchdog cycle that records a lease-end or capacity-released event MUST deliver it before returning only while event delivery is not paused; while event delivery is paused the event MUST stay recorded for the worker, and `POST /api/v1/system/event-delivery/run-cycle` MUST deliver it. The capacity-reservation watchdog, which records a hold's expiry, MUST hold its timer at a gate while paused and MUST offer, through route contracts the provisioning client binds, a pause, a resume and one cycle that runs its production cycle, answering whether it is paused and at its gate, as the lease watchdog does.

#### Scenario: A terminate while event delivery is paused

- **GIVEN** event delivery paused
- **WHEN** the administrator terminates a lease
- **THEN** the lease's end is recorded and its signed report is not sent to the storefront
- **AND** one event-delivery cycle sends it, with its original identity and instant

#### Scenario: A stepped watchdog cycle while event delivery is paused

- **GIVEN** event delivery and the lease watchdog paused, and a lease past its end
- **WHEN** one lease-watchdog cycle is stepped
- **THEN** the lease's end and release are recorded and neither event reaches the storefront until event delivery is stepped

#### Scenario: Unpaused delivery is unchanged

- **WHEN** event delivery is running and a command records a lease's end
- **THEN** the report is delivered before the command returns, as before

#### Scenario: The capacity-reservation watchdog is held

- **GIVEN** the capacity-reservation watchdog paused and at its gate, and a hold past its expiry
- **WHEN** no cycle is stepped
- **THEN** the watchdog records no expiry
- **AND** one stepped cycle expires the hold and records its event for delivery
