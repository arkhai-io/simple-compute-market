## ADDED Requirements

### Requirement: Ansible output is kept only redacted unless an operator configures otherwise

The provisioning service's packaged Ansible configuration MUST NOT name a log file. The output of a playbook run MUST be kept only as the job's logs, redacted, and the output of a connectivity check, including the text of an error running it, MUST be returned only redacted in the check's result: the value of a `password` field, an SSH identity-file argument, and an `sshpass` password are replaced. A probe runs no domain's playbook, and its inventory names a key only by the path of a transient file, so no domain's secret variable reaches its output. An operator whose `ansible_cfg` names a configuration stating a log file receives Ansible's unredacted output there, and the service MUST NOT override that configuration.

#### Scenario: A playbook runs under the packaged configuration

- **WHEN** a real playbook runs and the profile names no `ansible_cfg`
- **THEN** no Ansible log file is written, and the job's logs hold its redacted output

#### Scenario: A connectivity check's output carries a secret

- **WHEN** the output of a connectivity check contains the value of a `password` field, an SSH identity-file argument, or an `sshpass` password
- **THEN** the check's result carries that output with the value redacted

#### Scenario: An operator configures a log file

- **WHEN** the profile's `ansible_cfg` names a configuration stating `log_path`
- **THEN** the service runs Ansible under that configuration unchanged

### Requirement: A protected key that cannot be decrypted is named, not hidden

When an `ssh` connection's protected private key cannot be decrypted with the configured key, because it was protected under another key, its ciphertext is not a token the configured key can read, or no key is configured, the codec MUST raise an error naming the host and how to recover, carrying no ciphertext or key material. The caller MUST give the codec the host's id, so that every caller reports one failure with one message. A job MUST fail with that message and MUST NOT be retried, since a retry meets the same configuration. A connectivity check MUST answer the host unreachable with that message as its detail. Once any Ansible executor is real, the Ansible readiness component MUST report itself not ready, naming the host, MUST report every other host as it would without it, and MUST check a protected key only by decrypting it in memory. A stored protected value with no ciphertext, which no write stores, is not a connection the host authority can read: every read returning that host's connection fails, a listing as a whole, and the Ansible readiness component reports the host registry unreadable and no host.

#### Scenario: A job runs against a host whose key was protected under another key

- **WHEN** a job is dispatched against a host whose protected key does not decrypt under the configured key
- **THEN** it fails, unretried, with an error naming the host and carrying no ciphertext, and no key file remains

#### Scenario: A connectivity check meets such a host

- **WHEN** an operator checks that host's connectivity
- **THEN** the result is unreachable, with the same reason as its detail

#### Scenario: System status is read with such a host enabled

- **WHEN** system status is read while that host is enabled and an Ansible executor is real
- **THEN** the `ansible` component is not ready, its reasons naming the host, and its key is reported as not existing, while every other enabled host's key is reported as it would be without it

## MODIFIED Requirements

### Requirement: Connection secrets stay protected

Connection secrets MUST be persisted, stored, and passed to executors only in a protected
representation (a scheme and its ciphertext). A secret submitted with a host's
connection MUST be turned into a protected value by that connection kind's codec before
it is persisted, and the submitted secret MUST NOT be stored, returned, or logged. The
host authority MUST treat a protected value as opaque and MUST NOT encrypt or decrypt it.
It MUST return a protected value only through its internal reads for execution and for an
executor's readiness, and MUST keep it out of every other read and every API, logging, and
error surface. Only a connection codec MAY decrypt a protected value: just in time for
execution, or in memory to check that it decrypts when an executor's readiness is
reported, the plaintext then discarded at once and never written to storage. Plaintext
MUST stay confined to the submitting request, the codec, and the transient storage the
connection requires for execution.

#### Scenario: A host is registered with an embedded key

- **WHEN** an operator registers a host whose `ssh` connection submits a private key
- **THEN** the `ssh` codec protects it, the host authority stores only the protected
  value, and its responses name the protected value and its scheme without the ciphertext

#### Scenario: A job runs against a host with an embedded key

- **WHEN** an executor runs a job against that host
- **THEN** it receives the protected envelope, and only the `ssh` codec decrypts the key,
  into transient storage removed when execution ends

#### Scenario: Readiness checks a host with an embedded key

- **WHEN** system status is read while that host is enabled
- **THEN** the Ansible readiness component receives the protected envelope through the host
  authority's internal read, the `ssh` codec decrypts the key in memory only, nothing is
  written to storage, and the component's detail carries no plaintext or ciphertext

### Requirement: Execution readiness is reported in system status

The provisioning service's system status MUST report whether execution is mocked, as a
boolean for the deployment and per composed executor by offering mode, derived from the
composed executors rather than from deployment profiles, together with each contributed
readiness component's readiness and a versioned detail. A component that is not ready MUST
degrade the status. The status MUST NOT disclose a database URL or any credential.
Readiness MUST have no route of its own, and an execution implementation MUST contribute
its readiness rather than serve it. Once any Ansible executor is real, the Ansible
readiness component MUST refuse an enabled host's `ssh` connection exactly as execution
refuses it, reporting itself not ready with a reason naming the host, and MUST report
every other host as it would without it; it MUST skip a host of another connection kind.

#### Scenario: Every executor is mocked

- **WHEN** the service runs with every composed executor mocked
- **THEN** status reports execution as mocked, and lists each offering mode's executor as
  mocked

#### Scenario: A domain's playbook is missing

- **WHEN** the Ansible executor for one offering mode names a playbook that does not exist
- **THEN** the Ansible component reports that playbook and is not ready, and the status is
  degraded

#### Scenario: An enabled host is stored at an unserved connection version

- **WHEN** system status is read while an enabled host is stored at `ssh` version 1 and an
  Ansible executor is real, whether its key is a file that exists or a protected key that
  decrypts
- **THEN** the Ansible component is not ready, its reasons naming the host and the version
  served, and every other enabled host is reported as it would be without it
