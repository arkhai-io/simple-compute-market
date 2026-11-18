## ADDED Requirements

### Requirement: A job view shows when its execution started

The compute contract's job view MUST carry a nullable `execution_started_at`, the instant the job authority recorded that the job's execution was starting, null for a job whose execution has not started or that was recorded before the instant existed. It MUST NOT default or infer the instant. A client reading a service that does not report it MUST read null. Null on a job recorded before the instant existed MUST NOT be read as evidence that its execution never started.

#### Scenario: A job whose playbook ran is read

- **WHEN** a caller reads a job whose execution started
- **THEN** its view carries the instant the job authority recorded

#### Scenario: A job refused before its execution is read

- **WHEN** a caller reads a job that failed before its execution started
- **THEN** its `execution_started_at` is null
