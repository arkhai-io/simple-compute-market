## ADDED Requirements

### Requirement: The job view carries the job's structured failure

`JobStatusResponse` MUST carry an optional `failure` holding the latest failed attempt's `code`, `message`, `retryable` and redacted `details`, and MUST keep `error` as the job's failure text. A client reading a service that does not report `failure` MUST read it as null.

#### Scenario: A failed job is read

- **WHEN** a client reads a job whose latest attempt failed with `cleanup_refused`
- **THEN** the view's `failure` carries that code, its message, whether it is retryable and its details, and `error` carries the failure text

#### Scenario: A job recorded before the failure was kept

- **WHEN** a client reads a job that failed before its service kept structured failures
- **THEN** the view's `failure` is null and `error` carries its text
