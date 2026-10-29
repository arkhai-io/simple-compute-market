## RENAMED Requirements

- FROM: `### Requirement: Legacy host capacity is derived into declarations`
- TO: `### Requirement: Host writes declare no capacity`

## MODIFIED Requirements

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job; the resolved playbook is the pool's `playbook_path` when the pool states one, and otherwise the service's `vm_playbook_path` as configured when the job is prepared. Create metadata MUST retain the exact `host_id` and `executor_target` (the guest provisioning named), and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

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

#### Scenario: A VM pool states no playbook

- **WHEN** a VM job is prepared for a pool whose provider configuration states no `playbook_path`
- **THEN** the job's stored parameters carry the service's `vm_playbook_path` as configured at preparation

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
seeding inventory. A bare-metal inventory host MAY name its exact pool through
`pool_id`; the seed MUST reject an unknown pool and MUST preserve that binding
on create and update. A capacity declaration's explicit `bare_metal_publication`
view MUST carry the declaration's own pool. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration:
execution uses service-owned configuration and the scheduler-selected Physical
Resource, and a bare-metal job's stored parameters carry the service's
`bare_metal_playbook_path` as configured when the job is prepared. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and an unknown pool id fails the seed rather than leaving the host unplaced or assigning another pool

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

#### Scenario: The bare-metal playbook setting changes after a grant is prepared

- **WHEN** `bare_metal_playbook_path` changes after a grant or reclaim job is prepared
- **THEN** the job runs the playbook its stored parameters carry, and a job prepared afterwards carries the new one

### Requirement: Host writes declare no capacity

A compute provisioner MUST NOT create a capacity declaration from a host record on any host write: not when host inventory is applied from an INI document, whether seeded at startup or submitted through the host import API, and not when a host is created or updated through the individual host API. A host's GPU count and model are descriptive and MUST NOT affect capacity. Capacity MUST be declared only through capacity registration, a capacity-definitions document, or capacity import. The ordered migration derived a declaration once for host records with a positive legacy GPU count present at upgrade.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner applies host inventory carrying GPU counts from an INI
  document, at startup or through the host import API, and no capacity declarations
  exist
- **THEN** the hosts are registered, no capacity declaration is created for them, and
  the capacity projection contains no entry for them

#### Scenario: Existing hosts at upgrade

- **WHEN** the ordered migration runs against a database holding hosts with legacy
  GPU counts and no correlated declarations
- **THEN** each such host receives a derived declaration before the service serves
  requests

#### Scenario: Operator declaration and legacy host value disagree

- **WHEN** a host carries a GPU count and an operator has declared different
  capacity for the same Physical Resource
- **THEN** the operator's declaration is retained unchanged and the host's value does
  not affect it

#### Scenario: A declaration's resource id differs from its host

- **WHEN** a declaration whose resource id differs from a host's `host_id` names that
  host as its `host_id`
- **THEN** the host is treated as declared

#### Scenario: A host is created through the individual host API

- **WHEN** an operator creates a host with a GPU count through the individual host API
- **THEN** no declaration is created, and the host's capacity is declared through the
  capacity administration surface

#### Scenario: A host has no GPUs

- **WHEN** host inventory is applied for a host whose GPU count is zero
- **THEN** no declaration is created for it, as for any host

## ADDED Requirements

### Requirement: A domain's service playbook setting is named for its domain

The provisioning service MUST read the VM playbook from `vm_playbook_path` and the bare-metal playbook from `bare_metal_playbook_path`, and MUST refuse to start when its configuration sets the retired `playbook_path`, naming `vm_playbook_path` as its replacement. No alias for the retired name is read.

#### Scenario: A configuration sets the retired key

- **WHEN** the provisioning service starts with `playbook_path` set in any configuration layer
- **THEN** startup fails with an error naming `vm_playbook_path`

#### Scenario: A configuration sets the VM playbook

- **WHEN** the provisioning service starts with `vm_playbook_path` set
- **THEN** VM jobs whose pool states no playbook are prepared with that path
