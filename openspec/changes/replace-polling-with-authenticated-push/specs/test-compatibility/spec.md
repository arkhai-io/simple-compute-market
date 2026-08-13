## ADDED Requirements

### Requirement: Scenarios observe delivered events rather than polling

An end-to-end scenario MUST advance by observing events the system delivers, rather than
by polling for convergence or waiting a fixed interval. A scenario's runtime MUST depend
on the system completing work, not on a configured poll interval or timeout margin.

#### Scenario: A scenario waits for work to complete

- **WHEN** a scenario needs a lifecycle stage to finish before proceeding
- **THEN** it awaits the event the system emits on completion, rather than polling status
  until a timeout

#### Scenario: The system is slower than expected

- **WHEN** a stage takes longer than usual
- **THEN** the scenario waits for the event rather than failing on an interval-derived
  timeout

#### Scenario: A scenario would depend on event ordering

- **WHEN** a scenario needs several events that have no guaranteed order between them
- **THEN** it awaits each fact independently rather than assuming a sequence
