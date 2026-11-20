## ADDED Requirements

### Requirement: A host's pinned keys are stated or captured by an operator

An `ssh` connection MAY state `host_keys`: a non-empty list of OpenSSH public keys, each its key type and base64 encoding without a comment, which the codec MUST parse and MUST refuse when empty or malformed. The keys a host's connection states are its pin. A submission that omits `host_keys` MUST keep the stored pin, whatever else it changes, the connection's `ssh_host` and `ssh_port` included. The host definitions document and its canonical export MUST carry `host_keys` as a public field; the INI import carries none and MUST keep a stored pin. A pin MUST be replaced only by a submission stating other keys or by a capture with `replace`.

A connectivity check of a host with no pin MUST connect accepting the key the host presents into a file it discards, MUST store nothing, and MUST report the presented key's type and SHA-256 fingerprint with the endpoint `[ssh_host]:ssh_port`; a check of a pinned host MUST report whether the presented key matches the pin. `POST /api/v1/hosts/{host}/host-keys/capture`, admitted to the administrator alone, MUST probe the host again and MUST record the presented key as the host's pin only when its fingerprint equals the one the request names. It MUST answer 404 for an unknown host; 422 naming the kind for a host whose connection kind presents no key, and 422 naming the field for an empty or malformed fingerprint; and, recording nothing, 409 with the code `host_key_mismatch` naming the endpoint and the presented fingerprint when the host presents another key, 409 with the code `host_key_pinned` naming the pinned fingerprints for a host that already has a pin unless the request states `replace`, and 409 with the code `no_host_key_presented` naming the endpoint and the probe's reason when the probe reaches no SSH handshake. A capture that records a pin MUST answer with the endpoint and the pinned fingerprints. The provisioning family client MUST offer the capture with the fingerprint and an optional `replace`, and MUST surface each refusal's code.

#### Scenario: A host is registered with its key

- **WHEN** an operator registers a host whose `ssh` connection states `host_keys: ["ssh-ed25519 AAAAC3Nz…"]`
- **THEN** the host is stored with that pin, and its read and the export carry it

#### Scenario: A connection states an empty pin

- **WHEN** a host is submitted with `host_keys: []`
- **THEN** the submission is refused naming the field, and nothing is stored

#### Scenario: An update omits the pin

- **WHEN** a pinned host is updated with a connection that changes its `ssh_port` and states no `host_keys`
- **THEN** the host keeps its pin at the new port

#### Scenario: An operator checks an unpinned host

- **WHEN** an operator checks connectivity to a host with no pin
- **THEN** the result reports the presented key's fingerprint and endpoint, and no pin is stored

#### Scenario: An operator captures the key they compared

- **WHEN** an operator captures an unpinned host's key naming the fingerprint the host presents
- **THEN** the presented key becomes the host's pin

#### Scenario: The host presents another key at capture

- **WHEN** an operator captures a host's key naming a fingerprint other than the one the host presents
- **THEN** the capture answers 409 with `host_key_mismatch` naming the presented fingerprint, and no pin is stored

#### Scenario: A capture meets a pinned host

- **WHEN** an operator captures a pinned host's key without `replace`
- **THEN** the capture answers 409 with `host_key_pinned`, and the pin is unchanged

#### Scenario: An operator replaces a pinned host's key by capture

- **WHEN** an operator captures a pinned host's key with `replace`, naming the fingerprint the host presents
- **THEN** the presented key becomes the host's pin in place of the old one

#### Scenario: A capture reaches no handshake

- **WHEN** an operator captures the key of a host whose probe times out or is refused before any key is presented
- **THEN** the capture answers 409 with `no_host_key_presented` naming the endpoint and the probe's reason, and no pin is stored

#### Scenario: A capture names a malformed fingerprint

- **WHEN** an operator captures a host's key naming an empty fingerprint, or one that is not `SHA256:` followed by base64
- **THEN** the capture answers 422 naming the field, and no probe runs

#### Scenario: A capture names an unknown host or a kind without keys

- **WHEN** an operator captures the key of a host that is not registered, or of one whose connection kind presents no key
- **THEN** the capture answers 404 for the unknown host, and 422 naming the kind for the other

#### Scenario: A connectivity check reaches no handshake

- **WHEN** an operator checks connectivity to a host that presents no key before the probe fails
- **THEN** the result is unreachable with the probe's reason, and its `host_key` is null

#### Scenario: An INI import names a pinned host

- **WHEN** an inventory naming a pinned host is imported
- **THEN** the host keeps its pin

### Requirement: The Ansible executor reaches only hosts matching their pinned key

Every inventory the Ansible executor or its connectivity probe renders MUST verify the host's key against its pin: a transient, owner-only `known_hosts` holding the pin under `[ssh_host]:ssh_port`, removed when the run ends as a decrypted key file is, and host variables enabling strict checking against that file alone, which no Ansible configuration an operator names can override. Before recording a job's execution start, the Ansible executor MUST make one SSH connection to the host against its pin that runs nothing on the host. A host with no pin, unless it is pending adoption, or whose presented key matches no pinned key, MUST fail the job with no execution start recorded, unretried, with an error naming the host, its endpoint, the presented and pinned fingerprints, and how to recover, carrying no key material. A connectivity check of a pinned host whose key does not match MUST answer it unreachable with the same reason. Once any Ansible executor is real, readiness MUST name every enabled host with no pin. The mock executor reaches no host and MUST NOT read pins.

#### Scenario: A job runs against a pinned host

- **WHEN** a job is dispatched against a host whose presented key matches its pin
- **THEN** the playbook runs with strict host-key checking against a transient `known_hosts`, which is removed when the run ends

#### Scenario: A host presents another key

- **WHEN** a job is dispatched against a host whose presented key matches no pinned key
- **THEN** the job fails before its execution start is recorded, unretried, with an error naming the host, its endpoint and both fingerprints, and no playbook runs

#### Scenario: A teardown is refused for its host key

- **WHEN** a teardown is refused for its host's key and the operator then captures the host's new key
- **THEN** the teardown counts as never started and is run again

#### Scenario: A job meets an unpinned host

- **WHEN** a job is dispatched against a host with no pin that is not pending adoption
- **THEN** it fails before any connection with an error naming the host and how to pin it

#### Scenario: An operator's configuration turns checking off

- **WHEN** the profile's `ansible_cfg` names a configuration stating `host_key_checking = False` and its own `ssh_args`
- **THEN** the command a job runs still checks the host strictly against its pin

#### Scenario: A lane runs the mock executor

- **WHEN** a job runs under the mock executor against a host registered with no pin
- **THEN** it runs as it would without pins

### Requirement: Hosts deployed before pins are adopted before their first job

The provisioning migration that rewrites `ssh` connections to version 3 MUST mark every host it rewrites as pending adoption, on the host record outside its connection; no other write marks a host, and neither the host definitions document nor the export carries the mark. For a pending host, the Ansible executor's check before a job's start, and a connectivity check, MUST connect accepting the presented key into an empty file, running nothing on the host, and MUST record that key as the host's pin and clear the mark in one write that takes effect only while the host is still pending. Whichever adoption's write takes effect, a job MUST then make its check before the start against the committed pin, as for any pinned host, and its playbook MUST be checked against that committed pin, never against the key the job observed. A submission stating `host_keys`, or a capture, MUST clear the mark; a capture that meets a host an adoption has pinned answers as for any pinned host. Once any Ansible executor is real, readiness MUST list pending hosts without reporting itself not ready for them.

#### Scenario: A deployed host's first job after the upgrade

- **GIVEN** a host the version-3 migration marked pending adoption
- **WHEN** a job is dispatched against it
- **THEN** the key it presents becomes its pin, the mark is cleared, and the playbook runs checked against that pin

#### Scenario: Two first jobs adopt one host

- **GIVEN** a host pending adoption
- **WHEN** two jobs against it are dispatched together and their adopting connections are answered with different keys
- **THEN** exactly one key becomes the pin, and the job whose key lost fails before its execution start is recorded, with no playbook run against the key it observed

#### Scenario: A capture races an adoption

- **GIVEN** a host pending adoption
- **WHEN** a job's adoption commits a pin before an operator's capture without `replace` reaches it
- **THEN** the capture answers 409 with `host_key_pinned`, and the adopted pin is unchanged

#### Scenario: A host registered after the upgrade

- **WHEN** a host is registered with no pin after the migration ran
- **THEN** it is not pending adoption, and a job against it is refused until it is pinned

#### Scenario: An operator pins a pending host

- **WHEN** an operator states `host_keys` for a pending host, or captures its key
- **THEN** the mark is cleared, and the stated or captured key is its pin

### Requirement: A VM guest reaches no other guest on its host

Every VM guest MUST be created with its interface's bridge port isolated and with libvirt's `clean-traffic` filter binding it to its MAC address and the address it leased by DHCP. VM host preparation MUST drop forwarding from the guests' bridge back to it, in a chain of the host kit's own reached before any rule libvirt or UFW installs, and MUST keep that rule first across a restart of libvirt, a reload of UFW, and a reboot. A host whose libvirt lacks port isolation or the nwfilter driver MUST fail host preparation naming what is missing. A guest's address discovery, DHCP reservation, and teardown are unchanged.

#### Scenario: A guest probes another guest on its host

- **GIVEN** two guests running on one host
- **WHEN** one sends ARP, ICMP and TCP to the other, directly or through the bridge's gateway
- **THEN** none reaches the other guest

#### Scenario: A guest claims another guest's address

- **WHEN** a guest sends ARP claiming the address another guest leased
- **THEN** the frames are dropped, and the other guest's buyer connections still reach it

#### Scenario: A GPU guest is created

- **WHEN** a guest with a passed-through GPU is created
- **THEN** its interface is isolated and filtered as a CPU guest's is

### Requirement: A VM guest reaches only DHCP and DNS on its host and no undeclared private destination

VM host preparation MUST accept, from the guests' bridge to the host, only DHCP, DNS to the bridge's address, and traffic of connections already established, and MUST drop everything else. It MUST drop forwarding from the guests' bridge to link-local addresses and to private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`), except traffic of connections already established and each destination the host-kit variable `guest_allowed_private_destinations` lists, which is empty by default. These rules MUST sit in chains of the host kit's own, reached before any rule libvirt or UFW installs and kept first across a restart of libvirt and a reload of UFW; host preparation MUST NOT leave in place a rule accepting all traffic from the guests' bridge to the host. Connections the host opens to a guest and DNATed buyer connections, from public or private addresses, are unaffected.

#### Scenario: A guest reaches a service on its host

- **WHEN** a guest connects to a port on its host other than DHCP or DNS
- **THEN** the connection is dropped

#### Scenario: A guest reaches the cloud metadata address

- **WHEN** a guest connects to `169.254.169.254`
- **THEN** the connection is dropped

#### Scenario: A seller lists a private destination

- **WHEN** `guest_allowed_private_destinations` lists a private address and a guest connects to it
- **THEN** the connection is forwarded, while other private addresses stay dropped

#### Scenario: A buyer reaches their guest

- **WHEN** a buyer connects to their guest's forwarded or relayed port
- **THEN** the connection reaches the guest, and the host's own SSH into the guest still works

#### Scenario: A buyer connects from a private address

- **WHEN** a buyer whose address is in a private range connects directly to their guest's forwarded port
- **THEN** the connection is established and the guest's replies reach the buyer

#### Scenario: The host's firewall rules are reloaded

- **GIVEN** a prepared host whose UFW is enabled
- **WHEN** libvirt is restarted and UFW is reloaded
- **THEN** a guest still reaches DHCP and DNS on its host, and still cannot reach another host port or an unlisted private destination

### Requirement: VM host preparation converges running guests

VM host preparation MUST isolate the bridge port of every running guest without interrupting its link, MUST apply the `clean-traffic` filter to it live where libvirt accepts that and otherwise at the guest's next start, and MUST write both into the guest's saved definition so that a restart or a host reboot keeps them. It MUST report every running guest it could not converge.

#### Scenario: A host prepared before isolation is prepared again

- **GIVEN** a host running guests created with ports that are not isolated
- **WHEN** VM host preparation runs on it
- **THEN** every running guest's port is isolated without its buyer's session being interrupted, and its saved definition carries the isolation and the filter

#### Scenario: A guest cannot be converged

- **WHEN** host preparation cannot isolate a running guest's port
- **THEN** it reports the guest by name

## MODIFIED Requirements

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so that a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so that a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

The registry MAY also record a tenant-facing port, `public_port`, for a host. The port is optional on an SSH connection. A connection submission MUST state its version; the host contract carries no default. A rendered inventory MUST emit `public_port` for a host whose record states one, and MUST NOT emit it for a host whose record states none. A host whose record states no tenant-facing port MUST be stored with no `public_port` field, not even a null one. A `public_port` supplied through the INI input format MUST be preserved, and a value that is not a port number between 1 and 65535 MUST cause its entry to be rejected, as for `ansible_port`. A connection built from the INI format or the typed connection factory MUST use the served SSH connection version.

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
- **THEN** it is stored at the served version with no `public_port` field, and its rendered inventory carries the connection's own address and port

#### Scenario: A version-1 or unversioned connection is submitted

- **WHEN** a host is submitted with an `ssh` connection at a version the registry does not serve, or stating no version
- **THEN** an unsupported submission is refused naming the version served; an
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
composition MUST refuse two codecs for one kind. The `ssh` codec serves version 3. A
connection MUST be built by the codec of its own kind, at the version that codec serves.
A connection at a kind no codec serves, or at another version than its kind's codec
serves, MUST be refused naming the kinds or the version that is served. A reader of a
stored connection MUST check its kind and version before reading its fields, and MUST
refuse a version it does not serve rather than read it as another, so a host stored at a
version no longer served runs no work until it is submitted again at the served version.
Such a submission MUST carry forward a protected value it still needs and does not
resubmit, whatever the previous connection's version, as opaque material it neither
reads nor decrypts. A stored connection MUST NOT be rewritten to another version except
by a submission that states that version or by a recorded migration whose mapping from
the stored version is exact; no reader upgrades a stored connection. The provisioning
migration chain MUST rewrite every host's `ssh` connection stored at version 1 to
version 2, and every one stored at version 2 to version 3, each with the same public
fields and protected values, version 3 stating no `host_keys`; a job holds no copy of a
connection, reading its host's when it is dispatched.

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

#### Scenario: A host stored at an earlier version is submitted again at version 3

- **WHEN** a host stored at an `ssh` version no longer served, whose key is protected,
  with no key file, is updated with a version-3 connection that restates its public
  fields and submits no key
- **THEN** the host is stored at version 3, its protected key is kept unchanged, and work
  runs against it again

#### Scenario: A host stored at an earlier version with a key file is submitted again at version 3

- **WHEN** a host stored at an `ssh` version no longer served, whose key is a file, is
  updated with a version-3 connection restating its public fields, `key_path` included
- **THEN** the host is stored at version 3 with the same key file; an update omitting
  `key_path` names no key and is refused

#### Scenario: A host stored at version 1 is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 is updated with a version-2 connection
- **THEN** the submission is refused naming version 3, the version served, and the
  stored host is unchanged

#### Scenario: A host stored at version 1 with a key file is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 whose key is a file is updated with a
  version-2 connection restating its public fields, `key_path` included
- **THEN** the submission is refused naming version 3, and the stored host is unchanged

#### Scenario: A host stored at version 1 is imported again

- **WHEN** an inventory naming a host stored at an `ssh` version no longer served is
  imported
- **THEN** the host is stored at version 3 with the connection and key its entry names

#### Scenario: A provisioning database holding version-1 connections is migrated

- **WHEN** the provisioning migration command runs against a database with hosts stored
  at `ssh` versions 1 and 2 and a queued create job and a queued teardown job naming
  those hosts
- **THEN** the hosts are stored at `ssh` version 3 with the same public fields and
  protected values and no `host_keys`, each marked pending adoption, the jobs are
  unchanged, and the create and the teardown run against version-3 connections when
  they are dispatched

#### Scenario: A version-1 connection's fields are not valid at version 2

- **WHEN** the provisioning migration finds a host's stored `ssh` version 1 connection
  whose public fields are invalid at version 2
- **THEN** the migration fails naming the host, and nothing is rewritten

### Requirement: Every provisioning route admits the administrator

Every route on the provisioning service's route table MUST admit the `admin` role, in
addition to any other role it admits, since every resource the service holds — hosts,
relays, leases, jobs, and the capacity and pools it hosts — is its operator's. A route
contract a domain contributes that does not admit `admin` MUST be refused when the table
is assembled.

#### Scenario: An operator calls a storefront route

- **WHEN** a request signed by the provisioning administrator calls a route that also
  admits the seller, such as lease termination or fulfillment begin
- **THEN** it is authorized as it would be for the seller

#### Scenario: A domain contributes a seller-only route

- **WHEN** a domain declares a route whose roles omit `admin`
- **THEN** the provisioning service refuses to assemble its route table

### Requirement: Host connectivity is probed by connection kind

A host connectivity check MUST run the probe registered for the host's connection kind and
return a neutral connectivity result. A host whose connection kind has no registered probe
MUST be refused. The probe's execution resources MUST be composed by the provisioning
service, not borrowed from a domain's runtime. The result MUST carry, for a kind whose
hosts present a key, a `host_key` member stating the endpoint, whether the host is pinned,
the presented key's type and fingerprint, and for a pinned host whether it matched and the
pinned fingerprints; that member MUST be null when the probe failed before the host
presented a key.

#### Scenario: A bare-metal host is probed

- **WHEN** an operator checks connectivity to a registered bare-metal host with an `ssh`
  connection
- **THEN** the `ssh` probe runs over the service's own runner and returns the neutral
  result with its `host_key` member
