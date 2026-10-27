## MODIFIED Requirements

### Requirement: Compute-owned caller contract
Shared storefront/provisioner DTOs, the job, host, credential, lease, system-status, worker-control, and mock-rule wire models, and the family's route contracts MUST be owned by compute provisioning rather than the VM domain, in a contracts distribution that depends on no service, persistence, or web-framework package. Routes the provisioning service hosts for another capability, such as resource-pool administration and capacity-definition import, MUST keep that capability's models, contracts, and client; hosting a route does not make it compute provisioning's. The family's typed client MUST be a separate client distribution depending on no service, persistence, or web-framework package: only that contracts distribution, the core carrier package, the identity kit, its HTTP library, and its model library; it offers async and sync variants with identical operations, and the family kit itself MUST contain no client. The family's mock mechanism is the family's capability wherever it is mounted: the contracts distribution MUST own its route contracts as one template instantiated by a mount, a path prefix and an operation-name prefix, and the family client MUST offer its typed client over a mount; a compute domain MUST contribute only its mount for those routes, never declarations of its own. Each compute domain's client package MAY offer an extension over the family client's authenticated transport for other routes that domain mounts; direct VM operator APIs MAY retain VM-owned VM action, relay, and VM pool-configuration models; callers import compute-owned models from the contracts distribution. Compute provisioning MUST NOT name a domain's routes: a domain, an execution implementation, or another capability MUST contribute the route contracts of the routes it mounts, and for the mock mechanism's routes a domain contributes them through its mount. The service's request authentication MUST resolve requests against the table the provisioning service's composition root assembles from those contributions; each typed client MUST sign its routes from its owner's contracts. Where the owner's contracts are one declaration that both the service's table and the client read, as the compute family's, the resource-pool authority's, the Ansible implementation's, and each domain's are, operation, resource binding, and roles cannot diverge. Where an owner keeps separate server and client declarations, as the site capacity authority does, a contract-parity test MUST hold the two equal in method, path, operation, resource binding, and the models they exchange.

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

#### Scenario: A test reads a mock rule through the family client
- **WHEN** a test lists or installs a bare-metal or VM mock rule through the family's mock-rule client, constructed with that domain's mount
- **THEN** the request is signed with the domain's existing path and operation name, and the test receives the family's typed rule model from the contracts distribution

#### Scenario: A compute domain mounts the mock mechanism
- **WHEN** a compute domain mounts the mock mechanism's routes
- **THEN** it states its path prefix and operation-name prefix, and its route contracts and typed client come from the family without a declaration of its own

#### Scenario: An operator runs a worker control
- **WHEN** an operator checks leases, runs or advances a convergence cycle, or rotates the provisioning identity through the family client
- **THEN** the answer is a typed model from the contracts distribution

## ADDED Requirements

### Requirement: The provisioning service answers an unroutable request by what failed to match

The provisioning service's authentication middleware MUST answer a request that resolves to
no route contract, without signing it, with 404 when no contract names its path, 405 naming
the allowed methods when a contract names its path under another method, and 400 naming the
field when its route's body resource cannot be bound. Such an answer is unsigned because no
contract supplies the operation and resource a response proof binds.

A route contract's path pattern MUST consist of literal segments, single-segment named
captures (`[^/]+`), and finite alternations of literal segments, and building a contract
from a declaration MUST refuse any other pattern. Composing the route table MUST compare
the contracts of different contributions segment by segment and MUST refuse, before the
service accepts traffic, two whose method and segments can match one request. Within one
contribution, the first matching contract MUST decide, in the order its owner gave.

#### Scenario: An unknown path is requested

- **WHEN** a request names a path no route contract matches
- **THEN** the service answers an unsigned 404 before checking authentication

#### Scenario: A known path is requested with another method

- **WHEN** a request uses a method no contract binds to a path a contract names
- **THEN** the service answers an unsigned 405 whose `Allow` names the contract's methods

#### Scenario: A route's body resource is missing

- **WHEN** a request matches a route whose bound resource is a body field it omits
- **THEN** the service answers an unsigned 400 naming the field

#### Scenario: Two contributions claim one route

- **WHEN** the route table is composed from two contributions whose contracts, compared
  segment by segment, can both match one method and path
- **THEN** composition is refused before the service accepts traffic

#### Scenario: A contract's pattern is outside the grammar

- **WHEN** a contribution declares a route whose pattern uses a construct other than a
  literal segment, a single-segment capture, or a literal alternation
- **THEN** building its contract is refused, naming the route

#### Scenario: One contribution orders overlapping routes

- **WHEN** one contribution declares a literal route before a capture route that would also
  match it
- **THEN** composition succeeds and a request for the literal path resolves to the literal
  route

### Requirement: The family client names an unauthenticated answer

The compute provisioning client MUST report an answer that carries no response
authentication as unauthenticated, with its status, distinctly from one whose
authentication is malformed or from another principal. It MUST still refuse the answer,
and the report MUST contain no part of the response body, no header value, and no
credential.

#### Scenario: The client and service route tables differ

- **WHEN** the client sends a request the service's table does not route and receives an
  unsigned 405
- **THEN** the client refuses it and reports an unauthenticated 405

### Requirement: An operator-named VM guest satisfies provisioning's naming rules

VM's operator route that creates a VM by name MUST refuse, with 422 and before anything is
prepared, a guest name that is not a valid hostname label or whose login, stripped to
letters and digits, is not at most 32 characters starting with a letter.

#### Scenario: An operator names a guest whose login is too long

- **WHEN** an operator creates a VM named so that its login exceeds 32 characters
- **THEN** the request is refused with 422 naming the rule, and no job is submitted
