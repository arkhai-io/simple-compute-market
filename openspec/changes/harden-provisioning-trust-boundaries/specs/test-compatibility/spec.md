## ADDED Requirements

### Requirement: VM guest isolation is proven on a real host

An external-topology module, `e2e_vm_guest_isolation`, MUST prove VM guest isolation on a configured real-provisioning target by extending the real VM scenario's two deals on one host, adding its stages while both guests run and the first holds a session with a liveness check, and sharing that scenario's teardown. It MUST belong to no default lane and MUST report a blocked skip without the target.

A VM target MAY state, at version 2, a `guest_isolation` section naming a harness-local operator route to the host — its address, port, user, and the path of a key the harness references and never copies — and MAY name two private destinations, `refused` and `listed`, neither of which needs to answer. The module MUST perform every host-side step through that route alone, running fixed operator code under `sudo -n`: restarting libvirtd, reloading UFW, reading the guest policy's chains and rule counters, planting a guest unconverged, and running the host kit's installed convergence command. Guest-side probes MUST run as fixed code in a guest through the shared SSH helper. A refusal of a host port, of a link-local destination, or of a private destination MUST count only when the matching policy rule's counter rose across the probe, and a listed destination's forwarding only when its accept counter rose. The module MUST confirm from the policy's chain that the `listed` destination is admitted and the `refused` one is not.

The module MUST report, as made, failed, or unproven, each observation: guest-to-guest ARP, ICMP and TCP refused, directly and through the gateway (O1); an ARP claim of the other guest's address dropped while its buyer still reaches it, with the filter's parameters in the guest's live definition (O2); DHCP and DNS passing and another host port refused (O3); the link-local metadata address refused (O4); the unlisted private destination refused and the listed one forwarded (O5); a buyer from a private address reaching their guest (O6); O3 to O5 holding after a libvirtd restart and after a UFW reload, with the policy's jumps first (O7); and a guest planted unconverged converged with its session's longest gap at most five seconds, its port isolated, its filter bound or recorded as waiting for its next start, and its saved definition carrying both (O8). A stage whose input the target does not name MUST skip naming it.

#### Scenario: The target names no operator route

- **WHEN** the module runs against a VM target with no `guest_isolation` section
- **THEN** every host-side stage skips naming `guest_isolation`, and every observation but O1 and O6 is unproven naming it

#### Scenario: A refusal the policy did not make

- **WHEN** a guest's connection to a private destination gets no answer while the matching drop rule's counter is unchanged
- **THEN** the stage fails rather than counting the refusal

#### Scenario: Buyers reach the guests through a relay

- **WHEN** the VM target's access is a relay
- **THEN** the stage observing a private-source buyer skips naming the route it lacks, and O6 is unproven

#### Scenario: A planted guest is converged

- **WHEN** the module clears the first guest's port isolation, filter and saved definition through the operator route and runs the convergence command
- **THEN** the first guest's session shows no gap over five seconds, its port is isolated, its saved definition carries the isolation and the filter, and its probes of the other guest are refused again

## MODIFIED Requirements

### Requirement: A real-provisioning target is a typed, versioned settings section

The real-provisioning scenarios' target MUST be read from a versioned settings section
loaded from a profile file the repository ignores, beside a committed example whose
values are visibly fictitious. The section MUST be validated before any stage runs: a
missing or misspelled field MUST fail naming the field, an unknown version MUST be
refused, and a field that does not belong to a host's domain or access mode MUST be
refused. Version 2 describes a list of hosts, at most one per domain, each with its
domain, its identity, the connection the provisioning service reaches it at (address,
user, port, and the path at which the service reads its key), its access — a relay
named by its identifier, or direct access with a tenant address — and the capacity it
sells; a VM host also states the listing shape its scenario publishes, which MUST fit
twice within its capacity, and a bare-metal host its physical machine identity and its
SSH host public key. A relay named by a host is resolved in the provisioning service
that host's scenario runs against. The section MUST NOT carry the private key the
provisioning service reaches hosts with, nor any relay token or key.

A VM target MAY name its capacity declaration through `resource_id`. The real
VM deal, purchase, qualification and reapply scenarios MUST use that identifier
for registration, listing adoption and capacity checks. Omitted, it MUST retain
`compute-e2e-real-001`. Each real VM purchase MUST refresh its site projections
before discovery, including with background lifecycle loops held, so host
diagnostics do not age out its source confirmation. Before a real purchase
approves payment, its region query MUST select its intended listing alone; an
empty, different or ambiguous result MUST refuse the purchase. Selecting a declaration MUST NOT bypass the site's
single-declaration-per-host invariant.

A bare-metal target MAY name its existing pool and capacity declaration through
`pool_id` and `resource_id`. When stated, the real deal, purchase, cleanup
qualification and reapply scenarios MUST reconcile those identifiers. Omitted,
they MUST retain their default scenario identifiers. Selecting an existing
declaration MUST NOT bypass refusal of another declaration for the same host or
physical machine.

#### Scenario: Qualification adopts a registered bare-metal declaration

- **WHEN** the target names the pool and resource already declared for its machine
- **THEN** registration reconciles that resource rather than creating another
  declaration, and reapply reports the selected resource
- **AND** a different declaration for the same host or physical machine is refused

#### Scenario: A field is misspelled

- **WHEN** the target section names a field the model does not define, or omits one it
  requires
- **THEN** the scenario fails before its first stage, naming the field

#### Scenario: A newer target reaches an older reader

- **WHEN** the section's version is one the scenario does not know
- **THEN** the scenario refuses it rather than interpreting it

#### Scenario: Relay access is requested under version 1

- **WHEN** a section states version 1, whatever access mode it names
- **THEN** it is refused with a message naming the version 2 profile and how its fields
  map

#### Scenario: A listing shape does not fit twice

- **WHEN** a VM host's listing shape exceeds half its capacity on any dimension
- **THEN** the target is refused, naming the dimension

#### Scenario: Relay access names a tenant address

- **WHEN** a host under relay access states a tenant address, or one under direct access
  names a relay
- **THEN** the target is refused, naming the field

A VM target MAY state its management SSH public key. A VM scenario registering a
host MUST state that pin when supplied. Otherwise it MUST preserve a pin already
stored for the host, and MUST refuse before declaring capacity, naming the field,
when the host holds none. A scenario MUST NOT capture a key the host presents.
A reapply MUST
restate the pin held at registration and verify that the management pins are
retained. A bare-metal scenario MUST state the target's management SSH public key
at registration.

#### Scenario: A VM target with no pin is refused

- **WHEN** a real VM scenario registers a host whose target states no management SSH
  public key and which holds no stored pin
- **THEN** the scenario refuses before declaring capacity, naming
  `ssh_host_public_key`, and captures nothing

#### Scenario: Provisioning registration is reapplied with an existing pin

- **WHEN** a real VM or bare-metal scenario reapplies its host registration
- **THEN** the registered management SSH keys match those from before the reapply
