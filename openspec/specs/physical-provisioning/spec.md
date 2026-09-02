# Physical Provisioning Specification

## Purpose

Define the implemented allocation-backed executor dispatch, asynchronous job, and lease release behavior in the compute provisioning service.

## Requirements

### Requirement: Service calls use the shared version 2 identity contract

A provisioning authority MUST authenticate each inbound service request with
the shared `arkhai.market-request-signature.v2` contract and MUST sign each
mutation response with the shared response contract. Verification MUST use the
complete counterparty principal selected by route and authority state, bind the
canonical request or response body, enforce bounded freshness, classify replay
durably, and run locally without a chain or external identity call. Only the
version 2 request and response contracts authenticate the service boundary;
shared credentials, caller-selected expected identities, and unsigned mutation
responses MUST NOT do so.

The authority MUST durably reserve `(principal, request_id)` with the canonical
request digest before dispatch. An exact completed retry MUST return the
recorded status and body under a freshly signed response without repeating the
operation. One caller MAY reclaim an exact unfinished request after its
dispatch lease expires; an in-progress exact retry or reuse with changed signed
content MUST NOT dispatch a second operation.

#### Scenario: An inbound request is authenticated

- **WHEN** a storefront calls a provisioning authority with a correctly signed
  version 2 request
- **THEN** the authority verifies its role, exact registered principal, method,
  semantic operation and resource, request identity, timestamp, and body before
  dispatch

#### Scenario: Request content is changed

- **WHEN** any bound request field or body content is changed after signing
- **THEN** verification fails before the authority performs the operation

#### Scenario: A mutation response is returned

- **WHEN** the authority acknowledges a state-changing request
- **THEN** it signs the status, request identity, authority principal,
  timestamp, and canonical response body, and the caller verifies that exact
  authority before accepting the acknowledgement

#### Scenario: An exact completed request is retried

- **WHEN** a caller repeats the same canonical request with the same principal
  and request identity after losing the acknowledgement
- **THEN** the authority returns the recorded outcome under a fresh signed
  response without dispatching the operation again

#### Scenario: An unfinished request is retried

- **WHEN** an exact retry arrives while the original dispatch lease remains
  active
- **THEN** the authority rejects it as still in progress without dispatching a
  second operation

#### Scenario: A request identity is replayed

- **WHEN** a previously reserved request identity is reused with changed
  content, operation, role, or principal
- **THEN** the authority rejects it as a replay conflict rather than dispatching
  the operation

#### Scenario: Verification runs without external dependencies

- **WHEN** an Ed25519 or EIP-191 signature is verified
- **THEN** verification completes locally without a chain node, RPC endpoint,
  or external identity service

### Requirement: Provisioning role principals are exact and durably registered

The provisioning authority MUST resolve the active complete scheme-tagged
principal set for each required `seller` or `admin` role through its durable
principal-authority registry. Initial configuration MAY seed a role only when
the registry has no binding and MUST NOT overwrite persisted authority state.
The route-selected role and registry-selected principal set MUST determine
authorization; a body field, bare address, URL, provider identifier, or private
credential MUST NOT select or imply authority.

Provisioning clients MUST receive the endpoint and exact expected service
authority principal from registry or composition context independently of
request content. A cryptographically valid response from any other principal
MUST fail verification.

#### Scenario: A configured role seeds an empty registry

- **WHEN** the authority starts without a persisted binding for a supported
  caller role
- **THEN** it records that role's configured complete principal as the first
  authority generation

#### Scenario: Configuration differs from durable authority state

- **WHEN** a persisted role binding already exists and bootstrap configuration
  names another principal
- **THEN** the persisted registry remains authoritative

#### Scenario: A valid unregistered principal calls a route

- **WHEN** a cryptographically valid principal is absent from the active set
  for the route's required role
- **THEN** authorization fails before the handler or any external effect runs

#### Scenario: A different service principal signs a response

- **WHEN** a valid principal other than the client registry's expected
  provisioning authority signs the response
- **THEN** the client rejects the acknowledgement

### Requirement: Provisioning identity credentials and package boundaries are isolated

The provisioning service MUST construct its signer from private credential
material supplied through an approved secret boundary, require that signer to
match its configured public principal, and keep the service signer independent
from storefront and administrator trust principals and optional chain-wallet
credentials. Ordinary configuration, durable authority and replay records,
request and response bodies, logs, manifests, and diagnostics MUST contain only
public principals, trust pins, proofs, and operation metadata, never private
signing material.

Compute provisioning service and client packages MUST consume the shared
identity package's scheme-tagged principals, signer and verifier contracts,
canonical request and response models, replay primitives, and rotation models.
They MUST NOT derive addresses, inspect raw private keys, branch on signature
encoding, or define a second service-signature protocol.

#### Scenario: A wallet-free authority is configured

- **WHEN** the service and its counterparty use Ed25519 principals
- **THEN** authenticated provisioning requests, responses, replay recovery, and
  rotation run without an EVM wallet, RPC endpoint, chain ID, or EVM private key

#### Scenario: EIP-191 is explicitly configured

- **WHEN** a provisioning role uses an EIP-191 principal
- **THEN** the same canonical request and response coverage applies and proof
  verification remains local

#### Scenario: The service credential is loaded

- **WHEN** composition constructs the provisioning authority signer
- **THEN** it consumes the secret-injected credential, verifies that the
  resulting public principal matches configuration, and exposes only the
  signer operation and public principal to orchestration

#### Scenario: Provisioning package boundaries are inspected

- **WHEN** service and client identity dependencies are checked
- **THEN** protocol canonicalization, cryptographic scheme dispatch, replay
  classification, and rotation proof validation resolve from the shared
  identity package rather than provisioning-specific copies

### Requirement: Counterparty principals rotate with dual proof

A provisioning authority MUST rotate a durable role binding only when the
active and replacement principals both sign the same bounded rotation
statement for that stable role subject and authority. It MUST record the
replacement as a new generation, accept both principals only during the
recorded overlap, retire the old principal when the overlap closes, and retain
the rotation audit. Disablement MUST remain distinct from rotation and MUST
remove authority without assigning it to another principal.

#### Scenario: A counterparty rotates its principal

- **WHEN** valid old-principal and replacement-principal proofs authorize a
  bounded overlap
- **THEN** either principal authenticates the same counterparty role until the
  overlap expires or the old principal is explicitly retired

#### Scenario: Replacement proof is absent

- **WHEN** a rotation request names a replacement principal without its proof
  over the same rotation statement
- **THEN** the authority does not bind or promote that principal

#### Scenario: A retired principal is used

- **WHEN** a counterparty signs with a principal whose overlap has ended
- **THEN** the call is rejected

#### Scenario: A counterparty is disabled

- **WHEN** an operator disables a counterparty binding
- **THEN** no principal retains authority, the audit history remains, and the
  operation does not transfer that authority to another principal

### Requirement: Allocation-backed executor registration
Market-managed VM and bare-metal leases MUST attach executor kind, target, and executor-specific reference data to an existing committed site allocation.

#### Scenario: Bare-metal lease is registered
- **WHEN** a caller registers a lease for a committed allocation and bare-metal machine
- **THEN** the allocation records the `bare_metal` executor kind, machine target, and physical-host reference

### Requirement: Executor-dispatched lifecycle
Market-managed release MUST dispatch by executor kind; direct VM host administration endpoints MAY remain separate operator surfaces.

#### Scenario: Bare-metal allocation is released
- **WHEN** its lease lifecycle invokes release
- **THEN** dispatch selects the bare-metal reclaim executor rather than VM teardown

### Requirement: Durable asynchronous jobs
Provisioning operations MUST expose durable job identity and terminal status while the in-process worker queue executes provider actions.

#### Scenario: Client polls an accepted job
- **WHEN** the worker completes or fails the action
- **THEN** the job status exposes a terminal result or error linked to the allocation/deal

### Requirement: Allocation-backed lease release
Lease expiry MUST invoke the configured executor release delegate before capacity is reported released; failed release MUST remain observable and operator-repairable.

#### Scenario: Teardown fails
- **WHEN** the release delegate returns a failure
- **THEN** capacity remains unavailable, the lease enters `release_failed`, and retry/force-release controls remain available

### Requirement: Site-backed release lifecycle
Compute lease lifecycle MUST use an injected site-authority port and MUST NOT report capacity released until the selected executor release succeeds or an operator performs an explicit force-release action.

#### Scenario: Executor release succeeds
- **WHEN** a lease expires and its registered executor completes teardown or reclaim
- **THEN** compute lifecycle records successful allocation release through the site-authority port and capacity becomes available

#### Scenario: Executor release fails
- **WHEN** VM teardown or bare-metal reclaim returns a failure
- **THEN** the allocation remains unavailable, the lease exposes `release_failed`, and retry and force-release controls retain the failure evidence

#### Scenario: Operator force-releases allocation
- **WHEN** an authorized operator force-releases after an unrecoverable executor failure
- **THEN** the audit state distinguishes the operator override from successful physical teardown

Release submission and release-completion reads are separate, independently kind-routed seams, because what "teardown complete" means differs by executor kind: bare-metal submits one job to a shared job queue and polls that job directly; VM teardown is a durable, multi-step fulfillment aggregate (see the Fulfillment specification's "Fulfillment convergence worker") with its own dispatch and status-convergence passes, running independently of the lease watchdog's own poll cadence. Compute lease lifecycle stays kind-agnostic on both sides: a release-job port is resolved by the reservation's executor kind the same way release submission already resolves an executor delegate by kind, so adding or changing one executor's completion semantics does not touch the generic watchdog or any other kind's path. VM's specific delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "VM release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" below (`## Relationship to fulfillment`); this section states only the kind-routing rationale that applies to bare-metal too.

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** an executor's release delegate reports no pollable job for a submitted release (e.g. no release mechanism configured for that kind)
- **THEN** the lease lifecycle treats it as immediately complete, independent of whether any other executor kind has a release-job port configured

### Requirement: Explicit early lease termination

An authorized caller MUST be able to end a lease before its natural expiry through the same release mechanism the watchdog's expiry sweep uses, rather than through a separate termination code path.

#### Scenario: Caller terminates a lease before its natural end

- **WHEN** an authorized caller requests termination of a lease whose end time has not yet passed
- **THEN** release begins immediately through the reservation's registered executor delegate, without waiting for a watchdog cycle and without bypassing the release-job tracking a watchdog-detected expiry would also go through

### Requirement: Lease registration tolerates omitted identity hints

Lease registration MUST NOT require a caller to resupply identity information the executor's own committed resource attributes already carry. Registration MAY omit an executor-kind-specific physical-target hint; a release delegate resolving that hint later from the reservation's own attributes MUST produce the same outcome as if the hint had been supplied at registration.

#### Scenario: Registration omits a physical-target hint already implied by the committed resource

- **WHEN** a lease is registered without an executor-kind-specific physical-target hint, and the reservation's committed resource already carries the equivalent attribute
- **THEN** release still resolves the correct physical target and no lease registration fails or degrades for the omission

### Requirement: Lifecycle dependency isolation
Generic lease lifecycle and watchdog scheduling MUST depend on executor and site ports rather than concrete VM, bare-metal, storefront, or HTTP client implementations.

#### Scenario: Lifecycle is tested with registered delegates
- **WHEN** a test registers independent site and executor delegates
- **THEN** lease expiry, failure, retry, and release transitions execute without importing a concrete domain or storefront composition root

### Requirement: Adapter-owned compute execution

VM and bare-metal execution MUST consume the common compute-provisioning envelope while concrete adapters own action validation, infrastructure invocation, result interpretation, credentials, and release behavior.

#### Scenario: Generic provisioner dispatches VM work

- **WHEN** a committed allocation identifies the VM executor and a supported action
- **THEN** generic orchestration selects the registered VM adapter without importing or inspecting VM request fields

#### Scenario: Generic provisioner dispatches bare-metal work

- **WHEN** a committed allocation identifies the bare-metal executor and a supported action
- **THEN** generic orchestration selects the registered bare-metal adapter without importing or inspecting access-grant fields

### Requirement: Compute-owned caller contract

Shared storefront/provisioner DTOs, executor-neutral resource-pool models, and generic client behavior MUST be owned by compute provisioning rather than the VM domain, while direct VM operator APIs MAY retain VM-owned host, VM action, Ansible job, credential, and lease models.

#### Scenario: Bare-metal storefront installs the shared client

- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: Provisioning service exposes resource-pool administration

- **WHEN** the VM operator client or provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that executor-neutral model resolves from `compute_provisioning` without depending on a VM-domain generic provisioning-client package

### Requirement: Compute-owned provisioning service

Cross-domain compute orchestration, including mechanism-neutral fulfillment coordination, MUST run from a deployable service owned by `provisioning/compute`, while VM and bare-metal packages retain their concrete executor and fulfillment-provider semantics and register them through explicit adapter bundles.

#### Scenario: Compute service starts with configured adapters

- **WHEN** the compute provisioner starts with VM and bare-metal adapters configured
- **THEN** it mounts generic job, lease, capacity, fulfillment, health, and watchdog surfaces plus each adapter's declared executor, provider, and operator surfaces

#### Scenario: Generic service is inspected for dependencies

- **WHEN** package and import boundaries are checked
- **THEN** generic compute service modules do not import concrete VM or bare-metal request, action, result, playbook, provider, fulfillment-requirement, or access models

### Requirement: Validated executor registration

Service composition MUST reject duplicate executor/action kinds, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor kind. Provider fulfillment and executor dispatch remain separate paths unless composition explicitly joins them through a supported lifecycle.

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for an executor/action kind
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers executor adapters and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace an executor adapter

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job. Create metadata MUST retain the exact `vm_host` and `vm_target`, and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

Reservation-governed VM shape is resolved from the committed reservation dimensions carried by the scheduled settlement resource. Caller-supplied sizing fields do not override or fill missing committed dimensions. For each dimension absent from the committed reservation, the adapter MAY apply the corresponding pool default; if neither a committed dimension nor a pool default exists, the provider input remains unset and the selected playbook or inventory supplies its own default. The pool-selected registered requirement delegate owns conversion from canonical VM dimensions into the selected playbook's variable names, units, and derived values.

The fulfillment request's `connectivity` field MUST NOT carry relay configuration. Which relay a host dials is a durable property of the deployment, recorded on the relay a pool references, and MUST NOT be selectable per request: a request-supplied relay would make a fleet-wide fact depend on a caller's configuration and would let two requests for one host disagree about how that host is reached. The buyer-facing address and port are returned in the fulfillment result rather than supplied with the request. Any remaining `connectivity` content is opaque metadata the adapter forwards unchanged and never interprets, and is not a sizing or feasibility requirement.

#### Scenario: A request supplies relay configuration

- **WHEN** a fulfillment request's `connectivity` field carries a relay address, domain, or dashboard credential
- **THEN** the value does not select a relay, and the relay referenced by the pool is used instead

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

### Requirement: VM fulfillment result payload

`AnsibleFulfillmentProvider.fetch_credentials` (see `openspec/specs/fulfillment/spec.md#requirement-provider-contract`) MUST return a `vm.fulfillment.result.v1` versioned envelope, defined in `vm_provisioning_adapter/fulfillment_results.py`, nested inside the generic `fulfillment.result.v1` envelope's `domain_result` field. Its payload carries `provisioned_resources` (each output's `provisioned_resource_id` and `status`, mirroring the fulfillment-owned identity the kit already exposes) and `credentials`: a tuple of `role`, `password`, `ssh_commands`, `ssh_key_path_host`, `key_type`, and `provisioned_resource_ids` — the output identities that credential is associated with, expressed this way so a fulfillment with more than one provisioned resource can eventually express which credential belongs to which output rather than a single flat list. Today every VM fulfillment produces exactly one `ProvisionedResource`, so every credential's `provisioned_resource_ids` names that one output; this is a real limitation, not yet a genuine many-to-many resolution, since the adapter has no way to attribute an individual credential to a specific output when more than one exists. Credentials MUST be sourced from `AnsibleJobService.get_credentials(job_id)` and MUST NOT be persisted by this adapter or by the fulfillment kit — they exist only in the response constructed for one `get_fulfillment_result` call.

The payload also carries an optional `connection_info` object (`vm_name`, `host`, `timestamp`, `tenant_user`, `vm_ip_internal`, `ssh_port`) — structured VM identity/connection metadata, best-effort read from the same job's parsed Ansible result alongside credentials. A missing or unreadable result must not fail an otherwise-successful credential fetch, so every `connection_info` field, and `connection_info` itself, is optional. Each credential's `ssh_commands` already carries a ready-to-use connection string (host, port, and tenant user baked in), so `connection_info` is not required to connect — it exists for callers that want the pieces separately rather than parsing a command string.

#### Scenario: Result query on an active VM fulfillment includes the domain payload

- **WHEN** `get_fulfillment_result` is called for a `fulfillment_id` whose VM fulfillment is `active`
- **THEN** the envelope's `domain_result` is a `vm.fulfillment.result.v1` payload whose `credentials` reflect a live `AnsibleJobService.get_credentials` read for the recorded job, and whose `provisioned_resources` mirror the fulfillment kit's own `ProvisionedResource` rows

#### Scenario: Job result carries connection metadata

- **WHEN** the recorded job's parsed result includes VM identity/connection fields
- **THEN** `domain_result`'s `connection_info` carries them, without failing the credential fetch if any individual field is absent

### Requirement: Generic provisioning has one package owner

Generic provisioning service and client paths MUST resolve from the top-level
provisioning category. VM-domain packages MUST contain only concrete adapters
and assets and MUST NOT expose generic aliases or compatibility distributions.

#### Scenario: Package ownership is inspected

- **WHEN** repository package, import, image, and manifest references are
  inspected
- **THEN** generic compute provisioning resolves only from the top-level
  provisioning category and domain packages contain only their concrete
  adapters and assets

### Requirement: Persisted VM leases use provider contracts

When a persisted VM lease is represented in the fulfillment aggregate, the
selected resource SHALL resolve through host and resource-pool configuration.
The VM target SHALL be derived from the consistent persisted VM and executor
target fields, and known create or teardown job identifiers SHALL be retained
in provider metadata. Any prepared teardown operation SHALL be produced by the
VM Ansible provider's `prepare_teardown` contract using the snapshotted pool
configuration rather than by constructing provider payload JSON independently.

#### Scenario: A persisted VM lease resolves through provider configuration

- **WHEN** a persisted VM lease is represented in the fulfillment aggregate
- **THEN** its selected resource, VM target, and any prepared teardown operation
  are derived through host and resource-pool configuration and the provider
  contract rather than reconstructed independently


### Requirement: VM release delegates to durable fulfillment teardown

For VM reservations, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The VM release adapter SHALL use the durable `fulfillment_id` as the release tracking identifier and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL be selected by `executor_kind`; VM lookup SHALL read fulfillment aggregate state while bare-metal lookup MAY read its executor job service.

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents VM teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

### Requirement: Lease release and fulfillment teardown have separate retry ownership

Lease lifecycle SHALL own the reservation's `releasing` and terminal release states, final capacity return, and release notification. Fulfillment convergence SHALL own teardown dispatch, provider polling, retry, and recovery through `torn_down` or `teardown_failed`. An operator lease retry SHALL re-observe the same fulfillment aggregate and SHALL NOT create a second teardown operation. Capacity SHALL remain held until the fulfillment reaches `torn_down` or an explicit force-release occurs.

#### Scenario: Failed teardown is requeued without duplicate teardown

- **GIVEN** a VM reservation is `releasing` and its fulfillment is `teardown_failed`
- **WHEN** fulfillment convergence requeues teardown and an operator retries lease release
- **THEN** both paths SHALL continue using the same `fulfillment_id`
- **AND** capacity SHALL remain unavailable until that aggregate reaches `torn_down`

### Requirement: Provisioning shape comes from committed capacity

A fulfillment provider MUST derive reservation-governed resource shape from the dimensions carried by the scheduled settlement resource -- which reflect what was actually scheduled, bounded by but not necessarily equal to the capacity reservation (see `openspec/specs/site-capacity/spec.md#requirement-committed-dimensions-remain-authoritative-through-scheduling`). It MUST NOT use caller-supplied fulfillment fields as fallback values for that shape.

For an Ansible-backed VM pool, provider configuration identifies both the playbook and a registered requirement delegate. The adapter resolves the delegate through an allowlisted registry. The delegate validates that the committed canonical VM dimensions are representable by the playbook and translates them into the playbook's variable names, units, and derived values. Resource-pool configuration MUST NOT load arbitrary Python import paths.

#### Scenario: Provider derives shape from the scheduled resource, not caller-supplied fields
- **WHEN** a fulfillment provider prepares a create operation for a scheduled settlement resource
- **THEN** it derives the provisioned shape from that resource's own committed dimensions, not from any shape fields the caller's fulfillment request happens to carry

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
seeding inventory. A bare-metal inventory host MAY name its exact pool through
`pool_id`; the seed MUST reject an unknown pool and MUST preserve that binding
on create and update. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration:
execution uses service-owned configuration and the scheduler-selected Physical
Resource. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and unknown pool ids fail instead of falling back to `default`

#### Scenario: Pool-local executor configuration is supplied

- **WHEN** a `bare_metal.ansible` pool contains a non-empty `provider_config`
- **THEN** validation rejects the pool before it can authorize or dispatch fulfillment

### Requirement: Hosted funding gates whole-host allocation

For a hosted bare-metal obligation, no Capacity Reservation commit, scheduling, executor dispatch, lease, or access grant may begin before authoritative funding is ready. The fulfillment identity MUST be derived from the accepted agreement, obligation, seller-owned Physical Resource or pool selection, site, buyer, claimant, and executor kind. Replay and restart MUST converge on the same selected-site reservation and fulfillment; they MUST NOT substitute a different resource or site.

#### Scenario: Access-ready evidence

- **WHEN** the funded selected-site fulfillment becomes authoritatively access-ready
- **THEN** the storefront persists a public result and content-addressed seller-signed lease-ready evidence before collection
- **AND** the evidence binds agreement, obligation, accepted binding, fulfillment, buyer, seller, claimant, site, executor, resource/allocation, condition, access method, and expiry without exposing credentials

#### Scenario: Teardown is independent

- **WHEN** financial collection is complete and the lease later expires
- **THEN** revocation, executor teardown, and capacity release converge under their physical operation identities
- **AND** no financial reclaim is inferred from teardown

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

#### Scenario: A host is registered on a tunnel port

- **WHEN** a host is registered with an SSH port other than 22
- **THEN** the recorded port is returned by the host endpoints and appears as `ansible_port` in every rendered inventory for that host

#### Scenario: An inventory file supplies a port

- **WHEN** an INI inventory carrying `ansible_port` is imported
- **THEN** the port is stored against the host and survives to the rendered inventory the provisioner connects with

#### Scenario: An inventory file supplies a malformed port

- **WHEN** an INI inventory entry carries an `ansible_port` that is not a port number between 1 and 65535
- **THEN** that entry is rejected with a warning naming the host, other entries in the same file are still imported, and no host is registered with a substituted port

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

Rebinding is therefore drain-then-change: disabling a pool already excludes it from new scheduling without invalidating active workloads, so an operator disables, waits for leases to clear, rebinds, and re-enables.

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
- **THEN** the update is rejected

#### Scenario: A VM is torn down after its pool was rebound

- **WHEN** teardown runs for a VM whose pool now references a different relay
- **THEN** the relay recorded on the VM's lease is used, and the port is released against it

### Requirement: Relay admission tokens are resolved at execution

A relay's admission token MUST NOT be written into an accepted operation's persisted parameter snapshot, and MUST NOT appear in any job status or job list response. Job parameters are persisted unencrypted and are returned by the job endpoints, so a token placed among them is neither protected at rest nor withheld from a read.

An accepted operation MUST carry the relay reference and the leased remote port. The relay's address and admission token MUST be resolved immediately before the job's variables are written, so that a token rotated after acceptance takes effect on the next execution, including a retry of a job accepted before the rotation.

A relay that is absent, disabled, or holds no token at execution MUST fail the job as a configuration error rather than a retryable one, because a retry against unchanged configuration fails identically.

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

- **WHEN** the referenced relay is disabled or its token cleared before the job executes
- **THEN** the job fails as a configuration error and is not retried

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

### Requirement: Passthrough binding cannot strand a host

Host preparation MUST NOT render a machine unreachable. A device is assigned to guests by binding a PCI address, never a vendor/device identifier: an identifier matches every device presenting it anywhere in the machine, including devices in IOMMU groups no decision considered.

Passthrough viability MUST be audited before any binding is configured, and the audit MUST be read-only so it is safe to run against a machine nothing else has touched. A GPU whose IOMMU group contains a network controller, a storage controller, the device carrying the host's default route, or the device carrying its root filesystem MUST be reported unavailable rather than bound, because assigning it would require assigning that device with it.

An absent or disabled IOMMU MUST fail closed. "No groups because the IOMMU is disabled" and "groups assessed, no conflicts found" MUST be distinguishable outcomes, and only the second may result in a device being bound.

Bindings MUST be applied while an operator or automation holds a live connection to the host, and MUST NOT be persisted across reboots until they have been applied and verified on that machine. A reboot may enable the IOMMU, which claims no device; it MUST NOT carry a device binding that has not been verified.

Declared GPU capacity MUST count devices that can be assigned to a guest, not devices present, so a host does not publish capacity no fulfillment can satisfy.

#### Scenario: A GPU shares its group with a host-critical device

- **WHEN** the audit finds a GPU whose IOMMU group contains the device carrying the host's default route
- **THEN** that GPU is reported unavailable with the blocking device named, no binding is configured for it, and any GPU in a clean group on the same host is still bindable

#### Scenario: The IOMMU is not enabled

- **WHEN** the audit runs on a host exposing no IOMMU groups
- **THEN** it reports that viability cannot be assessed, distinctly from reporting no conflicts, and no device is bound

#### Scenario: A binding is applied

- **WHEN** audited bindings are applied
- **THEN** they are applied with a live connection to the host, every audited address is confirmed bound, the device carrying the default route is confirmed to hold the driver it held beforehand, and only then is the binding made to persist across reboots

#### Scenario: A binding fails

- **WHEN** applying a binding fails
- **THEN** the failure is reported, the host remains running and reachable, virtualization remains available, and the affected device is not counted as capacity

## Evidence

- VM and bare-metal allocation executor metadata: `provisioning/compute/service/tests/integration/test_leases_api.py` and `test_bare_metal_leases_api.py`.
- Multidimensional scheduling eligibility, including secondary-dimension rejection and GPU-only requests: `provisioning/compute/service/tests/integration/test_scheduling_composition.py`.
- Persisted asynchronous job lifecycle and polling: `provisioning/compute/service/tests/integration/test_vms_api.py`.
- Executor-specific release, failed-release capacity retention, retry, and force release: `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`, `test_leases_api.py`, and `unit/services/test_ledger_lease_lifecycle.py`.
- Adapter composition and generic import boundaries: `provisioning/compute/service/tests/unit/test_composition.py` and `test_import_boundaries.py`.
- VM sizing precedence (committed reservation, pool default, unset), relay access-path selection, and result credential/connection-metadata fields: `provisioning/compute/service/tests/unit/services/test_ansible_fulfillment_provider.py` (`TestSizingPrecedence`, `TestRelayAccessPath`, `TestTeardownReadsTheLease`), plus end-to-end HTTP coverage in `provisioning/compute/service/tests/integration/test_fulfillment_api.py::TestStatusAndResultQueries`.
- Relay administration, token confidentiality, rebinding, and definition-document reconciliation: `provisioning/compute/service/tests/unit/services/test_relay_administration.py`, `test_relay_port_allocator.py`, `test_relay_port_leases.py`, `test_definition_document_restart_safety.py`, plus `tests/integration/test_relays_api.py` through the canonical client.
- Relay port release on terminal settlement states, and the terminality predicate reconciliation is given: `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence.py`.

`PhysicalSettlementScheduler` and fulfillment-provider coordination are durable, not process-local: scheduling, acceptance, and dispatch state live in the fulfillment aggregate (see `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`), and a dedicated periodic worker recovers in-flight provider operations after a crash or restart (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` and `docs/development/ARCHITECTURE.md#recovery-workers`). This is a database-wide SQLite writer guarantee, not a distributed multi-replica protocol.

## Capacity settlement lifecycle

Physical provisioning distinguishes **Capacity Reservation → Capacity Settlement Assignment → Physical Settlement → Provisioned Resource / Active Workload**. Generic scheduling chooses an eligible Settlement Resource. Physical Settlement is provider-specific execution on that assigned resource. Provider-specific reachability, credentials, topology, and execution failures remain downstream of generic scheduling eligibility.

Scheduling uses deterministic round-robin through a replaceable policy interface. Generic policy and orchestration code use resource kind, a per-dimension quantity map (`dimensions`/`available`, checked against every requested dimension), pool identity, and opaque attributes and do not import market-specific executor persistence models.

## Relationship to fulfillment

The [fulfillment specification](../fulfillment/spec.md) owns provider-neutral settlement requests, settlement-resource scheduling, provider contracts, lifecycle identifiers, and versioned provider envelopes. This specification begins at compute-service composition and concrete executor/provider dispatch.

The compute provisioner may compose both a fulfillment-provider registry and an executor registry, but they remain distinct namespaces. Scheduling selects a `SettlementResource`; provider execution acts on that resource; executor dispatch performs domain-specific infrastructure actions. No one registration implicitly selects another.

Generic compute service modules may import `market_fulfillment`. `market_fulfillment` must not import the deployed compute service or VM/bare-metal adapters.
