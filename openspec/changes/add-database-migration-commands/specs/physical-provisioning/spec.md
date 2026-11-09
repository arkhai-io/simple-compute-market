## MODIFIED Requirements

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so that a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so that a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

The registry MAY also record a tenant-facing port, `public_port`, for a host. The port belongs to version 2 of the `ssh` connection, which is version 1 with that one optional field, and version 2 is the only version of the kind the registry serves: every `ssh` connection is submitted and stored at version 2, whether it states a tenant-facing port, states none, or states it as null. A connection submission MUST state its version; the host contract carries no default. A rendered inventory MUST emit `public_port` for a host whose record states one, and MUST NOT emit it for a host whose record states none. A host whose record states no tenant-facing port MUST be stored with no `public_port` field, not even a null one. A `public_port` supplied through the INI input format MUST be preserved, and a value that is not a port number between 1 and 65535 MUST cause its entry to be rejected, as for `ansible_port`. A connection built from the INI format or the typed connection factory MUST be submitted at version 2.

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

#### Scenario: An inventory file supplies a tenant-facing port

- **WHEN** an INI inventory entry carrying `public_port` is imported
- **THEN** the port is stored against the host and appears as `public_port` in the rendered inventory for that host

#### Scenario: An inventory file supplies a malformed tenant-facing port

- **WHEN** an INI inventory entry carries a `public_port` that is not a port number between 1 and 65535
- **THEN** that entry is rejected with a warning naming the host, other entries in the same file are still imported, and no host is registered with a substituted or missing tenant-facing port

#### Scenario: A host is registered with no tenant-facing port

- **WHEN** a host is registered or imported with an `ssh` connection that states no tenant-facing port
- **THEN** it is stored at version 2 with no `public_port` field, and its rendered inventory carries the connection's own address and port

#### Scenario: A version-1 or unversioned connection is submitted

- **WHEN** a host is submitted with an `ssh` connection at version 1, or stating no version
- **THEN** a version-1 submission is refused naming version 2, the version served; an
  unversioned submission is refused as missing its required `version`; and nothing is
  stored

### Requirement: Host connections are typed by their implementation's codec

A host's connection MUST be held as a connection envelope (a kind, a version, public
fields, and protected values) whose kind names the codec of the implementation
distribution that supports it. Compute provisioning MUST NOT define per-kind connection
fields; it validates an envelope through its codec. An executor MUST receive an immutable
execution-host value, not the persistence record, and MUST refuse a connection kind it
does not support.

A codec MUST validate the public fields it defines strictly, for every submission alike
— the host API, an INI import, and a host definitions document: a value of the wrong
type, such as a quoted number, MUST be refused rather than coerced.

A deployment MUST register one codec per kind, and each codec serves one version;
composition MUST refuse two codecs for one kind. A connection MUST be built by the codec
of its own kind, at the version that codec serves. A connection at a kind no codec
serves, or at another version than its kind's codec serves, MUST be refused naming the
kinds or the version that is served. A reader of a stored connection MUST check its kind
and version before reading its fields, and MUST refuse a version it does not serve
rather than read it as another, so a host stored at a version no longer served runs no
work until it is submitted again at the served version. Such a submission MUST carry
forward a protected value it still needs and does not resubmit, whatever the previous
connection's version, as opaque material it neither reads nor decrypts. A stored
connection MUST NOT be rewritten to another version except by a submission that states
that version or by a recorded migration whose mapping from the stored version is exact;
no reader upgrades a stored connection. The provisioning migration chain MUST rewrite
every host's `ssh` connection stored at version 1 to version 2 with the same public
fields and protected values; a job holds no copy of a connection, reading its host's
when it is dispatched.

#### Scenario: A compute domain needs another connection kind

- **WHEN** a domain's executor reaches its targets by a means other than SSH
- **THEN** an implementation distribution adds a codec for that kind, and neither the host
  authority's model nor the executor contract changes

#### Scenario: A connection quotes a number

- **WHEN** a host is submitted through the host API with an `ssh` connection whose
  `ssh_port` is the string `"2222"`
- **THEN** the submission is refused naming the field, and nothing is stored

#### Scenario: A connection states a version no codec serves

- **WHEN** a host is submitted with an `ssh` connection at a version other than the one the
  registered `ssh` codec serves
- **THEN** the submission is refused naming the version served, and nothing is stored

#### Scenario: A stored connection is at an unsupported version

- **WHEN** an execution path reads a stored connection whose version its codec does not
  serve
- **THEN** it refuses the connection before any playbook runs, rather than reading it
  under another version's fields

#### Scenario: A host stored at version 1 is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 whose key is protected, with no key file,
  is updated with a version-2 connection that restates its public fields and submits
  no key
- **THEN** the host is stored at version 2, its protected key is kept unchanged, and work
  runs against it again

#### Scenario: A host stored at version 1 with a key file is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 whose key is a file is updated with a
  version-2 connection restating its public fields, `key_path` included
- **THEN** the host is stored at version 2 with the same key file; an update omitting
  `key_path` names no key and is refused

#### Scenario: A host stored at version 1 is imported again

- **WHEN** an inventory naming a host stored at `ssh` version 1 is imported
- **THEN** the host is stored at version 2 with the connection and key its entry names

#### Scenario: A provisioning database holding version-1 connections is migrated

- **WHEN** the provisioning migration command runs against a database with hosts stored
  at `ssh` version 1 and a queued create job and a queued teardown job naming those hosts
- **THEN** the hosts are stored at `ssh` version 2 with the same public fields and
  protected values, the jobs are unchanged, and the create and the teardown run against
  version-2 connections when they are dispatched

#### Scenario: A version-1 connection's fields are not valid at version 2

- **WHEN** the provisioning migration finds a host's stored `ssh` version 1 connection
  whose public fields the version-2 codec refuses
- **THEN** the migration fails naming the host, and nothing is rewritten
