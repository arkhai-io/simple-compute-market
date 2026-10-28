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

### Requirement: A VM guest matches its host's architecture

A VM create MUST select its guest image, machine type, and firmware for the target
host's architecture: an `aarch64` host MUST receive an `aarch64` cloud image booted under
UEFI on the `virt` machine type, and an `x86_64` host an `amd64` image as before. Each
image MUST be pinned to a dated release and verified against its published checksum
before use; an image that fails verification MUST fail the create before a domain is
defined. A create for an architecture no pinned image serves MUST fail before any host
effect.

#### Scenario: A CPU-only VM is created on an aarch64 host

- **WHEN** a VM create without GPUs runs on an `aarch64` host
- **THEN** the guest is defined from the pinned `aarch64` image on the `virt` machine with UEFI firmware, and no GPU passthrough is configured

#### Scenario: A downloaded image does not match its checksum

- **WHEN** the image a create downloads does not match its pinned checksum
- **THEN** the create fails before defining a domain, and the image is not used

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
