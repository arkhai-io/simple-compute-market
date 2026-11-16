## ADDED Requirements

### Requirement: Relays are administered resources

A relay is a durable resource, not pool configuration. The provisioning service MUST record each relay's rendezvous address, rendezvous port, VM port allocation window, and admission token as one row, and resource pools MUST reference a relay rather than restating its address, window, or token.

A relay's rendezvous address and port taken together MUST be unique, so that one rendezvous cannot be recorded twice under different identities. Because a `tcp` proxy's remote port binds a listening socket on the relay itself, two pools referencing one relay draw from a single port namespace; recording the window on the relay is what prevents two pools from allocating within that namespace under different bounds.

A relay MUST be creatable, readable, and updatable through the provisioning API without redeploying the service, so that adding a rendezvous is an operator action against a running system.

#### Scenario: Two pools reference one relay

- **WHEN** two resource pools reference the same relay
- **THEN** both draw allocations from that relay's single recorded window, and neither pool can configure a different window for it

#### Scenario: A duplicate rendezvous is recorded

- **WHEN** a relay is created with an address and port already recorded by another relay
- **THEN** the request is rejected rather than creating a second identity for one rendezvous

#### Scenario: A relay moves to a new address

- **WHEN** a relay's recorded address is updated
- **THEN** every port lease held against that relay remains associated with it, rather than becoming unreferenced

#### Scenario: A relay is added after deployment

- **WHEN** an operator creates a relay through the API against a running service
- **THEN** a pool may reference it and allocate against it without the service being redeployed

### Requirement: Relay admission tokens are confidential at rest and on read paths

A relay's admission token MUST be encrypted at rest using the deployment's configured encryption key, so that the stored value is not a usable credential without a key held outside the database.

Configuration read paths MUST NOT return the token. This applies to every read surface, including pool and relay read endpoints, exported configuration documents, and the configuration comparison used to reconcile a definition document against stored state. A separate, explicitly named execution read path MAY return the decrypted token, and only fulfillment dispatch may use it.

A write that omits the token MUST preserve the stored value. Only an explicit token value replaces one, so that an update changing an unrelated field cannot destroy the credential.

#### Scenario: A relay is read through the API

- **WHEN** a relay or a pool referencing it is retrieved or exported
- **THEN** no admission token appears in the response, and the response indicates whether a token is configured

#### Scenario: A fulfillment job is dispatched

- **WHEN** the adapter builds job inputs for a VM creation against a relay-backed pool
- **THEN** the token is obtained through the execution read path and reaches the job, and is not obtained from a read path serving API responses

#### Scenario: An unrelated field is updated

- **WHEN** a relay or pool is updated with a request that omits the token
- **THEN** the stored token is unchanged

#### Scenario: Stored state is inspected directly

- **WHEN** a relay row is read from the database without the deployment's encryption key
- **THEN** the recorded token is ciphertext and cannot be used to admit a client

### Requirement: A relay binding is fixed for a VM's life

A VM's relay MUST be recorded on its port lease at allocation, and that record — not the pool's current configuration — MUST be the authority for which relay that VM uses. Teardown and reclamation MUST read the lease. Resolving the relay from pool configuration at teardown would target the wrong relay after any rebinding, releasing a port that was never bound there and leaving bound the one that was.

A pool's relay reference determines which relay a newly created VM receives. It MUST NOT change the relay of a VM that already exists.

A host's pool assignment, a pool's relay reference, and a relay's address or port MUST NOT change while any affected host holds an active lease, unless the relay is the same on both sides of the change. The buyer holds a rendezvous address and a port; both are delivered, and a remote port is not portable between relays, so a rebinding that moved existing VMs would strand every buyer on the affected hosts and request ports the new relay may already have leased.

Rebinding is therefore drain-then-change: disabling a pool already excludes it from new scheduling without invalidating active workloads, so an operator disables, waits for leases to clear, rebinds, and re-enables. A change on the relay's side — its address or port, or its token — drains the relay instead, since it affects every pool referencing it: the operator disables the relay, waits until it reports drained, makes the change, and re-enables it. A refusal under this rule MUST state the drain at the scope that clears it: the pool for a pool's relay reference or a host's pool, the relay for a relay's address, port, or token.

#### Scenario: A pool's relay reference is changed while VMs are running

- **WHEN** an operator changes a pool's relay reference and a host in that pool holds an active lease
- **THEN** the change is rejected, naming the host and the lease it holds

#### Scenario: A pool's relay reference is changed after draining

- **WHEN** the same change is made once no host in the pool holds an active lease
- **THEN** it is accepted, and subsequently created VMs are allocated on the new relay

#### Scenario: A host moves between pools sharing one relay

- **WHEN** a host is reassigned to a pool referencing the same relay as its current pool
- **THEN** the move is accepted regardless of active leases, because no delivered connection string changes

#### Scenario: A relay is repointed while it carries leases

- **WHEN** a relay's address or port is updated and it holds an active lease
- **THEN** the update is rejected, and the refusal tells the operator to disable the relay, wait until it reports drained, make the change, and re-enable it

#### Scenario: A pool's relay reference change is refused

- **WHEN** a change to a pool's relay reference is rejected because a host in the pool holds an active lease
- **THEN** the refusal tells the operator to disable the pool, wait for its leases to be released, make the change, and re-enable it

#### Scenario: A VM is torn down after its pool was rebound

- **WHEN** teardown runs for a VM whose pool now references a different relay
- **THEN** the relay recorded on the VM's lease is used, and the port is released against it

### Requirement: Relay admission tokens are resolved at execution

A relay's admission token MUST NOT be written into an accepted operation's persisted parameter snapshot, and MUST NOT appear in any job status or job list response. Job parameters are persisted unencrypted and are returned by the job endpoints, so a token placed among them is neither protected at rest nor withheld from a read.

An accepted operation MUST carry the relay reference and the leased remote port. The relay's address and admission token MUST be resolved immediately before the job's variables are written, so that a token rotated after acceptance takes effect on the next execution, including a retry of a job accepted before the rotation.

A relay that is absent, or holds no token at execution, MUST fail the job as a configuration error rather than a retryable one, because a retry against unchanged configuration fails identically. A disabled relay MUST NOT fail a job that holds a lease on it, whether the job adds the delivery's proxy or removes it: disabling a relay drains it, and a drain lets every leased delivery run to its end.

The rendered variables file holds the decrypted token and MUST have the same lifetime and access restrictions as other decrypted secret material on the execution path.

#### Scenario: A job's status is retrieved

- **WHEN** a job dispatched against a relay-backed pool is retrieved through the job endpoints
- **THEN** no admission token appears in the returned parameters

#### Scenario: Stored job parameters are inspected

- **WHEN** the persisted parameters of an accepted operation are read directly from the database
- **THEN** they carry the relay reference and remote port, and no token

#### Scenario: A token is rotated between acceptance and execution

- **WHEN** a relay's token is rotated after a job is accepted and before it executes
- **THEN** the job executes with the rotated token

#### Scenario: A relay becomes unusable between acceptance and execution

- **WHEN** the referenced relay is absent or holds no token when the job executes
- **THEN** the job fails as a configuration error and is not retried

#### Scenario: A relay is disabled between acceptance and execution

- **WHEN** the relay a job's lease names is disabled after the job is accepted and before it executes
- **THEN** the job executes, whether it creates the delivery or tears it down

### Requirement: Disabling a relay drains it

Disabling a relay MUST drain it: it stops new work on the relay and lets the work already holding a lease on it run to its end, for a VM guest and a bare-metal grant alike. While a relay is disabled, no host in a pool referencing it MAY be among the hosts taking new delivery that the compute composition reports to the site authority, so no claim is admitted against, placed on, or projected enabled for those hosts' declarations; and fulfillment preparation MUST refuse to lease a port on it. A create whose lease was allocated before the disable, and every teardown and reclaim of a delivery leased on the relay, MUST run. Once a relay is disabled, no lease is allocated on it, so the set of its active leases only shrinks.

Disabling MUST be reversible. Enabling the relay again MUST return its pools' hosts to new delivery and allow allocation on it, whether or not it has drained; disabling removes no proxy, releases no lease, and changes neither the token nor a grant key.

Removing the relay server is its operator's, outside this repository, once the relay has drained. Nothing in the provisioning service deletes a relay: a drained relay's row is kept, disabled, as the record its leases, retired keys, and pool references point at, and it keeps holding its rendezvous, so a server later reinstated at the same rendezvous is the same relay, enabled again.

#### Scenario: A relay is disabled while it carries deliveries

- **GIVEN** a relay holding active leases for a VM guest and a bare-metal grant
- **WHEN** an operator disables the relay
- **THEN** no new claim is admitted against or placed on a declaration of a host in a pool referencing it, those declarations are projected not enabled, and the guest's teardown and the grant's reclaim run when their leases end and release their ports

#### Scenario: A claim reaches fulfillment on a disabled relay

- **WHEN** fulfillment preparation runs for a pool whose relay is disabled
- **THEN** it refuses before leasing a port, naming the relay

#### Scenario: A relay disabled by mistake is enabled again before it drains

- **GIVEN** a disabled relay still holding active leases
- **WHEN** an operator enables it again
- **THEN** its pools' hosts take new delivery again, allocation on it resumes, and the deliveries it carried were never interrupted

#### Scenario: The definition document stops listing a drained relay

- **WHEN** a relay definition document that listed a relay is reconciled without it
- **THEN** the relay is left as it is, neither deleted nor changed

### Requirement: A relay reports whether it has drained

Every relay read the administrator receives MUST report the relay's number of active leases as `active_lease_count`, and whether it has drained as `drained`: true exactly when the relay is disabled and holds no active lease. An enabled relay MUST NOT be reported drained. Whether a released lease's grant has expired MUST NOT bear on it: a released lease has no proxy left to admit, and once the relay's server, or on a shared relay its keys, is removed, no grant it signed admits anything. The relay's operator relies on `drained` to know the relay may be removed.

#### Scenario: A disabled relay still carries a lease

- **WHEN** the administrator reads a disabled relay holding one active lease
- **THEN** the read reports `active_lease_count` 1 and `drained` false

#### Scenario: A disabled relay's last lease is released

- **WHEN** the administrator reads a disabled relay after its last active lease is released, while that lease's grant has not yet expired
- **THEN** the read reports `active_lease_count` 0 and `drained` true

#### Scenario: An enabled relay holds no lease

- **WHEN** the administrator reads an enabled relay holding no active lease
- **THEN** the read reports `drained` false

### Requirement: Relay port leases are unique per relay

The provisioning service MUST allocate a VM's relay port from the referenced relay's window before dispatch, record the allocation against that relay and the VM, and pass the port to the job as an input. The playbook MUST apply the port it is given and MUST NOT select one.

A port lease MUST be unique on the relay and the remote port. The host is recorded as an attribute of the lease and MUST NOT form part of its uniqueness, because the listening socket is bound on the relay rather than on the host, and two hosts sharing a relay share one port namespace.

A lease MUST be released when the owning settlement record reaches a terminal state, in the same transaction that records that state. Attaching release to individual lifecycle paths instead leaves whichever path was not enumerated leaking silently; attaching it outside the terminal transaction reintroduces the same leak on any crash between the two. A periodic reconciliation MUST release leases whose owning job or fulfillment has been terminal beyond a grace period, as a backstop for paths that bypass the transition rather than as the primary mechanism.

Allocation MUST be idempotent for one owner: allocating twice for the same fulfillment MUST return the lease already held rather than issuing a second port.

A pool whose referenced relay has no usable allocation window MUST be rejected before dispatch rather than producing a VM with no external route.

#### Scenario: Two hosts share a relay

- **WHEN** a port is leased for a VM on one host and a VM on a second host requests an allocation from the same relay
- **THEN** the second allocation selects a different port, rather than reissuing a port already bound on that relay

#### Scenario: A VM creation fails before teardown would run

- **WHEN** a VM's lifecycle reaches a terminal state without a teardown having run
- **THEN** its port lease is released

#### Scenario: A release path is missed

- **WHEN** a lease's owning job has been terminal beyond the grace period and the lease is still held
- **THEN** reconciliation releases it

#### Scenario: An accepted fulfillment allocates twice

- **WHEN** allocation runs a second time for a fulfillment that already holds an active lease
- **THEN** the existing lease is returned and no second port is issued

#### Scenario: Validation is requested

- **WHEN** a fulfillment request is validated rather than accepted
- **THEN** no port is leased and no durable state is written

#### Scenario: A relay is configured with no usable window

- **WHEN** a fulfillment is requested against a pool whose relay has no usable allocation window
- **THEN** the request is rejected before dispatch rather than creating a VM with no route

### Requirement: Relay definitions are imported from a mounted document

The provisioning service MAY be configured with a path to a relay definition document. When present, the service MUST import it, creating and updating the relays it names.

The document MUST NOT carry credentials. A relay entry MAY name which key of the deployment's secrets profile holds its admission token. That key MUST be read only when the relay is created, and MUST NOT be re-read on a later import, so that a token rotated through the API is never overwritten by a document that still names the key holding the old one.

An import MUST fail, naming the key, when an entry names a profile key the profile does not carry, rather than creating a relay with an empty token.

A relay MUST remain usable after the document that established it is removed or the path unset. Establishing a relay from a document and administering it through the API are the same relay, not two.

#### Scenario: A deployment starts with no operator action

- **WHEN** a deployment is applied carrying a relay definition document and a secrets profile holding the named token key
- **THEN** the named relay and the pools referencing it are usable without any API call by an operator

#### Scenario: A token is rotated and the document is later reconciled

- **WHEN** a relay's token is rotated through the API and the definition document is subsequently edited and reconciled
- **THEN** the rotated token is retained rather than reset to the value at the named profile key

#### Scenario: A named profile key is missing

- **WHEN** a definition document entry names a profile key the secrets profile does not carry
- **THEN** the import fails naming that key, and no relay is created with an empty token

#### Scenario: The document is unmounted

- **WHEN** the relay definition document is removed and the service restarts
- **THEN** relays established from it remain present and enabled, and pools referencing them continue to dispatch

## MODIFIED Requirements

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job; the resolved playbook is the pool's `playbook_path` when the pool states one, and otherwise the service's `vm_playbook_path` as configured when the job is prepared. Create metadata MUST retain the exact `host_id` and `executor_target` (the guest provisioning named), and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

Reservation-governed VM shape is resolved from the committed reservation dimensions carried by the scheduled settlement resource. Caller-supplied sizing fields do not override or fill missing committed dimensions. For each dimension absent from the committed reservation, the adapter MAY apply the corresponding pool default; if neither a committed dimension nor a pool default exists, the provider input remains unset and the selected playbook or inventory supplies its own default. The pool-selected registered requirement delegate owns conversion from canonical VM dimensions into the selected playbook's variable names, units, and derived values.

A VM fulfillment request MUST NOT say how its guest is reached, and the adapter MUST refuse one that carries a `connectivity` field or any other field the request does not declare. Which relay a host dials is a durable property of the deployment, recorded on the relay a pool references, and MUST NOT be selectable per request: a request-supplied relay would make a fleet-wide fact depend on a caller's configuration and would let two requests for one host disagree about how that host is reached. The buyer-facing address and port are returned in the fulfillment result rather than supplied with the request. The refusal happens while the request is prepared, inside the transaction that would accept it, so a refused request is never stored and nothing it carried, such as a relay credential, is kept at rest.

#### Scenario: A request supplies relay configuration

- **WHEN** a fulfillment request's payload carries a `connectivity` field, such as a relay address, domain, or dashboard credential
- **THEN** validation reports the request invalid, `begin_fulfillment` refuses it, and no fulfillment is accepted, no job is dispatched, and the request is not stored

#### Scenario: Pool configuration changes after create dispatch

- **WHEN** an operator edits provider configuration after an Ansible create job is accepted
- **THEN** the accepted job retains the resolved configuration snapshot captured at dispatch

#### Scenario: Provider variables collide with job identity

- **WHEN** pool-supplied extra variables attempt to override an authoritative host, target, action, sizing, or executor field
- **THEN** validation rejects the operation before asynchronous dispatch

#### Scenario: VM teardown is dispatched

- **WHEN** teardown begins for an accepted VM fulfillment
- **THEN** the adapter targets the recorded `host_id` and `executor_target` from fulfillment metadata

#### Scenario: A committed dimension is present

- **WHEN** the scheduled settlement resource carries a committed VM dimension
- **THEN** the adapter translates that value through the pool-selected requirement delegate and ignores any conflicting caller-supplied sizing field

#### Scenario: A committed dimension is absent and the pool has a default

- **WHEN** the committed reservation omits a VM dimension and the resolved pool configures the corresponding default
- **THEN** the adapter uses the pool default for that dimension

#### Scenario: A committed dimension and pool default are both absent

- **WHEN** neither the committed reservation nor the resolved pool supplies a VM dimension
- **THEN** the adapter leaves the corresponding provider input unset so the selected playbook or inventory may supply its own default

#### Scenario: A VM pool states no playbook

- **WHEN** a VM job is prepared for a pool whose provider configuration states no `playbook_path`
- **THEN** the job's stored parameters carry the service's `vm_playbook_path` as configured at preparation
