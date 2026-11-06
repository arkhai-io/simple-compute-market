## ADDED Requirements

### Requirement: Ansible output is kept only redacted unless an operator configures otherwise

The provisioning service's packaged Ansible configuration MUST NOT name a log file. The output of a playbook run and of a connectivity check MUST be kept only as the job's logs or the check's result, redacted. An operator whose `ansible_cfg` names a configuration stating a log file receives Ansible's unredacted output there, and the service MUST NOT override that configuration.

#### Scenario: A playbook runs under the packaged configuration

- **WHEN** a real playbook runs and the profile names no `ansible_cfg`
- **THEN** no Ansible log file is written, and the job's logs hold its redacted output

#### Scenario: An operator configures a log file

- **WHEN** the profile's `ansible_cfg` names a configuration stating `log_path`
- **THEN** the service runs Ansible under that configuration unchanged

### Requirement: A protected key that cannot be decrypted is named, not hidden

When an `ssh` connection's protected private key cannot be decrypted with the configured key, because it was protected under another key or no key is configured, the codec MUST raise an error naming the host and how to recover, carrying no ciphertext or key material. A job MUST fail with that message and MUST NOT be retried, since a retry meets the same configuration. A connectivity check MUST answer the host unreachable with that message as its detail. Once any Ansible executor is real, the Ansible readiness component MUST report itself not ready, naming the host, and MUST check a protected key only by decrypting it in memory.

#### Scenario: A job runs against a host whose key was protected under another key

- **WHEN** a job is dispatched against a host whose protected key does not decrypt under the configured key
- **THEN** it fails, unretried, with an error naming the host and carrying no ciphertext, and no key file remains

#### Scenario: A connectivity check meets such a host

- **WHEN** an operator checks that host's connectivity
- **THEN** the result is unreachable, with the same reason as its detail

#### Scenario: System status is read with such a host enabled

- **WHEN** system status is read while that host is enabled and an Ansible executor is real
- **THEN** the `ansible` component is not ready, its reasons naming the host, and its key is reported as not existing
