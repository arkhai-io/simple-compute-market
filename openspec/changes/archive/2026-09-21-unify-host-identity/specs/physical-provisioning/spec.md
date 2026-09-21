## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job. Create metadata MUST retain the exact `host_id` and `vm_target`, and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

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
- **THEN** the adapter targets the recorded `host_id` and `vm_target` from fulfillment metadata

#### Scenario: A committed dimension is present

- **WHEN** the scheduled settlement resource carries a committed VM dimension
- **THEN** the adapter translates that value through the pool-selected requirement delegate and ignores any conflicting caller-supplied sizing field

#### Scenario: A committed dimension is absent and the pool has a default

- **WHEN** the committed reservation omits a VM dimension and the resolved pool configures the corresponding default
- **THEN** the adapter uses the pool default for that dimension

#### Scenario: A committed dimension and pool default are both absent

- **WHEN** neither the committed reservation nor the resolved pool supplies a VM dimension
- **THEN** the adapter leaves the corresponding provider input unset so the selected playbook or inventory may supply its own default
