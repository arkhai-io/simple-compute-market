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

### Requirement: Relay port leases are unique per relay

The provisioning service MUST allocate a VM's relay port from the referenced relay's window before dispatch, record the allocation against that relay and the VM, and pass the port to the job as an input. The playbook MUST apply the port it is given and MUST NOT select one.

A port lease MUST be unique on the relay and the remote port. The host is recorded as an attribute of the lease and MUST NOT form part of its uniqueness, because the listening socket is bound on the relay rather than on the host, and two hosts sharing a relay share one port namespace.

A lease MUST be released on every terminal outcome of the VM's lifecycle, not only on teardown. A periodic reconciliation MUST release leases whose owning job or fulfillment has been terminal beyond a grace period.

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

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job. Create metadata MUST retain the exact `vm_host` and `vm_target`, and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

Reservation-governed VM shape is resolved from the committed reservation dimensions carried by the scheduled settlement resource. Caller-supplied sizing fields do not override or fill missing committed dimensions. For each dimension absent from the committed reservation, the adapter MAY apply the corresponding pool default; if neither a committed dimension nor a pool default exists, the provider input remains unset and the selected playbook or inventory supplies its own default. The pool-selected registered requirement delegate owns conversion from canonical VM dimensions into the selected playbook's variable names, units, and derived values.

The fulfillment request's `connectivity` field MUST NOT carry relay configuration. Which relay a host dials is a durable property of the deployment, recorded on the relay a pool references, and MUST NOT be selectable per request. The buyer-facing address and port are returned in the fulfillment result rather than supplied with the request. Any remaining `connectivity` content is opaque metadata the adapter forwards to the Ansible job unchanged and never interprets, and is not a sizing or feasibility requirement.

#### Scenario: Pool configuration changes after create dispatch

- **WHEN** an operator edits provider configuration after an Ansible create job is accepted
- **THEN** the accepted job retains the resolved configuration snapshot captured at dispatch

#### Scenario: Provider variables collide with job identity

- **WHEN** pool-supplied extra variables attempt to override an authoritative host, target, action, sizing, or executor field
- **THEN** validation rejects the operation before asynchronous dispatch

#### Scenario: VM teardown is dispatched

- **WHEN** teardown begins for an accepted VM fulfillment
- **THEN** the adapter targets the recorded `vm_host` and `vm_target` from fulfillment metadata

#### Scenario: A committed dimension is present

- **WHEN** the scheduled settlement resource carries a committed VM dimension
- **THEN** the adapter translates that value through the pool-selected requirement delegate and ignores any conflicting caller-supplied sizing field

#### Scenario: A committed dimension is absent and the pool has a default

- **WHEN** the committed reservation omits a VM dimension and the resolved pool configures the corresponding default
- **THEN** the adapter uses the pool default for that dimension

#### Scenario: A committed dimension and pool default are both absent

- **WHEN** neither the committed reservation nor the resolved pool supplies a VM dimension
- **THEN** the adapter leaves the corresponding provider input unset so the selected playbook or inventory may supply its own default

#### Scenario: A request supplies relay configuration

- **WHEN** a fulfillment request's `connectivity` field carries a relay address, domain, or dashboard credential
- **THEN** the value does not select a relay, and the relay referenced by the pool is used instead
