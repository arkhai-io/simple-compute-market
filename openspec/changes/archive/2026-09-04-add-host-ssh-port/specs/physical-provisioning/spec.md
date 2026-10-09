## ADDED Requirements

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so that a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so that a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

#### Scenario: A host is registered on a tunnel port

- **WHEN** a host is registered with an SSH port other than 22
- **THEN** the recorded port is returned by the host endpoints and appears as `ansible_port` in every rendered inventory for that host

#### Scenario: A host is registered without a port

- **WHEN** a host is registered with no SSH port supplied
- **THEN** the registry records port 22 and rendered inventories state it explicitly

#### Scenario: An inventory file supplies a port

- **WHEN** an INI inventory carrying `ansible_port` is imported
- **THEN** the port is stored against the host and survives to the rendered inventory the provisioner connects with

#### Scenario: An inventory file supplies a malformed port

- **WHEN** an INI inventory entry carries an `ansible_port` that is not a port number between 1 and 65535
- **THEN** that entry is rejected with a warning naming the host, other entries in the same file are still imported, and no host is registered with a substituted port
