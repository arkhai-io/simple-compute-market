## ADDED Requirements

### Requirement: A real playbook failure is classified from Ansible's own result records

The Ansible executor MUST enable, for every playbook it runs, a callback that records each failed or unreachable task — its host, play, role, task, task tags, module, return code, message and output, and whether the failure was ignored or rescued — to an owner-only file, whatever Ansible configuration an operator names. The runner MUST read the records once the process ends, hand them to the executor with the run's result or failure, and remove the file itself when the run ends, whether it succeeds, fails, times out or is cancelled; the executor MUST classify from the records it is handed, never from the file. It MUST classify a failed run, in order, as the runner's `timed_out` or `cancelled`; else from the last failure neither ignored nor rescued as `unreachable`, `authentication_refused` (an unreachable host refusing SSH authentication) or `task_failed`, a `task_failed` refined by its domain's codec; else, with no record, as `playbook_error`. The executor MUST report the class as the failure's `code`, a message naming the host, the task and the failure, and redacted `details`.

#### Scenario: A real task fails

- **WHEN** a real playbook run fails on a task that neither ignores nor rescues the failure
- **THEN** the job's failure is classified from that task's record, naming its host and task, and the run's record file no longer exists

#### Scenario: A host stops answering mid-run

- **WHEN** a playbook's host becomes unreachable after the job's execution started
- **THEN** the job fails with `unreachable` and is retried under the retry policy

#### Scenario: A host refuses the login

- **WHEN** a playbook's host refuses SSH authentication
- **THEN** the job fails with `authentication_refused` and is not retried

#### Scenario: An operator's Ansible configuration names another stdout callback

- **WHEN** an operator's own Ansible configuration names another stdout callback and a task fails
- **THEN** the failure is classified from the recorded task as it would be under the service's configuration

#### Scenario: A playbook fails before any task

- **WHEN** a playbook exits non-zero having recorded no failed task
- **THEN** the job fails with `playbook_error`, its exit code in the details, and is not retried

#### Scenario: A playbook times out

- **WHEN** a playbook runs past `ansible_timeout_seconds`
- **THEN** the job fails with `timed_out` and is retried under the retry policy

### Requirement: A domain classifies its own failures from the failure record

A domain's codec MUST classify a `task_failed` failure from its record, deciding its class and whether it is retryable, and a role MUST declare a domain class by tagging the task that can raise it. The bare-metal codec MUST classify a failure of the bounded-cleanup helper's tasks as `cleanup_refused`, retryable. The VM codec MUST classify `vm_not_found`, `vm_image_locked` and `vm_address_unknown` from the failing task's message, none retryable. A mock rule MUST be able to carry a failure record, classified through the same codec.

#### Scenario: Bounded cleanup refuses a foreign descendant

- **WHEN** a reclaim's bounded cleanup refuses a descendant owned by another UID
- **THEN** the reclaim job's attempt fails with `cleanup_refused`, naming the host and task, and a retry is scheduled

#### Scenario: A VM's domain is missing

- **WHEN** a VM job's task fails reporting that the domain is not found
- **THEN** the job fails with `vm_not_found` and is not retried

#### Scenario: A mocked failure carries a record

- **WHEN** a mock rule fails a bare-metal reclaim with a record naming a tagged helper task
- **THEN** the job fails with `cleanup_refused` as a real run's would

### Requirement: A job keeps its structured failure beside its error

The job authority MUST keep the latest failed attempt's `code`, `message`, `retryable` and redacted `details` on the job, beside its `error` text, which MUST carry the classified message. A job the engine refuses before any executor runs MUST carry `not_dispatchable`; a job whose codec refuses its preparation, `configuration_refused`; an unanticipated failure, `internal_error`; none of them retried.

#### Scenario: A reclaim exhausts its retries

- **WHEN** a reclaim job fails with `cleanup_refused` on its last attempt
- **THEN** the job is `failed`, its structured failure carries `cleanup_refused` and its details, and its `error` names the host, the task and the refusal

#### Scenario: A job names an unregistered host

- **WHEN** a job names a host with no record
- **THEN** it fails with `not_dispatchable` and is not retried

### Requirement: Operator-configured non-retryable substrings are matched against the failure record

A failure whose recorded task message or output, or whose classified message, contains one of `additional_non_retryable_errors` MUST NOT be retried, whatever its class.

#### Scenario: An operator marks a message non-retryable

- **WHEN** `additional_non_retryable_errors` holds `"disk quota exceeded"` and a task fails with a message containing it
- **THEN** the job fails without another attempt

### Requirement: Compute provisioning records operator-relevant events

Compute provisioning MUST declare and record these event kinds, each in the transaction of the change it reports:

- `provisioning.lease_release_failed`, `action_required`, keyed on the lease and its release handle, when a lease enters `release_failed` for any reason, carrying the reason, the message and, when one exists, the latest teardown job and its failure class; it is recorded as a prepared event in the site's release-failure transition;
- `provisioning.teardown_attempt_held`, `action_required`, keyed on the job and its retry count, when a teardown job's attempt fails with an operator-repairable class — `cleanup_refused` — and a retry is scheduled;
- `provisioning.job_finished`, keyed on the job, when any job reaches a terminal status, `info` when it succeeded and `warning` otherwise, carrying its status, action, offering mode, duration, failure class and whether it is an operator's job.

#### Scenario: A teardown fails with a refused cleanup

- **WHEN** a lease's reclaim fails with `cleanup_refused` after its retries and the lease enters `release_failed` with `teardown_failed`
- **THEN** one `provisioning.lease_release_failed` event names the lease, its reason and the class `cleanup_refused`

#### Scenario: A lease's teardown times out

- **WHEN** a lease is still `releasing` past `lease_watchdog_grace_period_seconds`
- **THEN** the lease enters `release_failed` with `teardown_timeout` and one `provisioning.lease_release_failed` event is recorded with it

#### Scenario: A stale release failure is refused

- **WHEN** the lease lifecycle observes a failure for a lease an operator has since force-released
- **THEN** the site refuses the transition and no `provisioning.lease_release_failed` event exists

#### Scenario: A refused cleanup is retried

- **WHEN** a reclaim attempt fails with `cleanup_refused` and a retry is scheduled
- **THEN** one `provisioning.teardown_attempt_held` event names the job, the lease, the host, the retry time and the retries left

#### Scenario: A teardown attempt fails with a class that is not repairable

- **WHEN** a teardown attempt fails with `timed_out` and a retry is scheduled
- **THEN** no `provisioning.teardown_attempt_held` event is recorded

#### Scenario: A long job finishes

- **WHEN** a VM create job succeeds after 2832 seconds
- **THEN** one `provisioning.job_finished` event records it as `info` with `duration_seconds` 2832

### Requirement: The provisioning service delivers events to the sinks its routes select

The provisioning service MUST read an `[Events]` section of sinks, routes, per-table retention, the delivery interval, the operator sinks' maximum age and the finally sink, refuse at startup a route or sink the eventing component refuses, and deliver events on a delivery worker of its own with pause and run-cycle controls.

#### Scenario: Held work is routed to a push sink

- **WHEN** `[Events]` routes `severity = 'action_required'` to an Apprise sink and a lease enters `release_failed`
- **THEN** the Apprise sink receives the `provisioning.lease_release_failed` event

#### Scenario: A route names a sink that is not enabled

- **WHEN** a route names a sink `[Events.sinks]` does not enable
- **THEN** the service refuses to start, naming the route and the sink

### Requirement: An administrator reads events and their delivery state

The provisioning service MUST serve, to its administrator, the events it recorded, filtered by kind, severity, subject or related reference, and each consumer destination's delivery state, and MUST let the administrator resume a parked destination.

#### Scenario: An administrator lists a lease's events

- **WHEN** an administrator lists events related to a lease
- **THEN** every recorded event naming that lease is returned in sequence order

#### Scenario: An administrator resumes a parked peer

- **WHEN** an administrator resumes the parked destination of the storefront peer
- **THEN** the lease-end reports it missed whose events are still retained are delivered to it in order, and any older report stays readable through the authenticated lease read

### Requirement: The capacity-released callback is a consumer of the release event

The capacity-released callback MUST be delivered to the owning storefront, for each release the lease lifecycle makes, by a consumer of `site.capacity_released`, retrying with backoff until acknowledged. A release a caller of the site's own release route asks for MUST draw no callback. A callback the storefront refuses outright — answering 400, 404 or 409 — MUST be abandoned to the finally sink and MUST NOT hold back the callbacks after it. A callback recorded while no storefront is configured MUST stay pending until one is. A callback pending when the service is upgraded MUST be delivered after it.

#### Scenario: A callback is pending at upgrade

- **WHEN** a deployment holding an undelivered capacity-released callback is upgraded
- **THEN** the callback is delivered after the upgrade under the same reservation, even when the upgraded service first starts with no storefront configured

#### Scenario: The storefront refuses a callback

- **WHEN** the storefront answers 404 to a capacity-released callback, for a reservation it does not hold, and later releases follow
- **THEN** that callback is abandoned to the finally sink and the later callbacks are delivered

#### Scenario: A release is asked of the site directly

- **WHEN** a caller of the site's release route releases a reservation
- **THEN** the release is recorded and no capacity-released callback is sent

#### Scenario: No storefront is configured

- **WHEN** the lease lifecycle releases a reservation while no storefront URL is configured, and one is configured later
- **THEN** the callback stays pending meanwhile and is delivered once the storefront is configured

## MODIFIED Requirements

### Requirement: Intended lease ends are reported separately from capacity release

Compute provisioning MUST deliver each `site.lease_ended` event's signed report to the owning storefront through a consumer of the eventing system, keyed by event identity, the report signed with the site's service identity in the transaction that records the event and kept in a table of its own, retained under its own setting, unlimited by default, and never pruned while its event is retained. The consumer MUST hold one destination per configured storefront peer: a destination is parked when its peer answers unsupported, until an administrator resumes it, and on resume receives the reports it missed whose events are still retained; a peer configured beside or in place of another is a new destination that receives no event recorded before it, a first peer receives what was recorded since the consumer's last read, and a peer no longer configured has its destination retired, its undelivered reports, those its consumer had not yet read included, going to the finally sink. A report no longer kept is abandoned to the finally sink rather than retried. Compute provisioning MUST keep acknowledgements separate from the capacity-released callback and expose the same signed report through the authenticated lease read for recovery. A report pending or parked when the service is upgraded MUST be delivered, or stay parked, after it under its original identity. The report MUST state intended end, not prove teardown or free capacity.

#### Scenario: The site crashes after recording an end

- **WHEN** the end transition commits and the process crashes before sending its report
- **THEN** recovery delivers the stored event with its original identity, instant and cause, rather than rebuilding them from the reservation's later state

#### Scenario: An acknowledgement is lost

- **WHEN** the storefront receives a report but its acknowledgement is lost
- **THEN** the consumer retries the same event identity and payload until acknowledged

#### Scenario: An older receiver is unsupported

- **WHEN** the owning storefront responds 404 or explicitly unsupported to a report push
- **THEN** the consumer parks that peer's destination and the signed report stays readable for authenticated pull recovery; transient failures instead retry

#### Scenario: The owning storefront's peer is reconfigured

- **WHEN** an operator configures another storefront peer while reports for the previous peer are pending, or recorded and not yet read by the consumer
- **THEN** none of those reports is sent to the new peer, and the previous peer's destination is retired, its pending reports written to the finally sink and still readable through the authenticated lease read

#### Scenario: A pending report outlives its retention

- **WHEN** an operator sets a finite report retention and a report's delivery is still pending past it, its peer down
- **THEN** the report is kept while its event is, and delivered when the peer returns

#### Scenario: A report is pending at upgrade

- **WHEN** a deployment holding an undelivered or parked lease-end report is upgraded
- **THEN** after the upgrade the report is delivered, or stays parked, under its original event identity and signed payload

#### Scenario: Teardown completes after the report

- **WHEN** the site reports an intended end and physical teardown completes later
- **THEN** the separate capacity-released callback retains its own acknowledgement and is still the signal of proven capacity return

#### Scenario: The storefront recovers by reading the lease

- **WHEN** a storefront misses a pushed report and reads the lease
- **THEN** the authenticated response contains the original report's payload and site proof for verbatim retention and return to the buyer
