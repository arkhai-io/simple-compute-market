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

### Requirement: Executor-dispatched lifecycle
Market-managed release MUST begin the reservation's fulfillment teardown through one provider-neutral release executor, whatever the reservation's offering mode; the fulfillment's provider dispatches the domain's teardown. Direct VM host administration endpoints MAY remain separate operator surfaces.

#### Scenario: Bare-metal allocation is released
- **WHEN** its lease lifecycle invokes release
- **THEN** release begins the bare-metal fulfillment's durable teardown, whose provider dispatches the bare-metal reclaim rather than VM teardown

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

Release submission and release-completion reads are separate seams, and neither is selected by offering mode. Every offering mode's teardown is a durable, multi-step fulfillment aggregate (see the Fulfillment specification's "Fulfillment convergence worker") with its own dispatch and status-convergence passes, running independently of the lease watchdog's own poll cadence; what a provider does to tear down differs by mode, not how lease lifecycle begins it or observes completion. Compute lease lifecycle is therefore mode-agnostic: one provider-neutral release executor begins the aggregate's teardown and one status port reads the aggregate, so adding a mode registers a fulfillment provider and touches neither seam. The delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "Lease release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" below (`## Relationship to fulfillment`).

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Bare-metal lease release begins durable fulfillment teardown

- **WHEN** a bare-metal lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the same provider-neutral delegate begins the bare-metal fulfillment's teardown and returns its fulfillment identifier, and no reclaim job is submitted outside the aggregate

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** a lease is due for release but the release executor finds no fulfillment aggregate to tear down, so it reports no job to poll
- **THEN** capacity is released directly only if the reservation's provenance proves that nothing was dispatched; otherwise the lease enters `release_failed` and capacity stays held until an operator force-releases it, and nothing to poll never counts as a completed release by itself

### Requirement: Explicit early lease termination

An authorized caller MUST be able to end a lease before its natural expiry through the same release mechanism the watchdog's expiry sweep uses, rather than through a separate termination code path.

#### Scenario: Caller terminates a lease before its natural end

- **WHEN** an authorized caller requests termination of a lease whose end time has not yet passed
- **THEN** release begins immediately through the reservation's registered executor delegate, without waiting for a watchdog cycle and without bypassing the release-job tracking a watchdog-detected expiry would also go through

### Requirement: Lifecycle dependency isolation
Generic lease lifecycle and watchdog scheduling MUST depend on executor and site ports rather than concrete VM, bare-metal, storefront, or HTTP client implementations.

#### Scenario: Lifecycle is tested with registered delegates
- **WHEN** a test registers independent site and executor delegates
- **THEN** lease expiry, failure, retry, and release transitions execute without importing a concrete domain or storefront composition root

### Requirement: Adapter-owned compute execution
VM and bare-metal execution MUST consume the common compute-provisioning envelope. Domain adapter contributions MUST own action-specific validation, execution preparation, codec and playbook selection, domain result interpretation, credential meaning, and release behavior; reusable execution technology MAY own the mechanics of invoking a prepared execution.

#### Scenario: Generic provisioner dispatches VM work
- **WHEN** a committed allocation identifies the VM executor and a supported action
- **THEN** generic orchestration selects the registered VM adapter without importing or inspecting VM request fields

#### Scenario: Generic provisioner dispatches bare-metal work
- **WHEN** a committed allocation identifies the bare-metal executor and a supported action
- **THEN** generic orchestration selects the registered bare-metal adapter without importing or inspecting access-grant fields

#### Scenario: Shared Ansible mechanics run a domain's job
- **WHEN** a VM or bare-metal job runs through the shared Ansible executor
- **THEN** the domain's codec renders its variables and interprets its result, and the shared mechanics hold no VM or bare-metal meaning

### Requirement: Compute-owned caller contract
Shared storefront/provisioner DTOs, the job, host, credential, lease, and system-status wire models, and the family's route contracts MUST be owned by compute provisioning rather than the VM domain, in a contracts distribution that depends on no service, persistence, or web-framework package. Routes the provisioning service hosts for another capability, such as resource-pool administration and capacity-definition import, MUST keep that capability's models, contracts, and client; hosting a route does not make it compute provisioning's. The family's typed client MUST be a separate client distribution depending on no service, persistence, or web-framework package: only that contracts distribution, the core carrier package, the identity kit, its HTTP library, and its model library; it offers async and sync variants with identical operations, and the family kit itself MUST contain no client. Direct VM operator APIs MAY retain VM-owned VM action, relay, and VM pool-configuration models and a VM client extension over the family client's authenticated transport; callers import compute-owned models from the contracts distribution. Compute provisioning MUST NOT name a domain's routes: a domain, an execution implementation, or another capability MUST contribute the route contracts of the routes it mounts. The service's request authentication MUST resolve requests against the table the provisioning service's composition root assembles from those contributions; each typed client MUST sign its routes from its owner's contracts. Where the owner's contracts are one declaration that both the service's table and the client read, as the compute family's, the resource-pool authority's, the Ansible implementation's, and each domain's are, operation, resource binding, and roles cannot diverge. Where an owner keeps separate server and client declarations, as the site capacity authority does, a contract-parity test MUST hold the two equal in method, path, operation, resource binding, and the models they exchange.

#### Scenario: Bare-metal storefront installs the shared client
- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: A storefront installs the client without the family kit
- **WHEN** a storefront depends on the compute-provisioning client
- **THEN** it installs the contracts and client distributions only, and no persistence, web-framework, or job-authority package arrives with them

#### Scenario: Provisioning service exposes resource-pool administration
- **WHEN** an operator client or the provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that offering-mode-neutral model resolves from the resource-pool capability's contracts distribution, not from compute provisioning or a VM-domain package

#### Scenario: A domain's routes are signed and authenticated
- **WHEN** a compute domain mounts routes on the provisioning service
- **THEN** it contributes their route contracts, and neither the compute-provisioning client nor the service's authentication needs a compute-provisioning change to sign or authorize them

#### Scenario: An operator reads a lease
- **WHEN** an operator reads a VM or bare-metal lease through the generic lease routes
- **THEN** the response is the neutral lease view, carrying no VM-only field

### Requirement: Compute-owned provisioning service

Cross-domain compute orchestration, including mechanism-neutral fulfillment coordination, MUST run from a deployable service owned by `provisioning/compute`, while VM and bare-metal packages retain their concrete executor and fulfillment-provider semantics and register them through explicit adapter bundles.

#### Scenario: Compute service starts with configured adapters

- **WHEN** the compute provisioner starts with VM and bare-metal adapters configured
- **THEN** it mounts generic job, lease, capacity, fulfillment, health, and watchdog surfaces plus each adapter's declared executor, provider, and operator surfaces

#### Scenario: Generic service is inspected for dependencies

- **WHEN** package and import boundaries are checked
- **THEN** generic compute service modules do not import concrete VM or bare-metal request, action, result, playbook, provider, fulfillment-requirement, or access models

### Requirement: Validated executor registration

Service composition MUST reject duplicate job-executor registrations for one `(offering_mode, action)` key, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. A job executor MUST be selected by the `offering_mode` it serves together with its action; no surface may name that selector `executor_kind`, `offering_type`, or `virtualization_type`. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor's offering mode. A fulfillment provider submits its jobs to the job authority, which resolves each job's executor through the executor table.

`executor` names the job-execution abstraction and nothing else when it is the head noun. It MUST NOT stand in for the offering mode, the machine, or the delivery handler: the mode is an offering mode, the machine is a host, and the handler is a provider. The abstraction keeps the name because it executes a job and returns its outcome; only its selector moves.

`executor_`-prefixed compounds naming the abstraction's own targets, references, or actions MUST retain the name, because `executor` carries its execution sense in them rather than standing in for another concept. `executor_ref` is the executor's reference, `executor_target` is the target of an executor action, and an executor action envelope carries an executor action; none of these is the mode, the machine, or the handler as a head noun. This requirement's prohibition therefore applies to the head noun and MUST NOT be read as a prohibition on the prefix.

#### Scenario: An executor-prefixed compound names the abstraction's own target

- **WHEN** a durable reservation or lease records the target or reference an executor action acts on
- **THEN** those fields retain their `executor_`-prefixed names
- **AND** the offering-mode selector on the same record does not, because its head noun is the mode

#### Scenario: Two adapters claim one offering mode

- **WHEN** composition registers two job executors for the same `offering_mode` and action pair
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers job executors and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace a job executor

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job. Create metadata MUST retain the exact `host_id` and `executor_target` (the guest provisioning named), and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

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

### Requirement: Lease release and fulfillment teardown have separate retry ownership

Lease lifecycle SHALL own the reservation's `releasing` and terminal release states, final capacity return, and release notification. Fulfillment convergence SHALL own teardown dispatch, provider polling, retry, and recovery through `torn_down` or `teardown_failed`. An operator lease retry SHALL re-observe the same fulfillment aggregate and SHALL NOT create a second teardown operation. Capacity SHALL remain held until the fulfillment reaches `torn_down` or an explicit force-release occurs.

#### Scenario: Failed teardown is requeued without duplicate teardown

- **GIVEN** a reservation is `releasing` and its fulfillment is `teardown_failed`
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
on create and update. A capacity declaration's explicit `bare_metal_publication`
view MUST carry the declaration's own pool. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration:
execution uses service-owned configuration and the scheduler-selected Physical
Resource. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and unknown pool ids fail instead of falling back to `default`

#### Scenario: Publication retains the inventory pool binding

- **GIVEN** a bare-metal inventory host is bound to a configured provider pool
- **AND** the capacity declaration naming that host is in the same pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is that pool, taken from the declaration

#### Scenario: Publication carries the declaration's pool

- **GIVEN** a capacity declaration with an enabled `bare_metal_publication` in a configured provider pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is the declaration's pool

#### Scenario: Pool-local executor configuration is supplied

- **WHEN** a `bare_metal.ansible` pool contains a non-empty `provider_config`
- **THEN** validation rejects the pool before it can authorize or dispatch fulfillment

### Requirement: A bare-metal publication view is built from its capacity declaration

A capacity declaration's bare-metal publication view SHALL take its Physical
Resource identity, pool, host, physical host identity, capacity, and availability
from that declaration alone, and SHALL NOT read a host inventory record. A
declaration whose publication is enabled but which names no host SHALL be
projected without the view rather than failing the projection generation.

#### Scenario: An enabled publication names no host

- **GIVEN** a capacity declaration with an enabled bare-metal publication and no
  host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration is projected without the bare-metal view and every
  other entry in the generation is unaffected

#### Scenario: The named host is not registered

- **GIVEN** a capacity declaration with an enabled bare-metal publication naming
  a host that has no registered record
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced and carries the declaration's host

### Requirement: Signed payment receipts gate selected-site execution

VM and bare-metal payment stages MUST load the accepted mandate from shared `negotiation_threads.settlement_data` beside exact `agreement_bytes` and verify the matching service-signed receipt before producing verified SettlementEvidence or any protected physical effect. Physical delivery MUST consume that evidence and the accepted domain/site binding, never compare mechanism IDs or create payment escrow/obligation rows. Restart MUST revalidate through the selected stage and reuse durable reservation and fulfillment identities rather than buyer-supplied routing or current listing state.

#### Scenario: Receipt is pending or mismatched

- **WHEN** the seller cannot verify a matching signed receipt
- **THEN** it reports retryable pending or rejects invalid evidence without provisioning or creating access

#### Scenario: Bare-metal receipt is verified

- **WHEN** payment settlement succeeds for an accepted bare-metal Agreement
- **THEN** reservation, fulfillment, result retrieval and teardown continue against that Agreement's selected-site authority

### Requirement: Bare-metal role tables own settlement choices

Bare-metal buyer and seller roles MUST each declare exactly their supported settlement entries. Acceptance hooks and seller settlement MUST resolve the Agreement's mechanism through the seller table; buyer purchase MUST use its buyer table. Payment-only buyer support MUST NOT imply seller-only mechanisms are supported by that buyer. Common physical delivery MUST receive verified evidence, not select a mechanism.

#### Scenario: Bare-metal buyer supports payment only

- **WHEN** discovery presents payment and seller-supported Alkahest options
- **THEN** the buyer selects only its declared compatible entry without hardcoding payment in purchase control flow

#### Scenario: Seller supports introduction instead of physical delivery

- **WHEN** its declared contact-exchange stage settles an accepted introduction
- **THEN** the fused stage retains introduction evidence and no physical reservation, access grant or payment is required

### Requirement: Bare-metal obligation servicing follows the accepted seller entry

Each bare-metal seller entry MUST declare its own obligation servicing: the
continuation the settlement servicing worker runs when an obligation becomes ready
and when it ends. The runtime MUST compose servicing only for entries that provide
it, and the worker's hooks MUST resolve the entry from the accepted Agreement of the
obligation's `agreement_ref`, not compare the obligation's mechanism with concrete
mechanism IDs. An obligation whose mechanism differs from its Agreement's, or whose
entry composes no servicing, MUST be refused before any servicing effect. An entry
whose obligations need no servicing, such as contact exchange whose reveal binds the
obligation, MUST decline explicitly.

#### Scenario: An Alkahest obligation becomes ready

- **WHEN** the servicing worker reports an Alkahest obligation ready
- **THEN** the hook resolves the Alkahest entry from the accepted Agreement and only
  that entry's lifecycle starts delivery

#### Scenario: An obligation names another mechanism than its Agreement

- **WHEN** a serviced obligation's mechanism differs from its accepted Agreement's
- **THEN** the hook refuses it and no entry's servicing acts


### Requirement: Bare-metal evidence is independent of escrow rows

Bare-metal settlement stages MUST persist accepted-Agreement-bound SettlementEvidence by negotiation ID. Fulfillment and status MUST read that record's verified status/reference, not accept an escrow row as alternative proof or interpret a chain-name sentinel. Established identity/source evidence MUST be conflict-protected. Incompatible evidence/lifecycle schemas MUST require explicit database reset without legacy payment-row copying or fallback. Before protected recovery effects, the selected stage MUST revalidate authoritative source evidence; an Alkahest journal's materialization identity alone MUST NOT authorize physical delivery.

#### Scenario: A legacy payment sentinel is presented

- **WHEN** an escrow row names `arkhai.payments.v1` as its chain but no verified negotiation evidence exists
- **THEN** it authorizes no physical effect and status does not treat it as payment verification

#### Scenario: Bare-metal delivery resumes from evidence

- **WHEN** a verified accepted negotiation is resumed without an escrow row
- **THEN** fulfillment uses its existing selected-site lifecycle and durable physical identity without creating a replacement reservation

#### Scenario: Accepted evidence conflicts

- **WHEN** a record is reused with another mechanism, Agreement digest or established reference
- **THEN** the write fails before capacity, access or provider mutation

#### Scenario: Materialized Alkahest source is no longer active

- **WHEN** recovery finds reclaim or collection in progress or completed, a non-ready mechanism status, or chain evidence no longer matching the accepted obligation
- **THEN** it refuses before reservation, fulfillment, access or teardown effects


### Requirement: Physical payment fulfillment recovers on accepted evidence

Retries and restart recovery MUST recheck accepted receipt evidence and converge on the same reservation and physical operation. VM's local provisioning-progress row MAY use the negotiation ID but MUST NOT turn the transaction into a chain escrow, settlement plan, or obligation.

#### Scenario: Verified VM provisioning restarts

- **WHEN** foreground work or recovery resumes verified payment progress
- **THEN** the existing convergence lease and durable physical fulfillment ID prevent duplicate delivery

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

A lease MUST be released with its reservation's capacity, in the transaction that releases it, whatever path releases it, and MUST NOT be released on a fulfillment state alone. A failed creation may leave a guest running with its tunnel bound, so its port is held, with its capacity, until an operator verifies the host and forces the release. A periodic reconciliation MUST release leases whose reservation has been released beyond a grace period, as a backstop rather than as the primary mechanism.

Allocation MUST be idempotent for one owner: allocating twice for the same fulfillment MUST return the lease already held rather than issuing a second port.

A pool whose referenced relay has no usable allocation window MUST be rejected before dispatch rather than producing a VM with no external route.

#### Scenario: Two hosts share a relay

- **WHEN** a port is leased for a VM on one host and a VM on a second host requests an allocation from the same relay
- **THEN** the second allocation selects a different port, rather than reissuing a port already bound on that relay

#### Scenario: A VM creation fails before teardown would run

- **WHEN** a VM's fulfillment fails, including after its provider reported the create succeeded
- **THEN** its port lease is held until an operator forces the release of its capacity, and is released then

#### Scenario: A release path is missed

- **WHEN** a lease's reservation has been released beyond the grace period and the lease is still held
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

### Requirement: A host has one identity name

A host's identity MUST be named `host_id` on every interface that names it: the
host registry, a capacity declaration's host link, reservation execution references,
fulfillment metadata, job parameters, lease APIs, playbook variables, and published
listings. No such interface MAY name that identity `name`, `vm_host`, `machine_id`, or
any other domain-prefixed spelling. The address the provisioner connects to is the
host's `ssh_host`. The stable identity of a physical machine across
hosts is a distinct concept and MUST keep its own name.

#### Scenario: A VM reservation binds to a host

- **WHEN** a VM reservation is admitted against a declaration delivered through a host
- **THEN** its execution reference names that host as `host_id`

#### Scenario: A bare-metal listing is published

- **WHEN** a bare-metal listing is published for a declaration delivered through a host
- **THEN** the listing names that host as `host_id` under the listing kind that
  carries it, and names the physical machine separately as `physical_host_id`

#### Scenario: Two hosts share one physical machine

- **WHEN** one physical machine is registered as a VM host and as a bare-metal node
- **THEN** each has its own `host_id`, and both declarations carry the same
  `physical_host_id` so cross-mode accounting sees one machine

### Requirement: Existing host identities migrate without loss

A compute provisioner MUST migrate every persisted host identity to `host_id` in one
transaction before serving requests. It MUST read and validate every affected row
before its first write, and the transaction MUST cover its schema changes as well as
its data, so a failure leaves both unchanged. A declaration whose host spellings
disagree, whose cross-mode accounting fields disagree between locations, or that
names a host another declaration names, MUST abort the migration, naming the row.
The migration MUST rewrite only the locations that carry a host identity; values an
operator supplied, such as provider variables, MUST NOT be rewritten whatever their
names.

#### Scenario: A declaration carries both legacy spellings with one value

- **WHEN** a declaration's `vm_host` and its publication `machine_id` name the same host
- **THEN** the migration records that host as the declaration's `host_id` and removes
  both legacy spellings

#### Scenario: A declaration carries conflicting spellings

- **WHEN** a declaration's `vm_host` and its publication `machine_id` name different hosts
- **THEN** the migration aborts, names the declaration, and leaves the database's
  schema and rows unchanged

#### Scenario: An operator variable shares a retired key's name

- **WHEN** a stored operation's provider variables include one named `machine_id`
- **THEN** the migration rewrites the operation's host identity and leaves that
  variable as it was

### Requirement: A bare-metal storefront refuses state written under a retired listing kind

A bare-metal storefront MUST refuse to start against a database whose persisted state
was written under a listing kind it no longer decodes, and the refusal MUST name the
operator procedure that resolves it. It MUST NOT start and then fail when a retired
record is first decoded.

#### Scenario: The storefront starts against a pre-rename database

- **WHEN** a bare-metal storefront starts against a database written under
  `bare_metal.v1`
- **THEN** startup fails before serving requests, naming the reset procedure, and no
  record is decoded or rewritten

#### Scenario: The storefront starts against a fresh database

- **WHEN** a bare-metal storefront starts against an empty database
- **THEN** it creates its schema under the current listing kind and serves requests

### Requirement: Host inventory is connection identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST NOT read host inventory records at all, and MUST NOT
project a host that no capacity declaration names. A host record is joined to a
capacity declaration only where its connection is used: at dispatch.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a host record still holds a capacity value from before capacity
  declarations existed
- **THEN** capacity projection does not read it and the projected capacity comes from
  the declared capacity resource for that Physical Resource

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no host inventory record contributes to the projection

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration names a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

### Requirement: Execution inventory comes only from the registered host record

The inventory an execution path hands to its executor SHALL be rendered from the
registered host record named by the selected settlement resource, and from no
other source. A host name with no registered host record SHALL fail the operation
before any playbook or executor command runs. A configured inventory file SHALL be
used only as a startup seed input that populates host records; no execution path
SHALL read it as an inventory, and no execution path SHALL target a host named only
by a request or a capacity declaration.

#### Scenario: Dispatch names an unregistered host

- **WHEN** fulfillment dispatch reaches an execution path for a host name with no
  registered host record
- **THEN** the operation fails before any playbook runs, and no fallback inventory
  is consulted

#### Scenario: A static inventory file names the host

- **GIVEN** a configured inventory file naming a host that has no registered host
  record
- **WHEN** an execution path runs for that host name
- **THEN** it fails exactly as it would with no inventory file present

#### Scenario: The inventory file seeds the host registry

- **WHEN** the provisioning service starts with a configured inventory file
- **THEN** the hosts it names are seeded into the host registry, and later
  execution renders from those records

### Requirement: The tenant-facing host address falls back to the connection address

Where an execution path derives a tenant-facing address for a host, it SHALL use
that host record's configured tenant-facing address when one is set, and otherwise
the record's connection address. It SHALL NOT read the address from a configured
inventory file.

#### Scenario: A host has no tenant-facing address

- **GIVEN** a registered host record with a connection address and no
  tenant-facing address
- **WHEN** a tenant's connection details are produced for that host
- **THEN** they carry the connection address

### Requirement: Legacy host capacity is derived into declarations

A compute provisioner MUST create a capacity declaration for a host inventory record
that carries a positive legacy GPU count and has no correlated declaration, at two
points only: when host inventory is applied from an INI document — whether seeded at
startup or submitted through the host import API — in the same transaction as the
host upsert, and once, by ordered migration, for host records present at upgrade.
Derivation MUST NOT run on a process start that applies no inventory, and MUST NOT
run when a host is created or updated through the individual host API.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.
Derivation MUST NOT overwrite or merge into an existing declaration, and an
operator-supplied declaration MUST win over any derivable legacy value.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner seeds host inventory carrying legacy GPU counts from an INI
  document and no capacity declarations exist
- **THEN** a declaration is derived for each such host in the same transaction as
  its host record
- **AND** published capacity is unchanged from before declarations existed

#### Scenario: Existing hosts at upgrade

- **WHEN** the ordered migration runs against a database holding hosts with legacy
  GPU counts and no correlated declarations
- **THEN** each such host receives a derived declaration before the service serves
  requests

#### Scenario: Operator declaration and legacy host value disagree

- **WHEN** a host carries a legacy capacity value and an operator has declared
  different capacity for the same Physical Resource
- **THEN** the operator's declaration is retained unchanged and no derivation occurs
  for that resource

#### Scenario: A declaration's resource id differs from its host

- **WHEN** a declaration whose resource id differs from a host's `host_id` names that
  host as its `host_id`
- **THEN** the host is treated as declared and no second declaration is derived for it

#### Scenario: A host is created through the individual host API

- **WHEN** an operator creates a host with a legacy GPU count through the individual
  host API
- **THEN** no declaration is derived, and the host's capacity is declared through the
  capacity administration surface

#### Scenario: A host has no GPUs

- **WHEN** host inventory is applied for a host whose legacy GPU count is zero
- **THEN** no declaration is derived for it

### Requirement: Capacity definitions are imported from a mounted document

A compute provisioner MUST reconcile a configured capacity-definitions document
before serving requests, under the same digest contract as resource-pool
definitions: the provisioner records the digest of the document it last reconciled
at startup and applies a document only when the current one differs. The digest MUST
be recorded in the same transaction as the apply. A process start MUST NOT be treated
as a submission: reapplying an unchanged document would revert capacity administration
performed through the API since the last import.

An operator-submitted import through the capacity-definitions import API MUST
reconcile regardless of the recorded digest and MUST NOT record a digest.

Every import MUST upsert the declarations the document names and MUST leave every
declaration the document does not name unchanged. A declaration naming a resource
pool that does not exist MUST fail the whole import, naming the pool, with nothing
applied. A configured document that cannot be read or applied MUST fail startup
rather than be skipped silently, and the startup import MUST run after resource-pool
definitions and host inventory seeding.

A document entry MUST state a declaration with the registration contract's own fields
and MUST replace the whole declaration it names, exactly as a registration request
does. The document MUST NOT accept the legacy scalar unit total, MUST require each
entry's resource type rather than defaulting it, and MUST reject unknown fields.
Document validation MUST report every structural problem it finds, each with its
location, rather than stopping at the first. A document with any structural problem
MUST NOT be evaluated against stored state.

An import MUST compare each entry with the stored declaration before writing, and an
entry equal to the stored declaration MUST write nothing and emit no capacity event,
so reconciling an unchanged or reformatted document does not advance the capacity
version. A refusal only stored state can decide (an unknown pool, a host already
named by an unnamed declaration, a pool move under a live obligation) MUST come from
the same rules registration enforces. For a structurally valid document every such
refusal MUST be reported, and any
refusal MUST leave the whole import unapplied with no digest recorded. The import API
MUST offer a validate-only mode that reports the problems and the planned changes
without applying either.

#### Scenario: Capacity definitions change between restarts

- **WHEN** an operator edits the configured capacity-definitions document and
  restarts the provisioner
- **THEN** the edited declarations are applied, rather than being ignored because
  declarations already existed

#### Scenario: An unchanged document is present at restart

- **GIVEN** capacity has been administered through the API since the last import
- **WHEN** the provisioner restarts with the same capacity-definitions document
- **THEN** no reconciliation occurs and the API administration survives

#### Scenario: An operator explicitly imports an unchanged document

- **WHEN** an operator submits through the import API a document whose digest matches
  the recorded one
- **THEN** the document is reconciled anyway, because the operator has asked
- **AND** the recorded startup digest is unchanged

#### Scenario: A document stops naming a declaration

- **WHEN** a document is imported that omits a declaration an earlier document, the
  API, or derivation created
- **THEN** that declaration remains as it was, including its enabled state

#### Scenario: A declaration names an unknown pool

- **WHEN** a capacity-definitions document names a resource pool that does not exist
- **THEN** the import fails naming the pool, no declaration from the document is
  applied, and no digest is recorded

#### Scenario: A document is reapplied unchanged

- **WHEN** an import names declarations identical to the stored ones
- **THEN** no declaration is written and no capacity event is emitted
- **AND** the import reports them as unchanged

#### Scenario: An entry omits an optional field

- **WHEN** a document entry names an existing declaration but omits its host or
  attributes
- **THEN** the declaration is replaced as a registration request would replace it,
  and the omitted fields are cleared rather than retained

#### Scenario: A document has several problems

- **WHEN** a document carries an unknown field, a missing resource type, and two
  entries naming the same host
- **THEN** the import reports all three with their locations and applies nothing

#### Scenario: A document has structural and stored-state problems

- **WHEN** a document has an unknown field in one entry and names an unknown pool in
  another
- **THEN** the unknown field is reported and the unknown pool is not, because stored
  state is not consulted for a structurally invalid document
- **AND** nothing is applied

#### Scenario: A later entry is refused by stored state

- **WHEN** an import's earlier entries are acceptable and a later entry would move a
  resource that holds a live obligation to another pool
- **THEN** the refusal is reported, no entry from the document is applied, and no
  digest is recorded

#### Scenario: An operator validates a document

- **WHEN** an operator submits a document to the import API in validate-only mode
- **THEN** the response reports the problems and the planned creations, updates, and
  unchanged entries
- **AND** nothing is applied

#### Scenario: Configured document is missing

- **WHEN** a capacity-definitions path is configured but no document exists there
- **THEN** startup fails rather than proceeding with stale or absent declarations

#### Scenario: No capacity definitions are configured

- **WHEN** no capacity-definitions path is configured
- **THEN** startup proceeds and declarations come only from derivation and the
  administration surface

### Requirement: Storefront teardown goes through lease termination

A storefront requesting teardown of a delivered lease MUST request it through the site's
storefront-role lease termination, the same release path lease expiry takes, and MUST
NOT begin fulfillment teardown or release a site reservation directly. A repeated
termination request MUST return the same releasing or released lease. The storefront
MUST learn that capacity was released only from the site's capacity-released callback.

#### Scenario: Buyer requests bare-metal teardown

- **WHEN** a buyer requests teardown of a delivered bare-metal lease at the storefront
- **THEN** the storefront terminates the lease at the site, which begins the lease's
  fulfillment teardown, and the storefront makes no site release call of its own

#### Scenario: Teardown is requested twice

- **WHEN** the storefront repeats termination for a lease already releasing or released
- **THEN** the site returns that lease unchanged and starts no second teardown

### Requirement: Job execution resolves its executor by offering mode and action

Compute provisioning MUST own the table that selects the executor running a job, keyed by
the job's `offering_mode` and the action its executor runs, populated by adapter
bundles, and MUST reject a duplicate `(offering_mode, action)` registration at startup.
Each entry MUST be one complete job executor that executes a job and returns a
normalized outcome and cancels through its own handle; the job engine, not the executor,
knows when a job has finished. The job engine MUST resolve
each job's executor through that table and MUST NOT know how a job runs: no playbook,
fact, inventory, process identifier, or SSH vocabulary, and no domain's parameter
construction. Job persistence and the pre-execution host lookup MUST be independent of
which executor runs. Under the mock profile an adapter MUST register a mock executor for
its own offering mode only.

#### Scenario: A bare-metal access job runs

- **WHEN** a job with offering mode `bare_metal` and a grant or reclaim action runs
- **THEN** it runs through the executor the bare-metal bundle registered, and its result
  is interpreted by bare metal's codec whether that executor is real or mock

#### Scenario: Two bundles claim the same executor key

- **WHEN** two adapter bundles register an executor for the same offering mode and action
- **THEN** compute provisioning refuses to start

### Requirement: Compute provisioning owns the job and host authorities

Compute provisioning MUST own durable physical-execution jobs — their identity, state,
route key, `host_id`, retry counts and timing, scheduling, cancellation through the
executor and its opaque handle, logs, and results and credentials, persisted and served as
`ResultEnvelope` and `CredentialEnvelope` — and operational host registration — host
identity, enabled state, pool association, a connection envelope whose secrets it holds
only in a protected form, and the lookup made immediately before execution, which yields
an immutable execution-host value. An executor MUST decide whether its failure is retryable
and MUST redact what it reports; the job authority decides whether and when a retry
happens. Shared execution technology MAY own the mechanics of invoking a prepared
execution: process lifecycle, transient inventory rendering, redaction, failure
classification, and connectivity probes. The site authority MUST reference a host only
by `host_id` and MUST NOT own provisioning connection information. The provisioning
service's composition root MUST build exactly one job authority and one host authority
and supply both to every adapter runtime; no adapter runtime builds or owns either. The
root supplies the connection codecs a deployment supports, and a domain contributes its
host pool-change hooks as declarations the root merges. Every change of a registered host's
pool MUST go through those hooks, whether it arrives as a host update or in an imported
inventory, and assigning a host the pool it already has is not a move. A hook MAY refuse a
move; a refused move MUST leave every host the operation names unchanged, and a provisioning
route MUST answer it as a conflict (409).

#### Scenario: A host changes pool

- **WHEN** an operator moves a registered host to another pool
- **THEN** the host authority records it and notifies subscribers, and a domain's
  dependent state (such as VM relay rebinding) reacts through that notification

#### Scenario: An imported inventory moves a host a subscriber protects

- **WHEN** an operator imports an inventory that moves a host, whose VM tunnels a buyer
  holds, to a pool dialling another relay
- **THEN** VM's hook refuses the move, the import answers 409, and no host the inventory
  names is created or changed

#### Scenario: An executor reports a non-retryable failure
- **WHEN** a job's executor returns a failure it classifies as not retryable
- **THEN** the job fails without another attempt, whatever attempts remain under the retry policy

#### Scenario: A VM and a bare-metal job are in flight

- **WHEN** both run at once
- **THEN** one job engine and one host registry serve both, and neither domain's adapter
  holds either

### Requirement: A cancelled job stays cancelled

Once a job is cancelled, no outcome its executor reports later MAY change its state. A
cancellation requested before the executor reports its cancellation handle MUST take
effect when the handle is reported.

#### Scenario: A running job is cancelled and its execution then completes

- **WHEN** an operator cancels a running job and its executor afterwards reports success
- **THEN** the job remains cancelled and records no result or credentials from that outcome

#### Scenario: A job is cancelled before its executor reports a handle

- **WHEN** cancellation is requested before the executor has reported a handle
- **THEN** the executor is asked to cancel through the handle as soon as it is reported

### Requirement: Host connections are typed by their implementation's codec

A host's connection MUST be held as a connection envelope (a kind, a version, public
fields, and protected values) whose kind names the codec of the implementation
distribution that supports it. Compute provisioning MUST NOT define per-kind connection
fields; it validates an envelope through its codec. An executor MUST receive an immutable
execution-host value, not the persistence record, and MUST refuse a connection kind it
does not support.

#### Scenario: A compute domain needs another connection kind

- **WHEN** a domain's executor reaches its targets by a means other than SSH
- **THEN** an implementation distribution adds a codec for that kind, and neither the host
  authority's model nor the executor contract changes

### Requirement: Connection secrets stay protected

Connection secrets MUST be persisted, stored, and passed to executors only in a protected
representation (a scheme and its ciphertext). A secret submitted with a host's
connection MUST be turned into a protected value by that connection kind's codec before
it is persisted, and the submitted secret MUST NOT be stored, returned, or logged. The
host authority MUST treat a protected value as opaque, MUST NOT encrypt or decrypt it, and
MUST keep it out of every read, logging, and error surface. Only a connection codec MAY
decrypt a protected value, just in time for execution, and plaintext MUST stay confined
to the submitting request, the codec, and the transient storage the connection requires.

#### Scenario: A host is registered with an embedded key

- **WHEN** an operator registers a host whose `ssh` connection submits a private key
- **THEN** the `ssh` codec protects it, the host authority stores only the protected
  value, and its responses name the protected value and its scheme without the ciphertext

#### Scenario: A job runs against a host with an embedded key

- **WHEN** an executor runs a job against that host
- **THEN** it receives the protected envelope, and only the `ssh` codec decrypts the key,
  into transient storage removed when execution ends

### Requirement: Provisioning adapters import neither each other nor the deployed service

A compute provisioning adapter MUST NOT depend on or import another provisioning
adapter or the deployed provisioning service, including under `TYPE_CHECKING`. It
receives its collaborators from composition. No neutral provisioning module MAY import a
domain's operator client; compatibility flows from a domain client to the neutral
contract.

#### Scenario: Package boundaries are checked

- **WHEN** the import-boundary check runs
- **THEN** neither the VM nor the bare-metal provisioning adapter imports
  `compute_provisioning_service` or the other adapter, and no `compute_provisioning`
  module imports `vm_provisioning_operator`

### Requirement: Domains contribute their inventory views

A domain view in the site's resource-pool projection, whether attached to a projected
resource or to a pool, MUST be produced by a projection the domain's adapter contributes.
The provisioning service MUST NOT name a domain's view, its source attributes, or its
provider configuration. Each projection MUST declare the view identifiers it produces and
the declaration attributes it consumes, a consumed attribute MUST NOT appear in the neutral
projected attributes, and composition MUST refuse a view identifier or consumed attribute
declared by two projections.

#### Scenario: A third domain contributes a view

- **WHEN** a domain contributes a projection producing a resource view under its own
  identifier
- **THEN** projected resources carry that view without any change to the provisioning
  service

#### Scenario: Two projections claim one view

- **WHEN** two contributed projections declare the same view identifier
- **THEN** composition refuses to start

### Requirement: Domain routes are bound through accessors

A provisioning adapter that contributes routes MUST supply them as router factories
taking zero-argument accessors for its collaborators, and MUST NOT import the deployed
service's composition module to find them. A route whose collaborator is not yet
composed MUST answer 503.

#### Scenario: A route is mounted before composition

- **WHEN** the service mounts an adapter's routes before its lifespan has composed the
  adapter's collaborators
- **THEN** the routes resolve them through the accessors at request time, and a request
  arriving before composition answers 503

### Requirement: What is held for a reservation is returned with its capacity

A domain resource held for a reservation's lifetime, such as a relay port, MUST be
returned in the transaction that releases the reservation's capacity, whether the
release guard permits it or an operator forces it, and never on a fulfillment state
alone. The provisioning service MUST NOT name the resource, and a failing return MUST
abort the release.

#### Scenario: A failed fulfillment holds its port

- **WHEN** a VM's fulfillment fails and the release guard refuses its capacity
- **THEN** its relay port stays held until an operator forces the release, which returns both

#### Scenario: An abandoned hold returns a port leased before dispatch

- **WHEN** the release guard abandons an `assigned` aggregate whose create was prepared and leased a relay port
- **THEN** the port is returned in the ledger's transaction, not left to reconciliation

### Requirement: Relay administration admits only the administrator

The relay routes MUST admit only the administrator role: creating, reading, updating,
enabling, disabling, and rotating the token of a relay are operator infrastructure, and no
storefront calls them.

#### Scenario: A storefront signs a relay request

- **WHEN** a request to a relay route is signed under the seller role
- **THEN** it is refused before reaching relay administration

### Requirement: Job-backed fulfillment is the compute family's

A fulfillment provider that executes through the job authority MUST be the compute
family's: it submits, reads status, resolves the provisioned resource, and assembles the
delivery. A domain MUST contribute only its codec and its preparation, which turns a
settled resource into a job and a create job's parameters into its teardown. A job-backed
fulfillment MUST produce one provisioned resource, the one its `executor_target` names.

#### Scenario: A domain prepares a job

- **WHEN** a domain's preparation returns a job for a settled resource
- **THEN** the family submits it, tracks it, and delivers its result, with no further domain code

#### Scenario: Teardown undoes what create ran

- **WHEN** a job-backed fulfillment's teardown is prepared
- **THEN** the domain receives the parameters its create job ran with, and a fulfillment whose create job is missing fails preparation as a configuration error

### Requirement: Jobs are submitted against a registered host

Every job MUST be submitted through the compute family's job submission, which MUST
refuse a host that is not registered. A fulfillment's create MUST also refuse a disabled
host; a teardown or an operator's job MUST NOT. A fulfillment job's operation id MUST
derive from its contract's idempotency key; an operator's job keeps its request's
operation id.

#### Scenario: A disabled host holds a fulfillment

- **WHEN** a host is disabled while a fulfillment on it is active
- **THEN** that fulfillment's teardown is submitted, and a new create on the host is refused

### Requirement: Jobs are correlated by capacity reservation

A fulfillment's job MUST record the capacity reservation it serves, and no job MAY record
a deal reference, because a deal's commercial identity does not cross the provisioning
boundary for correlation. The job list MUST filter by capacity reservation and MUST NOT
filter by escrow.

#### Scenario: An operator finds a deal's jobs

- **WHEN** a seller maps a buyer's negotiation to its capacity reservation and filters the job list by it
- **THEN** the deal's jobs are returned, whatever settlement mechanism the deal used

### Requirement: A create succeeds only with readable delivery evidence

A codec MUST report a create job's result as the compute family's create result: the
delivery evidence (the endpoints to connect to and when access became ready), or none
when the output cannot say, and a detail mapping of non-secret operator data. A create
job reported succeeded MUST NOT make its fulfillment active unless its evidence is valid;
otherwise the fulfillment MUST fail. The family MUST NOT read or deliver the detail.

#### Scenario: A create job's evidence is unreadable

- **WHEN** a create job succeeds but its result carries no valid delivery evidence
- **THEN** its fulfillment fails, and its capacity is held as for any failed create

#### Scenario: A relay-backed VM is delivered

- **WHEN** a VM is created behind a relay
- **THEN** its delivery's endpoint is the relay's address and leased port, not its host's

### Requirement: Delivery says how to reach what was provisioned

A fulfillment's delivery MUST carry only the endpoints to connect to, the credentials
issued, each by role with an allowlisted set of fields, and when access became ready. It
MUST NOT carry a provisioner-side path, an address internal to a host, a deal reference,
a lease window, or a credential field outside the allowlist.

#### Scenario: A VM is delivered

- **WHEN** a VM fulfillment becomes active
- **THEN** its delivery carries the tenant's endpoint and credentials, and not the guest's internal address or a key path on its host

### Requirement: Provisioning names what it provisions

Provisioning MUST name the resource a job creates, deriving the name from the capacity
reservation so a retry names the same resource, and the name MUST satisfy every use the
resource's playbooks make of it. A storefront MUST NOT supply it, and a request naming one
MUST be refused. The lease's target MUST be the one the reservation's fulfillment recorded.

#### Scenario: A lease reports its target

- **WHEN** a VM fulfillment becomes active
- **THEN** the lease reports the guest its fulfillment named, without a storefront naming it

#### Scenario: A VM guest is named

- **WHEN** a VM create is prepared for a capacity reservation
- **THEN** the guest is named `tenant-` and the first 24 hex characters of a UUIDv5 of the
  reservation's identifier, the same on every retry
- **AND** the name is a valid hostname label, contains no other guest's name, and uses only
  lowercase letters, digits, and a hyphen
- **AND** stripped to letters and digits it is a login of at most 32 characters starting
  with a letter, which `useradd` accepts

#### Scenario: A fulfillment request names a guest

- **WHEN** a VM fulfillment request names a guest
- **THEN** it is refused, and nothing is prepared

#### Scenario: A fulfillment accepted earlier is requested again

- **WHEN** a request is repeated for a fulfillment whose create was already prepared
- **THEN** the fulfillment keeps the name its create was prepared with

### Requirement: Every provisioning route admits the administrator

Every route on the provisioning service's route table MUST admit the `admin` role, in
addition to any other role it admits. A route contract a domain contributes that does not
admit `admin` MUST be refused when the table is assembled.

#### Scenario: An operator calls a storefront route

- **WHEN** a request signed by the provisioning administrator calls a route that also
  admits the seller, such as lease termination or fulfillment begin
- **THEN** it is authorized as it would be for the seller

#### Scenario: A domain contributes a seller-only route

- **WHEN** a domain declares a route whose roles omit `admin`
- **THEN** the provisioning service refuses to assemble its route table

### Requirement: Leases have one family surface that records and releases

Compute provisioning MUST serve every offering mode's leases through one route surface
returning the neutral lease view: get, list, terminate, release-oversight, retry-release,
and force-release. Get and terminate MUST admit the seller and the administrator; list,
release-oversight, retry-release, and force-release MUST admit the administrator only. No
lease route writes a lease. A lease MUST be addressed by its capacity reservation identifier;
the list MAY filter by lease status and offering mode and MUST NOT filter by a deal's
commercial identity or by host. A lease route MUST NOT deliver: no lease route grants
access, creates a workload, or submits provider work, and a domain MUST NOT add or
override lease routes. A domain MAY extend what a lease reports only by contributing a
versioned projection.

#### Scenario: An operator lists bare-metal leases

- **WHEN** an administrator lists leases filtered by offering mode `bare_metal`
- **THEN** the response carries every bare-metal lease as the neutral lease view

#### Scenario: A storefront asks for the lease list

- **WHEN** a request signed as the seller calls the lease list
- **THEN** it is refused, and the storefront reads its own leases by reservation id

#### Scenario: Bare-metal access is granted

- **WHEN** a bare-metal deal is delivered
- **THEN** access is granted only through the fulfillment aggregate, and provisioning
  records the machine as the lease's target when the fulfillment becomes active

### Requirement: A lease's executor identity and evidence are fixed once recorded

No caller writes a lease. Commit MUST record a lease's window; provisioning MUST record its
executor target when the reservation's fulfillment becomes active, in the transaction that
makes it active, as the target that fulfillment recorded; and the lease lifecycle records
release. A recorded target MUST NOT be replaced. A target the data prevents recording
(metadata naming no job-backed target, or a reservation the site refuses) MUST NOT fail
the activation; any other failure to record it MUST leave the fulfillment unactivated, for
convergence to retry. Convergence MUST keep recording the target of every active
job-backed fulfillment whose reservation records none, and MUST report each it cannot
record and each reservation that records a different target. No route MAY change a lease's executor identity, its start, or its create or
release handles once recorded, and its end MAY move only through the site authority's lease
truncation.

#### Scenario: A fulfillment becomes active

- **WHEN** a reservation's job-backed fulfillment becomes active
- **THEN** the reservation records the target that fulfillment acts on, in the same
  transaction, and its state and window are unchanged

#### Scenario: A target is already recorded

- **WHEN** a fulfillment becomes active on a reservation that already records another target
- **THEN** the recorded target is kept, the fulfillment still becomes active, and each
  convergence cycle reports the difference

#### Scenario: Recording the target fails for a reason other than the data

- **WHEN** recording the target fails while a fulfillment becomes active, other than for
  its data
- **THEN** the fulfillment stays unactivated, and a later convergence cycle activates it
  and records the target

#### Scenario: An active fulfillment's lease records no target

- **WHEN** a convergence cycle finds an active job-backed fulfillment whose reservation
  records no target
- **THEN** it records the target where it now can, and reports it where it cannot

#### Scenario: A lease body is posted

- **WHEN** a caller posts a lease to the lease routes
- **THEN** it is refused, and nothing is recorded

### Requirement: Execution readiness is reported in system status

The provisioning service's system status MUST report whether execution is mocked, as a
boolean for the deployment and per composed executor by offering mode, derived from the
composed executors rather than from deployment profiles, together with each contributed
readiness component's readiness and a versioned detail. A component that is not ready MUST
degrade the status. The status MUST NOT disclose a database URL or any credential.
Readiness MUST have no route of its own, and an execution implementation MUST contribute
its readiness rather than serve it.

#### Scenario: Every executor is mocked

- **WHEN** the service runs with every composed executor mocked
- **THEN** status reports execution as mocked, and lists each offering mode's executor as
  mocked

#### Scenario: A domain's playbook is missing

- **WHEN** the Ansible executor for one offering mode names a playbook that does not exist
- **THEN** the Ansible component reports that playbook and is not ready, and the status is
  degraded

### Requirement: Host connectivity is probed by connection kind

A host connectivity check MUST run the probe registered for the host's connection kind and
return a neutral connectivity result. A host whose connection kind has no registered probe
MUST be refused. The probe's execution resources MUST be composed by the provisioning
service, not borrowed from a domain's runtime.

#### Scenario: A bare-metal host is probed

- **WHEN** an operator checks connectivity to a registered bare-metal host with an `ssh`
  connection
- **THEN** the `ssh` probe runs over the service's own runner and returns the neutral result

### Requirement: Delivery happens only through fulfillment

No provisioning route MAY submit delivery work (creating a workload or granting access) outside a fulfillment aggregate, for any offering mode. The provisioning service MUST NOT serve a generic executor-action route, and a domain MUST NOT contribute one.

#### Scenario: An operator looks for a direct grant

- **WHEN** an operator wants to grant bare-metal access or create a VM for a reservation
- **THEN** the only path is the reservation's fulfillment, and no provisioning route submits that work directly

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
- When the create is in flight (`dispatch_pending` or `dispatching`), the release MUST be remembered durably, with the reservation `releasing` and the fulfillment as its release handle, and teardown MUST begin once the aggregate reaches `active`; the grace timeout MUST NOT run while the create is in flight.
- A `failed` aggregate, or an absent, `assigned`, or `abandoned` one without that proof, MUST put the lease in `release_failed` for an operator to verify and force-release.
- A teardown observed as `teardown_failed` while the lease is `releasing` MUST put the lease in `release_failed`; an operator's retry-release MUST re-observe the same aggregate.

The compute provisioning composition MUST supply the site authority's release guard, which permits freeing a reservation's capacity only for a `torn_down` aggregate or for an absent, `assigned`, or `abandoned` one whose provenance proof holds, and MUST check that proof in the transaction that frees the capacity. Every direct capacity return, whether by the lease lifecycle or by any caller of the site's release, MUST pass that guard; force-release remains the operator's recorded override.

#### Scenario: A committed lease whose fulfillment never began expires

- **WHEN** a lease's reservation was committed but its fulfillment was never dispatched, and the lease reaches its end
- **THEN** the assigned aggregate is abandoned, the capacity returns, and no teardown is attempted

#### Scenario: A lease is terminated while its create is in flight

- **WHEN** a lease is terminated while its fulfillment is `dispatching`
- **THEN** the reservation becomes `releasing` at once, survives a restart in that state, and its teardown begins when the aggregate reaches `active`

#### Scenario: A create failed

- **WHEN** a lease is released and its aggregate is `failed`
- **THEN** the lease enters `release_failed`, and capacity stays held until an operator force-releases it

#### Scenario: Teardown fails while the lease is releasing

- **WHEN** a releasing lease's aggregate reaches `teardown_failed`
- **THEN** the lease enters `release_failed`, and when convergence's retry later reaches `torn_down`, an operator's retry-release adopts that teardown and releases the capacity

#### Scenario: A storefront releases a delivered lease

- **WHEN** a storefront asks the site to release a reservation whose aggregate is `active`
- **THEN** the release guard refuses, the reservation keeps its capacity and state, and the lease is released only through its lifecycle

### Requirement: Host import belongs to the execution implementation that reads its format

A host-import route that reads an implementation's inventory format MUST be contributed by that implementation, with its route contract, route service, and typed client; the compute family's host routes MUST serve only format-neutral host administration and connectivity.

#### Scenario: Hosts are imported from an Ansible inventory

- **WHEN** an operator imports hosts from an Ansible INI inventory
- **THEN** the Ansible implementation's import route parses it and registers the hosts through the host authority, and the family's host route contracts name no inventory format

### Requirement: Lease release delegates to durable fulfillment teardown

For every offering mode, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The release adapter SHALL be provider-neutral, SHALL use the durable `fulfillment_id` as the release tracking identifier, and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL read fulfillment aggregate state and SHALL NOT be selected by the reservation's offering mode.

#### Scenario: Release status is read from the aggregate

- **WHEN** lease lifecycle reads release status for a VM or a bare-metal reservation
- **THEN** both reads go through the same status port to the fulfillment aggregate, whose teardown state decides the outcome

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

#### Scenario: A bare-metal lease expires

- **WHEN** a delivered bare-metal lease passes its end
- **THEN** release begins the bare-metal fulfillment's teardown, the aggregate leaves `active`, and capacity stays held until it reaches `torn_down`

### Requirement: A committed allocation's lease records its executor target
Market-managed leases MUST record the executor target on an existing committed site allocation, when the allocation's fulfillment becomes active; the lease window is the one its commit recorded. The allocation's offering mode is the one the site recorded when capacity was claimed, and executor-specific reference data such as a physical-host identity MUST stay with the fulfillment that delivered the workload rather than the lease.

#### Scenario: Bare-metal lease records its machine
- **WHEN** a bare-metal fulfillment granting access on a committed allocation becomes active
- **THEN** provisioning records the machine as the lease's target, and the allocation keeps its recorded `bare_metal` offering mode and committed window, with the physical-host identity staying in the fulfillment's metadata

#### Scenario: Teardown cannot begin after the release is recorded
- **WHEN** a lease is terminated and beginning its fulfillment's teardown fails
- **THEN** the lease is `releasing` with the fulfillment as its handle, and the lease lifecycle begins the teardown on a later cycle, including after a restart

## Evidence

- Bare-metal obligation servicing resolved from the accepted Agreement: `domains/bare_metal/storefront/tests/test_obligation_servicing.py` and `test_app_composition.py`.
- VM and bare-metal allocation executor metadata: `provisioning/compute/service/tests/integration/test_leases_api.py` and `test_bare_metal_leases_api.py`.
- Multidimensional scheduling eligibility, including secondary-dimension rejection and GPU-only requests: `provisioning/compute/service/tests/integration/test_scheduling_composition.py`.
- Persisted asynchronous job lifecycle and polling: `provisioning/compute/service/tests/integration/test_vms_api.py`.
- Executor-specific release, failed-release capacity retention, retry, and force release: `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`, `test_leases_api.py`, and `unit/services/test_ledger_lease_lifecycle.py`.
- Adapter composition and generic import boundaries: `provisioning/compute/service/tests/unit/test_composition.py` and `test_import_boundaries.py`.
- VM sizing precedence (committed reservation, pool default, unset), relay access-path selection, and teardown from the lease: `domains/vms/provisioning/adapter/tests/unit/test_vm_fulfillment_plan.py` (`TestSizingPrecedence`, `TestRelayAccessPath`, `TestTeardown`); the delivered credentials and endpoint: `provisioning/compute/service/tests/integration/test_fulfillment_api.py::TestStatusAndResultQueries`.
- Relay administration, token confidentiality, rebinding, and definition-document reconciliation: `provisioning/compute/service/tests/integration/test_relay_administration.py`, `test_relay_port_allocator.py`, `test_relay_port_leases.py`, `test_relays_api.py` through the canonical client, plus `tests/unit/services/test_definition_document_restart_safety.py`.
- Relay ports held through fulfillment convergence, including a failed creation, and the reservation-released predicate reconciliation is given: `provisioning/compute/service/tests/integration/test_fulfillment_convergence.py`; their return with a reservation's capacity: `provisioning/compute/tests/integration/test_release.py` and `kit/site/tests/integration/test_ledger.py`.

`PhysicalSettlementScheduler` and fulfillment-provider coordination are durable, not process-local: scheduling, acceptance, and dispatch state live in the fulfillment aggregate (see `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`), and a dedicated periodic worker recovers in-flight provider operations after a crash or restart (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` and `docs/development/ARCHITECTURE.md#recovery-workers`). This is a database-wide SQLite writer guarantee, not a distributed multi-replica protocol.

## Capacity settlement lifecycle

Physical provisioning distinguishes **Capacity Reservation → Capacity Settlement Assignment → Physical Settlement → Provisioned Resource / Active Workload**. Generic scheduling chooses an eligible Settlement Resource. Physical Settlement is provider-specific execution on that assigned resource. Provider-specific reachability, credentials, topology, and execution failures remain downstream of generic scheduling eligibility.

Scheduling uses deterministic round-robin through a replaceable policy interface. Generic policy and orchestration code use resource kind, a per-dimension quantity map (`dimensions`/`available`, checked against every requested dimension), pool identity, and opaque attributes and do not import market-specific executor persistence models.

## Relationship to fulfillment

The [fulfillment specification](../fulfillment/spec.md) owns provider-neutral settlement requests, settlement-resource scheduling, provider contracts, lifecycle identifiers, and versioned provider envelopes. This specification begins at compute-service composition and concrete executor/provider dispatch.

The compute provisioner may compose both a fulfillment-provider registry and an executor registry, but they remain distinct namespaces. Scheduling selects a `SettlementResource`; provider execution acts on that resource; executor dispatch performs domain-specific infrastructure actions. No one registration implicitly selects another.

Generic compute service modules may import `market_fulfillment`. `market_fulfillment` must not import the deployed compute service or VM/bare-metal adapters.
