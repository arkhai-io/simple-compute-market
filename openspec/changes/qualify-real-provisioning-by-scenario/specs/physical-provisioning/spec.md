## ADDED Requirements

### Requirement: A VM host's diagnostics are read through an operator job

The VM operator surface MUST offer a host diagnostics action that runs as a job on a
registered host, like the VM list, and reports its boot identity, uptime, kernel, the
count of running guests, and for `libvirtd.service`, `frpc-buyers.service` and an
optional caller-named management unit, the unit's active state, invocation ID, main PID,
restart count, active-enter time and result. A caller-named unit MUST match systemd's
unit-name syntax or be refused before any job is queued. The operator client MUST
return the result as a typed value parsed from the succeeded job and MUST refuse a
malformed fact. In the mock profile the action MUST answer with default output rendered
from the job's parameters.

#### Scenario: Diagnostics are read from a real host

- **WHEN** an operator requests host diagnostics naming a management unit
- **THEN** a job runs on that host and its typed result reports each unit's invocation
  ID and restart count

#### Scenario: An invalid unit name is named

- **WHEN** the request names a management unit that is not a systemd unit name
- **THEN** it is refused and no job is queued

#### Scenario: A mock-profile host is diagnosed

- **WHEN** the provisioning service runs its mock profile
- **THEN** the diagnostics job succeeds with default output the typed result parses
