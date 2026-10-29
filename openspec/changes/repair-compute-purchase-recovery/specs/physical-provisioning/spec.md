## ADDED Requirements

### Requirement: A bare-metal reclaim tolerates an account its grant never created

A bare-metal reclaim MUST succeed, reporting the tenant account absent, when the tenant
account it names does not exist on the host, whatever its reclaim policy, and MUST NOT
create the account. Where the account exists it MUST remove the lease's key, or lock or
delete the account, as its policy says.

#### Scenario: A grant failed before creating its account

- **WHEN** a compensating teardown reclaims access for a grant whose tenant account was never created
- **THEN** the reclaim succeeds reporting the account absent, and no account is created

#### Scenario: A grant created its account and installed its key

- **WHEN** a reclaim under the default policy runs for an account holding the lease's key
- **THEN** that key is removed and the account is otherwise unchanged

### Requirement: A bare-metal reclaim's printed fact is a diagnostic

A bare-metal reclaim's fact MUST be read through the compute family's fact reader
for the reclaim's action, and checked against the job as a grant's is: its action,
execution host, tenant account, the physical machine when the job names one, and
success. A fact that matches MUST be the reclaim's result unchanged. A fact that
does not match MUST NOT be recorded as the result; the result MUST name only the
mismatch. With no fact read, the reclaim carries no result.

The result is diagnostic. Whether the teardown succeeded or failed MUST be decided
by the reclaim job's status alone, as for any teardown, and the reclaim's result
MUST NOT add an evidence or linkage condition to the teardown or to the release
that follows it.

#### Scenario: A reclaim's fact matches its job

- **WHEN** a reclaim succeeds and its printed fact names the job's action, host,
  tenant account, and machine, and reports success
- **THEN** the reclaim's result is that fact

#### Scenario: A reclaim's fact names another tenant

- **WHEN** a reclaim job succeeds and its printed fact names a tenant account
  other than the job's
- **THEN** the reclaim's result names only the mismatch, and the teardown is
  judged by the job's success as any teardown is

#### Scenario: A reclaim prints no fact

- **WHEN** a reclaim job's output carries no fact for the reclaim's action
- **THEN** the job carries no result, and the teardown is judged by the job's status

### Requirement: A VM teardown removes only what its guest created

A VM teardown MUST remove only artifacts attributable to its own guest: its libvirt
domain and that domain's storage and firmware variables, its cloud-init image, its relay
proxy, its DHCP reservation, and the firewall and NAT rules created for it. Every rule a
VM create adds for a guest MUST carry a marker naming that guest, and teardown MUST
remove rules by that exact marker; a rule created without the marker MUST be matched by
the guest's exact address, never by a prefix of it. A rule shared by every guest MUST NOT
be removed by one guest's teardown.

A teardown that finds no cleanup record for its guest MUST NOT treat the guest as absent
on that ground: it MUST look for each artifact attributable to the guest by name, remove
each one it finds, and report the guest absent only when it finds none. An artifact it
cannot attribute to the guest MUST fail the teardown, naming the artifact, so the
fulfillment's teardown fails visibly and its capacity stays held.

#### Scenario: Two guests' addresses share a prefix

- **GIVEN** two guests on one host whose addresses are `192.0.2.1` and `192.0.2.12`
- **WHEN** the first guest is torn down
- **THEN** only its rules are removed, and the second guest's rules remain

#### Scenario: A create failed before writing its cleanup record

- **WHEN** a VM teardown runs for a guest whose create left a domain and disk image but no cleanup record
- **THEN** the domain and its storage are removed by the guest's name, and the teardown succeeds

#### Scenario: Nothing of the guest remains

- **WHEN** a VM teardown runs for a guest with no cleanup record and no domain, image, proxy, reservation, or marked rule on the host
- **THEN** it succeeds, reporting the guest absent

#### Scenario: An artifact cannot be attributed

- **WHEN** a VM teardown with no cleanup record finds a rule it cannot attribute to the guest
- **THEN** the teardown fails naming that rule, and the reservation's capacity stays held

### Requirement: A VM guest is created from a pinned, verified image

A VM create from scratch MUST use one dated release of its cloud image, named by that
release's URL and the SHA-256 its published checksum list gives, never a moving latest
path. It MUST verify the image's SHA-256 before the image backs any disk, whether it
downloaded the image or found it already on the host, and an image that fails
verification MUST fail the create before any disk or domain is defined, without being
used. Only an `x86_64` image is pinned: a create whose target host reports another
machine architecture MUST fail, naming it, before any host effect.

#### Scenario: A create downloads its pinned image

- **WHEN** a VM create from scratch runs on an `x86_64` host that holds no copy of the pinned image
- **THEN** it downloads the pinned release, verifies its SHA-256, and only then creates the guest's disk from it

#### Scenario: A downloaded image does not match its checksum

- **WHEN** the image a create downloads does not match its pinned checksum
- **THEN** the create fails before defining a disk or a domain, and the image is not used

#### Scenario: An image already on the host does not match its checksum

- **WHEN** a create finds a file at the pinned image's path whose SHA-256 is not the pinned one
- **THEN** the create fails before defining a disk or a domain, and the file is not used

#### Scenario: The host is not x86-64

- **WHEN** a VM create from scratch targets a host whose machine architecture is not `x86_64`
- **THEN** the create fails naming the architecture, before any host effect

### Requirement: A host's boot GPU is passed through only by an operator's opt-in

A VM create selecting one GPU for passthrough MUST decide whether a candidate is the
host's boot GPU, the device the host's console runs on, from that candidate's own
kernel boot flag, and MUST NOT select the boot GPU unless the pool's operator-owned
provider configuration sets `vm_passthrough_boot_gpu` true. No job parameter, buyer
term, or storefront request MUST be able to set it. With it set, the boot GPU MUST be
eligible only when, at the moment of selection, the host's GPU capability inventory
lists it as available for passthrough, the kernel reports it bound to the passthrough
driver, and no defined guest has it attached; the inventory alone MUST NOT make it
eligible. The create MUST NOT bind or unbind a device. Every part of the create that
excludes or refuses the boot GPU MUST use the same test and the same setting, and a
create left with no eligible GPU MUST fail before defining a domain.

#### Scenario: A host's only GPU is its boot GPU and the pool does not opt in

- **WHEN** a GPU VM create runs on a host whose only GPU is its boot GPU, in a pool that does not set `vm_passthrough_boot_gpu`, whatever the capability inventory lists
- **THEN** no GPU is selected, and the create fails before defining a domain

#### Scenario: The boot GPU is listed first in the host's device listing

- **WHEN** the host's device listing prints each device's slot before its class, and the boot GPU is among the inventory's available devices, in a pool that does not opt in
- **THEN** the boot GPU is still recognized by its own boot flag and is not selected

#### Scenario: The pool opts in and the boot GPU is prepared

- **WHEN** the pool sets `vm_passthrough_boot_gpu` true, the inventory lists the boot GPU as available, the kernel reports it bound to the passthrough driver, and no guest has it attached
- **THEN** the create selects the boot GPU and passes it through

#### Scenario: The inventory is stale

- **WHEN** the pool sets `vm_passthrough_boot_gpu` true and the inventory lists the boot GPU as available, but the kernel reports it bound to its host driver, or to no driver
- **THEN** the boot GPU is not selected, and a create with no other eligible GPU fails before defining a domain

#### Scenario: The pool opts in but another guest holds the boot GPU

- **WHEN** the pool sets `vm_passthrough_boot_gpu` true, but a defined guest has the boot GPU attached
- **THEN** the boot GPU is not selected

### Requirement: A GPU guest's readiness wait and autostart are set by its pool's operator

A GPU VM create MUST wait for its guest to confirm setup for at most
`vm_setup_wait_attempts` attempts, `vm_setup_wait_interval_seconds` apart, defaulting
to 10 and 30, and MUST fail, naming that bound, when the wait runs out; it MUST NOT
report a guest ready that has not confirmed its setup. Each setting MUST be a positive
integer, and a value that is not MUST fail the create before any host effect. A
created guest MUST be set to start on host boot unless `vm_autostart` is false; absent,
it is true. These settings MUST come only from the pool's operator-owned provider
configuration, never from a job parameter, a buyer term, or a storefront request, and
none of them changes what teardown removes.

#### Scenario: A pool states no readiness or autostart setting

- **WHEN** a GPU VM create runs in a pool whose provider configuration sets none of these
- **THEN** it waits at most ten attempts thirty seconds apart, and sets the guest to start on host boot, as before

#### Scenario: A pool extends the readiness wait

- **WHEN** the pool sets `vm_setup_wait_attempts` to 40 and `vm_setup_wait_interval_seconds` to 15
- **THEN** the create waits at most forty attempts fifteen seconds apart, and fails naming that bound if setup is not confirmed within it

#### Scenario: A setting is not a positive integer

- **WHEN** the pool sets `vm_setup_wait_attempts` to `0`, a negative number, or text
- **THEN** the create fails naming the setting, before any host effect

#### Scenario: A pool turns autostart off

- **WHEN** the pool sets `vm_autostart` to false
- **THEN** the created guest is not set to start on host boot, and its teardown removes the same artifacts as any guest's

## MODIFIED Requirements

### Requirement: A create succeeds only with readable delivery evidence

A codec MUST report a create job's result as the compute family's create result: the
delivery evidence (the endpoints to connect to and when access became ready), or none
when the output cannot say, and a detail mapping of non-secret operator data.

A result fact printed by a compute role MUST be read through the compute family's one
fact reader, whatever display format the Ansible callback uses: the fact printed by a
`debug: var:` task in JSON form, or else a JSON document printed by a `debug: msg:`
literal block whose `action` is the action the job's domain expects. The reader MUST
read each literal block alone, as the indented lines following its `msg:` key, and MUST
NOT read past the block's end into later output. A block that is not a JSON object, a
document with no `action`, and a document naming another action MUST be ignored and
MUST NOT be taken as the job's fact. When several documents name the expected action,
the last is the fact. When none does, the fact MUST be absent, and the job's result
carries no evidence. The reader MUST NOT log a block's content.

A codec MUST yield evidence only from a fact that names the job's action, that matches
the target, host, tenant account, and physical machine its domain's job parameters name
and its role prints, and that reports success. A fact that matches anything else MUST
yield no evidence, with a detail naming what did not match. A create job reported
succeeded MUST NOT make its fulfillment active unless its evidence is valid; otherwise
the fulfillment MUST fail. The family MUST NOT read or deliver the detail.

#### Scenario: A create job's evidence is unreadable

- **WHEN** a create job succeeds but its result carries no valid delivery evidence
- **THEN** its fulfillment fails, and its capacity is held as for any failed create

#### Scenario: A relay-backed VM is delivered

- **WHEN** a VM is created behind a relay
- **THEN** its delivery's endpoint is the relay's address and leased port, not its host's

#### Scenario: A grant's output is printed in the YAML callback format

- **WHEN** a bare-metal grant succeeds and its output prints the access fact in the
  callback's YAML format, with the same fact as JSON in a `debug: msg:` block
- **THEN** the job's result carries the delivery evidence, and its fulfillment becomes
  active

#### Scenario: Output names another job's host or tenant

- **WHEN** a grant's printed fact names a host or tenant account other than the job's
- **THEN** the result carries no evidence and its fulfillment fails, its detail naming
  the mismatch

#### Scenario: Output carries only another action's document

- **WHEN** a grant's output carries a `debug: msg:` document naming another action and
  no fact for the grant
- **THEN** no fact is read, and its fulfillment fails for lack of evidence

#### Scenario: A non-JSON block precedes another task's JSON

- **WHEN** a grant's output carries the play's human-readable summary block, or an
  unreadable block, followed by a later task's JSON document
- **THEN** the unreadable block is ignored without adopting the later document, and
  only a document naming the grant's action can be its fact

#### Scenario: A VM create's fact names another guest

- **WHEN** a VM create's printed fact names a guest other than the job's target
- **THEN** the result carries no evidence and its fulfillment fails, its detail naming
  the mismatch

### Requirement: The tenant-facing host address falls back to the connection address

Where an execution path derives a tenant-facing address for a host, it SHALL use
that host record's configured tenant-facing address when one is set, and otherwise
the record's connection address; and it SHALL use the record's configured
tenant-facing port when one is set, and otherwise the record's connection port. A
tenant-facing port SHALL be a port number between 1 and 65535. It SHALL NOT read
either from a configured inventory file. A bare-metal grant's delivery endpoint is
its host's tenant-facing address and port with the tenant account its job created.

#### Scenario: A host has no tenant-facing address

- **GIVEN** a registered host record with a connection address and no
  tenant-facing address
- **WHEN** a tenant's connection details are produced for that host
- **THEN** they carry the connection address

#### Scenario: A host is reached by tenants on another route

- **GIVEN** a registered host whose connection reaches it through a tunnel on one
  address and port, and whose record names a tenant-facing address and port
- **WHEN** a bare-metal grant on that host succeeds
- **THEN** the delivery's endpoint is the tenant-facing address and port, and not the
  tunnel's

#### Scenario: A host names a tenant-facing address and no tenant-facing port

- **WHEN** a tenant's connection details are produced for a host whose record names a
  tenant-facing address and no tenant-facing port
- **THEN** they carry the tenant-facing address and the connection port

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so that a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so that a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

The registry MAY also record a tenant-facing port, `public_port`, for a host. The port belongs to version 2 of the `ssh` connection, which is version 1 with that one optional field, and version 2 is the only version of the kind the registry serves: every `ssh` connection is submitted and stored at version 2, whether it states a tenant-facing port, states none, or states it as null. A rendered inventory MUST emit `public_port` for a host whose record states one, and MUST NOT emit it for a host whose record states none. A host whose record states no tenant-facing port MUST be stored with no `public_port` field, not even a null one. A `public_port` supplied through the INI input format MUST be preserved, and a value that is not a port number between 1 and 65535 MUST cause its entry to be rejected, as for `ansible_port`. A connection built from the INI format or the typed connection factory MUST be submitted at version 2.

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
- **THEN** the submission is refused naming version 2, the version served, and nothing is stored

### Requirement: Host connections are typed by their implementation's codec

A host's connection MUST be held as a connection envelope (a kind, a version, public
fields, and protected values) whose kind names the codec of the implementation
distribution that supports it. Compute provisioning MUST NOT define per-kind connection
fields; it validates an envelope through its codec. An executor MUST receive an immutable
execution-host value, not the persistence record, and MUST refuse a connection kind it
does not support.

A deployment MUST register one codec per kind, and each codec serves one version;
composition MUST refuse two codecs for one kind. A connection MUST be built by the codec
of its own kind, at the version that codec serves. A connection at a kind no codec
serves, or at another version than its kind's codec serves, MUST be refused naming the
kinds or the version that is served. A reader of a stored connection MUST check its kind
and version before reading its fields, and MUST refuse a version it does not serve
rather than read it as another, so a host stored at a version no longer served runs no
work until it is submitted again at the served version. Such a submission MUST carry
forward a protected value it still needs and does not resubmit, whatever the previous
connection's version, as opaque material it neither reads nor decrypts. A stored connection MUST NOT
be rewritten to another version except by a submission that states that version, and
nothing upgrades a stored connection on its own.

#### Scenario: A compute domain needs another connection kind

- **WHEN** a domain's executor reaches its targets by a means other than SSH
- **THEN** an implementation distribution adds a codec for that kind, and neither the host
  authority's model nor the executor contract changes

#### Scenario: A connection states a version no codec serves

- **WHEN** a host is submitted with an `ssh` connection at a version other than the one the
  registered `ssh` codec serves
- **THEN** the submission is refused naming the version served, and nothing is stored

#### Scenario: A stored connection is at an unsupported version

- **WHEN** an execution path reads a stored connection whose version its codec does not
  serve, such as a host stored at `ssh` version 1
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

### Requirement: An undelivered lease is released by what its fulfillment proves

A lease's release MUST follow the state of its reservation's fulfillment aggregate. Deciding
a release MUST NOT write: the reservation MUST be recorded `releasing`, with the fulfillment
as its release handle, before teardown is begun, so that a restart between the two resumes
the release from `releasing`, and a failure to begin teardown leaves it for the lease
lifecycle's next cycle. The grace period after which a stalled teardown is marked failed
MUST run from when the reservation entered `releasing`, not from the lease's end. When the
site refuses one of the lifecycle's writes because the reservation changed since it was
read, the lifecycle MUST re-read the reservation and leave it in the state another actor
recorded; in particular, it MUST NOT begin teardown after a refused move to `releasing`.

- An `active` aggregate MUST be torn down before capacity returns.
- An aggregate whose teardown has already begun — `teardown_dispatch_pending`, `tearing_down`, or `teardown_failed` — MUST have that teardown adopted, not a second one begun.
- A `torn_down` aggregate MUST return the capacity as a completed release.
- An absent, `assigned`, or `abandoned` aggregate MUST return the capacity directly, as a completed release, only when the reservation's provenance proves nothing was dispatched: no create handle on the reservation and no job bound to the reservation. An `assigned` aggregate MUST be abandoned only by a compare-and-set taken after the proof is checked, so a concurrent dispatch cannot outrun it and a refused release writes nothing.
- When the create is in flight (`dispatch_pending` or `dispatching`), the release MUST be remembered durably, with the reservation `releasing` and the fulfillment as its release handle, and teardown MUST begin once the aggregate reaches `active`, or once it reaches a compensable `failed`; the grace timeout MUST NOT run while the create is in flight.
- A `failed` aggregate is compensable when the provider reported its dispatched create failed (`provider_reported_failure`) and its durable provider metadata is the job-backed provider's, naming its create operation, job, host, and target. One compute-owned predicate MUST decide this, and the release decision, the release status, and the begin of teardown MUST all use it. A compensable aggregate MUST have its domain's ordinary teardown begun as a compensating teardown, the same way for every offering mode, and capacity returns only once the aggregate reaches `torn_down`. The begin MUST re-judge eligibility from the aggregate's state at that moment, not from an earlier decision.
- A compensating teardown records the failure reason `create_compensation`. A `torn_down` aggregate carrying that reason ended compensated; a `torn_down` aggregate carrying any other reason, or none, was delivered and torn down. A teardown failure of a compensating teardown MUST keep that reason and replace only the failure message, which therefore holds the latest diagnostic. The create job itself stays durable, with its status, result, and log; the fulfillment's earlier diagnostic is not kept verbatim, and the job's error MAY be empty, as for a create that succeeded without usable delivery evidence.
- When a compensable aggregate's provider cannot prepare its teardown, because its create job is missing or names another resource, beginning the teardown MUST be refused writing nothing, and the lease MUST enter `release_failed` with the reason `compensation_refused`, its capacity held. The failure MUST be recorded under the release handle the lifecycle recorded when it entered `releasing`, so that a refusal observed for one release cannot land on another. Any other failure to begin is transient: the lease stays `releasing`, and the lifecycle's next cycle retries it.
- Any other `failed` aggregate — quarantined, failed for metadata that cannot name its output, or carrying no or unreadable provider metadata — or an absent, `assigned`, or `abandoned` one without the provenance proof, MUST put the lease in `release_failed` for an operator to verify and force-release. An operator's retry-release of such a lease whose aggregate has since become compensable MUST begin the compensating teardown.
- Only a release of the lease — termination, expiry, or an operator's retry-release — begins a compensating teardown. A lease already `released` or `force_released` MUST NOT be revisited.
- A teardown observed as `teardown_failed` while the lease is `releasing` MUST put the lease in `release_failed`; an operator's retry-release MUST re-observe the same aggregate.

The compute provisioning composition MUST supply the site authority's release guard, which permits freeing a reservation's capacity only for a `torn_down` aggregate or for an absent, `assigned`, or `abandoned` one whose provenance proof holds, and MUST check that proof in the transaction that frees the capacity. Every direct capacity return, whether by the lease lifecycle or by any caller of the site's release, MUST pass that guard; force-release remains the operator's recorded override.

#### Scenario: A committed lease whose fulfillment never began expires

- **WHEN** a lease's reservation was committed but its fulfillment was never dispatched, and the lease reaches its end
- **THEN** the assigned aggregate is abandoned, the capacity returns, and no teardown is attempted

#### Scenario: A lease is terminated while its create is in flight

- **WHEN** a lease is terminated while its fulfillment is `dispatching`
- **THEN** the reservation becomes `releasing` at once, survives a restart in that state, and its teardown begins when the aggregate reaches `active`

#### Scenario: A create failed

- **WHEN** a lease is released and its aggregate is `failed` after its provider reported the dispatched create failed, with provider metadata naming its create job
- **THEN** the lease becomes `releasing` with the fulfillment as its handle, the domain's teardown is begun as a compensating teardown recording `create_compensation`, and capacity returns only when the aggregate reaches `torn_down`

#### Scenario: A create in flight at termination then fails

- **GIVEN** a lease terminated while its fulfillment was `dispatching`, so its reservation is `releasing`
- **WHEN** the provider reports the create failed, leaving a compensable `failed` aggregate
- **THEN** the release status reports it ready for teardown, the lifecycle's next cycle begins the compensating teardown, and capacity returns only when the aggregate reaches `torn_down`

#### Scenario: A failed create cannot be compensated

- **WHEN** a lease is released and its aggregate is `failed` with no provider metadata, as a quarantined row, or for metadata that cannot name its output
- **THEN** the lease enters `release_failed`, no teardown is begun, and capacity stays held until an operator force-releases it

#### Scenario: A compensating teardown cannot be prepared

- **WHEN** a lease is released and its compensable aggregate's provider cannot prepare the teardown because the create job it names is missing
- **THEN** nothing is written to the aggregate, the lease enters `release_failed` with the reason `compensation_refused`, and capacity stays held

#### Scenario: A compensating teardown fails

- **WHEN** a compensating teardown reaches `teardown_failed`
- **THEN** the aggregate keeps the reason `create_compensation` with the teardown's diagnostic as its message, and the lease enters `release_failed` with capacity held, as for an active fulfillment's failed teardown

#### Scenario: A delivered fulfillment's teardown fails once and then succeeds

- **WHEN** an `active` fulfillment's teardown reaches `teardown_failed` and a later attempt reaches `torn_down`
- **THEN** the aggregate does not carry `create_compensation` and is not read as compensated

#### Scenario: Teardown fails while the lease is releasing

- **WHEN** a releasing lease's aggregate reaches `teardown_failed`
- **THEN** the lease enters `release_failed`, and when convergence's retry later reaches `torn_down`, an operator's retry-release adopts that teardown and releases the capacity

#### Scenario: A storefront releases a delivered lease

- **WHEN** a storefront asks the site to release a reservation whose aggregate is `active`
- **THEN** the release guard refuses, the reservation keeps its capacity and state, and the lease is released only through its lifecycle

### Requirement: Relay port leases are unique per relay

The provisioning service MUST allocate a VM's relay port from the referenced relay's window before dispatch, record the allocation against that relay and the VM, and pass the port to the job as an input. The playbook MUST apply the port it is given and MUST NOT select one.

Fulfillment preparation MUST allocate through the acceptance transaction's
session. The port lease, accepted fulfillment, and prepared operation MUST commit
or roll back together. It MUST NOT allocate through an independent write
transaction while acceptance is open. Standalone allocation remains available to
callers that own no acceptance transaction.

A port lease MUST be unique on the relay and the remote port. The host is recorded as an attribute of the lease and MUST NOT form part of its uniqueness, because the listening socket is bound on the relay rather than on the host, and two hosts sharing a relay share one port namespace.

Only released lease rows may be reused. A stale free-port observation MUST NOT
reassign an active lease; allocation MUST retry a conflicting claim without
rolling back other writes in the caller's transaction.

A lease MUST be released with its reservation's capacity, in the transaction that releases it, whatever path releases it, and MUST NOT be released on a fulfillment state alone. A failed creation may leave a guest running with its tunnel bound, so its port is held with its capacity: until a compensating teardown reaches `torn_down` and the capacity is released, or until an operator verifies the host and forces the release. A periodic reconciliation MUST release leases whose reservation has been released beyond a grace period, as a backstop rather than as the primary mechanism.

Allocation MUST be idempotent for one owner: allocating twice for the same fulfillment MUST return the lease already held rather than issuing a second port.

A pool whose referenced relay has no usable allocation window MUST be rejected before dispatch rather than producing a VM with no external route.

#### Scenario: Two hosts share a relay

- **WHEN** a port is leased for a VM on one host and a VM on a second host requests an allocation from the same relay
- **THEN** the second allocation selects a different port, rather than reissuing a port already bound on that relay

#### Scenario: A VM creation fails before teardown would run

- **WHEN** a VM's fulfillment fails, including after its provider reported the create succeeded
- **THEN** its port lease is held with its capacity, and is released only in the transaction that releases that capacity, after a compensating teardown or an operator's forced release

#### Scenario: A release path is missed

- **WHEN** a lease's reservation has been released beyond the grace period and the lease is still held
- **THEN** reconciliation releases it

#### Scenario: An accepted fulfillment allocates twice

- **WHEN** allocation runs a second time for a fulfillment that already holds an active lease
- **THEN** the existing lease is returned and no second port is issued

#### Scenario: Validation is requested

- **WHEN** a fulfillment request is validated rather than accepted
- **THEN** no port is leased and no durable state is written

#### Scenario: Preparation rejects after leasing a port

- **WHEN** fulfillment preparation leases a relay port and a later check rejects the request
- **THEN** no port lease, accepted fulfillment, or prepared operation is committed
- **AND** a corrected request may be accepted without an orphaned port

#### Scenario: A stale scan names an occupied port

- **WHEN** allocation attempts to claim a port another owner already holds
- **THEN** that owner's lease remains intact and allocation selects another free port
- **AND** the caller's other pending writes remain committable

#### Scenario: A relay is configured with no usable window

- **WHEN** a fulfillment is requested against a pool whose relay has no usable allocation window
- **THEN** the request is rejected before dispatch rather than creating a VM with no route

### Requirement: What is held for a reservation is returned with its capacity

A domain resource held for a reservation's lifetime, such as a relay port, MUST be
returned in the transaction that releases the reservation's capacity, whether the
release guard permits it or an operator forces it, and never on a fulfillment state
alone. The provisioning service MUST NOT name the resource, and a failing return MUST
abort the release.

#### Scenario: A failed fulfillment holds its port

- **WHEN** a VM's fulfillment fails and the release guard refuses its capacity
- **THEN** its relay port stays held until the capacity is released, after a compensating teardown reaches `torn_down` or an operator forces the release, which returns both

#### Scenario: An abandoned hold returns a port leased before dispatch

- **WHEN** the release guard abandons an `assigned` aggregate whose create was prepared and leased a relay port
- **THEN** the port is returned in the ledger's transaction, not left to reconciliation
